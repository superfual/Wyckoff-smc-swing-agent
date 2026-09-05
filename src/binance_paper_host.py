"""
Binance MCP Paper Host Harness
Wyckoff + SMC Spot Swing Agent

Composes a read-only Binance MCP market-data stack with PaperRuntime. The host
also exposes a persistent portfolio kill switch and a non-mutating live-feed
preflight before paper portfolio state is allowed to advance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence

try:
    from .binance_adapter import BinanceAdapterConfig, BinanceMarketDataProvider
    from .binance_live_paper_validation import BinanceLivePaperPreflight, validate_binance_live_paper_feed
    from .binance_mcp_bridge import BinanceMCPBridgeConfig, BinanceMCPClientBridge
    from .paper_report import PaperCycleReport, build_paper_cycle_report
    from .paper_runtime import PaperRuntime, PaperRuntimeConfig, RuntimeCycleResult, create_paper_runtime, run_runtime_cycle
    from .paper_runner import PaperRunnerConfig
    from .paper_session import PaperSessionConfig
    from .paper_trading import PaperTradingConfig
    from .portfolio_safety import PortfolioSafetyConfig, set_kill_switch
    from .orchestrator import AgentConfig
    from .risk import RiskConfig
    from .execution import ExecutionConfig
except ImportError:
    from binance_adapter import BinanceAdapterConfig, BinanceMarketDataProvider
    from binance_live_paper_validation import BinanceLivePaperPreflight, validate_binance_live_paper_feed
    from binance_mcp_bridge import BinanceMCPBridgeConfig, BinanceMCPClientBridge
    from paper_report import PaperCycleReport, build_paper_cycle_report
    from paper_runtime import PaperRuntime, PaperRuntimeConfig, RuntimeCycleResult, create_paper_runtime, run_runtime_cycle
    from paper_runner import PaperRunnerConfig
    from paper_session import PaperSessionConfig
    from paper_trading import PaperTradingConfig
    from portfolio_safety import PortfolioSafetyConfig, set_kill_switch
    from orchestrator import AgentConfig
    from risk import RiskConfig
    from execution import ExecutionConfig

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


@dataclass
class BinancePaperHost:
    runtime: PaperRuntime
    provider: BinanceMarketDataProvider
    config: BinancePaperHostConfig


@dataclass(frozen=True)
class BinancePaperCycleOutput:
    result: RuntimeCycleResult
    report: PaperCycleReport


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


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Binance MCP paper host harness ready; preflight validates live feed before state mutation.")
