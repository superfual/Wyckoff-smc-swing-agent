"""
Binance MCP Paper Host Harness
Wyckoff + SMC Spot Swing Agent

Composes a read-only Binance MCP market-data stack with PaperRuntime. The host
also exposes a persistent portfolio kill switch and a non-mutating live-feed
preflight before paper portfolio state is allowed to advance.
"""

from __future__ import annotations

from dataclasses import dataclass
from time import sleep
from typing import Any, Callable, Sequence

try:
    from .binance_adapter import BinanceAdapterConfig, BinanceMarketDataProvider
    from .binance_live_paper_validation import BinanceLivePaperPreflight, validate_binance_live_paper_feed
    from .binance_mcp_bridge import BinanceMCPBridgeConfig, BinanceMCPClientBridge
    from .binance_watchlist_acquisition import (
        BinanceWatchlistAcquisitionConfig,
        BinanceWatchlistPipelineResult,
        acquire_and_validate_watchlist,
    )
    from .paper_report import PaperCycleReport, build_paper_cycle_report
    from .paper_runtime import (
        PaperRuntime,
        PaperRuntimeConfig,
        RuntimeCycleResult,
        create_paper_runtime,
        run_runtime_cycle,
        run_runtime_cycle_with_markets,
    )
    from .paper_runner import PaperRunnerConfig, build_closed_snapshot
    from .paper_session import PaperSessionConfig
    from .paper_trading import PaperTradingConfig
    from .portfolio_safety import PortfolioSafetyConfig, set_kill_switch
    from .orchestrator import AgentConfig
    from .risk import RiskConfig
    from .execution import ExecutionConfig
    from .scanner import load_watchlist
    from .watchlist_validation import WatchlistValidationConfig
except ImportError:
    from binance_adapter import BinanceAdapterConfig, BinanceMarketDataProvider
    from binance_live_paper_validation import BinanceLivePaperPreflight, validate_binance_live_paper_feed
    from binance_mcp_bridge import BinanceMCPBridgeConfig, BinanceMCPClientBridge
    from binance_watchlist_acquisition import (
        BinanceWatchlistAcquisitionConfig,
        BinanceWatchlistPipelineResult,
        acquire_and_validate_watchlist,
    )
    from paper_report import PaperCycleReport, build_paper_cycle_report
    from paper_runtime import (
        PaperRuntime,
        PaperRuntimeConfig,
        RuntimeCycleResult,
        create_paper_runtime,
        run_runtime_cycle,
        run_runtime_cycle_with_markets,
    )
    from paper_runner import PaperRunnerConfig, build_closed_snapshot
    from paper_session import PaperSessionConfig
    from paper_trading import PaperTradingConfig
    from portfolio_safety import PortfolioSafetyConfig, set_kill_switch
    from orchestrator import AgentConfig
    from risk import RiskConfig
    from execution import ExecutionConfig
    from scanner import load_watchlist
    from watchlist_validation import WatchlistValidationConfig

ToolCall = Callable[[str, dict[str, Any]], Any]


class CallableMCPInvoker:
    def __init__(self, tool_call: ToolCall) -> None:
        if not callable(tool_call):
            raise TypeError("tool_call must be callable")
        self._tool_call = tool_call

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        return self._tool_call(tool_name, arguments)


@dataclass(frozen=True)
class BinancePaperHostConfig:
    runtime: PaperRuntimeConfig = PaperRuntimeConfig()
    bridge: BinanceMCPBridgeConfig = BinanceMCPBridgeConfig()
    adapter: BinanceAdapterConfig = BinanceAdapterConfig()
    runner: PaperRunnerConfig = PaperRunnerConfig()
    paper: PaperTradingConfig = PaperTradingConfig()
    portfolio_safety: PortfolioSafetyConfig = PortfolioSafetyConfig()
    agent: AgentConfig = AgentConfig()
    risk: RiskConfig = RiskConfig()
    execution: ExecutionConfig = ExecutionConfig()
    session: PaperSessionConfig = PaperSessionConfig()


def live_binance_paper_host_config() -> BinancePaperHostConfig:
    """Return production-paper-safe defaults for a real read-only Binance feed."""
    return BinancePaperHostConfig(
        runtime=PaperRuntimeConfig(
            checkpoint_path="state/binance_live_paper.json",
            auto_recover=True,
            checkpoint_after_cycle=True,
            require_all_symbols=True,
        ),
        runner=PaperRunnerConfig(
            reference_timeframe="1h",
            require_reference_candle=True,
            require_exact_reference_close=True,
            continue_on_symbol_error=True,
            fair_same_cycle_allocation=True,
        ),
        paper=PaperTradingConfig(reference_timeframe="1h"),
        agent=AgentConfig(trading_mode="SPOT"),
        execution=ExecutionConfig(trading_mode="SPOT"),
    )


@dataclass
class BinancePaperHost:
    runtime: PaperRuntime
    provider: BinanceMarketDataProvider
    config: BinancePaperHostConfig


@dataclass(frozen=True)
class BinancePaperCycleOutput:
    result: RuntimeCycleResult
    report: PaperCycleReport


@dataclass(frozen=True)
class BinanceControlRoomOutput:
    """One acquisition/preflight/paper-cycle result for operator inspection."""

    status: str
    pipeline: BinanceWatchlistPipelineResult
    result: RuntimeCycleResult | None = None
    report: PaperCycleReport | None = None

    @property
    def decision_time(self) -> int:
        return self.pipeline.acquisition.decision_time


def create_binance_paper_host(
    tool_call: ToolCall,
    *,
    symbols: Sequence[str] | None = None,
    config: BinancePaperHostConfig | None = None,
) -> BinancePaperHost:
    cfg = config or BinancePaperHostConfig()
    invoker = CallableMCPInvoker(tool_call)
    bridge = BinanceMCPClientBridge(invoker, cfg.bridge)
    provider = BinanceMarketDataProvider(bridge, cfg.adapter)
    runtime = create_paper_runtime(symbols=symbols, runtime_config=cfg.runtime, session_config=cfg.session)
    return BinancePaperHost(runtime=runtime, provider=provider, config=cfg)


def create_live_binance_paper_host(
    tool_call: ToolCall,
    *,
    symbols: Sequence[str] | None = None,
    config: BinancePaperHostConfig | None = None,
) -> BinancePaperHost:
    """Create a real-feed paper host with fail-closed Spot defaults."""
    return create_binance_paper_host(
        tool_call,
        symbols=symbols,
        config=config or live_binance_paper_host_config(),
    )


def set_binance_paper_kill_switch(host: BinancePaperHost, active: bool) -> None:
    """Persistently block/unblock new paper entries without force-closing positions."""
    set_kill_switch(host.runtime.session.portfolio_safety, active)


def validate_binance_paper_feed(host: BinancePaperHost, *, decision_time: int) -> BinanceLivePaperPreflight:
    """Validate real read-only feed freshness/completeness without mutating paper state."""
    cfg = host.config
    return validate_binance_live_paper_feed(
        host.runtime,
        host.provider,
        decision_time=decision_time,
        runtime_config=cfg.runtime,
        runner_config=cfg.runner,
        agent_config=cfg.agent,
        execution_config=cfg.execution,
    )


def run_binance_paper_cycle(host: BinancePaperHost, *, decision_time: int) -> RuntimeCycleResult:
    cfg = host.config
    return run_runtime_cycle(
        host.runtime,
        host.provider,
        decision_time=decision_time,
        runtime_config=cfg.runtime,
        runner_config=cfg.runner,
        paper_config=cfg.paper,
        agent_config=cfg.agent,
        risk_config=cfg.risk,
        execution_config=cfg.execution,
        portfolio_safety_config=cfg.portfolio_safety,
    )


def run_binance_paper_cycle_with_report(host: BinancePaperHost, *, decision_time: int) -> BinancePaperCycleOutput:
    result = run_binance_paper_cycle(host, decision_time=decision_time)
    report = build_paper_cycle_report(result, host.runtime.session)
    return BinancePaperCycleOutput(result=result, report=report)


def run_binance_control_room_cycle(
    host: BinancePaperHost,
    *,
    captured_at: int,
    acquisition_config: BinanceWatchlistAcquisitionConfig | None = None,
    sleep_fn: Callable[[float], None] = sleep,
) -> BinanceControlRoomOutput:
    """Acquire, validate, then conditionally advance one Spot paper cycle.

    Acquisition and preflight failures return before the paper session, runner
    state, positions, cash, or checkpoint can be changed. A READY batch is fed
    directly into the runtime; the host does not fetch a second snapshot.
    """
    configured = {item.symbol: item for item in load_watchlist()}
    try:
        watchlist = [configured[symbol] for symbol in host.runtime.symbols]
    except KeyError as exc:
        raise ValueError(f"Runtime symbol is not enabled in config/watchlist.json: {exc.args[0]}") from exc

    pipeline = acquire_and_validate_watchlist(
        host.provider.client,
        watchlist,
        captured_at=captured_at,
        account_equity=host.runtime.session.equity,
        acquisition_config=acquisition_config,
        validation_config=WatchlistValidationConfig(reference_timeframe=host.config.runner.reference_timeframe),
        agent_config=host.config.agent,
        risk_config=host.config.risk,
        execution_config=host.config.execution,
        sleep_fn=sleep_fn,
    )
    if pipeline.status != "READY":
        return BinanceControlRoomOutput(pipeline.status, pipeline)

    cfg = host.config
    closed_markets = [
        build_closed_snapshot(
            market,
            decision_time=pipeline.acquisition.decision_time,
            reference_timeframe=cfg.runner.reference_timeframe,
        )
        for market in pipeline.acquisition.markets
    ]
    result = run_runtime_cycle_with_markets(
        host.runtime,
        closed_markets,
        decision_time=pipeline.acquisition.decision_time,
        runtime_config=cfg.runtime,
        runner_config=cfg.runner,
        paper_config=cfg.paper,
        agent_config=cfg.agent,
        risk_config=cfg.risk,
        execution_config=cfg.execution,
        portfolio_safety_config=cfg.portfolio_safety,
    )
    report = build_paper_cycle_report(result, host.runtime.session)
    status = "PAPER_CYCLE_COMPLETE" if result.processed else "PAPER_CYCLE_FAILED"
    return BinanceControlRoomOutput(status, pipeline, result, report)


def render_binance_control_room_output(output: BinanceControlRoomOutput) -> str:
    acquisition = output.pipeline.acquisition
    lines = [
        f"BINANCE SPOT CONTROL ROOM: {output.status}",
        f"Decision time: {acquisition.decision_time} | Mode: PAPER ONLY",
        "Safety: CLOSED CANDLES ONLY | NO LOOK-AHEAD | REAL ORDERS DISABLED",
        (
            f"Acquisition: {len(acquisition.completed_symbols)}/{len(acquisition.expected_symbols)} symbols | "
            f"failures={len(acquisition.failures)}"
        ),
    ]
    if output.pipeline.validation is not None:
        validation = output.pipeline.validation
        lines.append(
            f"Preflight: {'READY' if validation.ready else 'BLOCKED'} | "
            f"ranked={len(validation.ranked_symbols)} | deep={len(validation.deep_analysis_symbols)}"
        )
        if validation.blockers:
            lines.append("Blockers: " + "; ".join(validation.blockers))
        for item in validation.symbols:
            score = "n/a" if item.scan is None else f"{item.scan.score:.1f}"
            classification = "n/a" if item.scan is None else item.scan.classification
            action = item.decision.action if item.decision is not None else item.status
            lines.append(
                f"  {item.rank or '-':>2} {item.symbol} | score={score} | "
                f"class={classification} | action={action}"
            )
    if output.report is not None:
        report = output.report
        lines.append(
            f"Paper cycle: processed={report.processed_symbols} | skipped={report.skipped_symbols} | "
            f"checkpoint={'YES' if report.checkpoint_saved else 'NO'}"
        )
        lines.append(
            f"Portfolio: equity={report.equity:.2f} | exposure={report.exposure_pct:.2f}% | "
            f"open={report.open_positions} | trades={report.total_trades}"
        )
        if report.errors:
            lines.append("Cycle errors: " + "; ".join(report.errors))
    return "\n".join(lines)


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Binance MCP paper host harness ready; live-safe constructor enables exact closed-candle validation.")
