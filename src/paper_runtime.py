"""
Paper Runtime / Market Data Provider Boundary
Wyckoff + SMC Spot Swing Agent

Coordinates an external normalized market-data provider with the closed-candle
paper runner and versioned checkpoint persistence. The runtime is intentionally
provider-agnostic: Binance Agent OS / MCP integration belongs in an adapter that
implements MarketDataProvider.

This module performs no exchange authentication and sends no orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Protocol, Sequence

try:
    from .execution import ExecutionConfig
    from .market_data import MarketData
    from .orchestrator import AgentConfig
    from .paper_runner import PaperRunnerConfig, PaperRunnerState, RunnerCycleResult, run_paper_cycle
    from .paper_session import PaperSession, PaperSessionConfig, create_paper_session
    from .paper_trading import PaperTradingConfig
    from .persistence import RecoveryResult, load_checkpoint, save_checkpoint
    from .risk import RiskConfig
    from .scanner import WatchlistSymbol, load_watchlist
except ImportError:
    from execution import ExecutionConfig
    from market_data import MarketData
    from orchestrator import AgentConfig
    from paper_runner import PaperRunnerConfig, PaperRunnerState, RunnerCycleResult, run_paper_cycle
    from paper_session import PaperSession, PaperSessionConfig, create_paper_session
    from paper_trading import PaperTradingConfig
    from persistence import RecoveryResult, load_checkpoint, save_checkpoint
    from risk import RiskConfig
    from scanner import WatchlistSymbol, load_watchlist


class MarketDataProvider(Protocol):
    """Adapter contract: return normalized snapshots for requested symbols."""

    def fetch_markets(self, symbols: Sequence[str], *, decision_time: int) -> list[MarketData]:
        ...


@dataclass(frozen=True)
class PaperRuntimeConfig:
    checkpoint_path: str = "state/paper_runtime.json"
    auto_recover: bool = True
    checkpoint_after_cycle: bool = True
    require_all_symbols: bool = False


@dataclass
class PaperRuntime:
    session: PaperSession
    runner_state: PaperRunnerState
    symbols: tuple[str, ...]
    checkpoint_path: str
    recovered: bool = False
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuntimeCycleResult:
    decision_time: int
    provider_symbols: list[str]
    missing_symbols: list[str]
    cycle: RunnerCycleResult | None
    checkpoint_saved: bool
    errors: list[str]

    @property
    def processed(self) -> bool:
        return self.cycle is not None and not self.errors

    def to_dict(self) -> dict:
        return asdict(self)


def _normalize_symbols(symbols: Sequence[str | WatchlistSymbol]) -> tuple[str, ...]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in symbols:
        raw = item.symbol if isinstance(item, WatchlistSymbol) else item
        symbol = str(raw).upper().strip()
        if symbol and symbol not in seen:
            normalized.append(symbol)
            seen.add(symbol)
    if not normalized:
        raise ValueError("Runtime requires at least one symbol")
    return tuple(normalized)


def create_paper_runtime(
    *,
    symbols: Sequence[str | WatchlistSymbol] | None = None,
    runtime_config: PaperRuntimeConfig | None = None,
    session_config: PaperSessionConfig | None = None,
) -> PaperRuntime:
    """Create a fresh runtime or recover the latest valid checkpoint."""
    cfg = runtime_config or PaperRuntimeConfig()
    runtime_symbols = _normalize_symbols(symbols if symbols is not None else load_watchlist())

    if cfg.auto_recover:
        recovery = load_checkpoint(cfg.checkpoint_path)
        if recovery.recovered:
            assert recovery.session is not None and recovery.runner_state is not None
            return PaperRuntime(
                session=recovery.session,
                runner_state=recovery.runner_state,
                symbols=runtime_symbols,
                checkpoint_path=cfg.checkpoint_path,
                recovered=True,
                errors=[],
            )
        # Missing checkpoint is a normal first-start condition. Other recovery
        # failures are fail-closed because silently resetting could duplicate risk.
        if recovery.errors != ["CHECKPOINT_NOT_FOUND"]:
            return PaperRuntime(
                session=create_paper_session(session_config),
                runner_state=PaperRunnerState(),
                symbols=runtime_symbols,
                checkpoint_path=cfg.checkpoint_path,
                recovered=False,
                errors=[f"RECOVERY_FAILED:{error}" for error in recovery.errors],
            )

    return PaperRuntime(
        session=create_paper_session(session_config),
        runner_state=PaperRunnerState(),
        symbols=runtime_symbols,
        checkpoint_path=cfg.checkpoint_path,
    )


def run_runtime_cycle(
    runtime: PaperRuntime,
    provider: MarketDataProvider,
    *,
    decision_time: int,
    runtime_config: PaperRuntimeConfig | None = None,
    runner_config: PaperRunnerConfig | None = None,
    paper_config: PaperTradingConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
) -> RuntimeCycleResult:
    """Fetch one normalized batch, run one paper cycle, then checkpoint it."""
    cfg = runtime_config or PaperRuntimeConfig(checkpoint_path=runtime.checkpoint_path)
    errors: list[str] = []

    if runtime.errors:
        errors.extend(runtime.errors)
        return RuntimeCycleResult(decision_time, [], list(runtime.symbols), None, False, errors)
    if decision_time < 0:
        return RuntimeCycleResult(decision_time, [], list(runtime.symbols), None, False, ["INVALID_DECISION_TIME"])

    try:
        markets = provider.fetch_markets(runtime.symbols, decision_time=decision_time)
    except Exception as exc:  # Adapter failures must not mutate runner/session state.
        error = f"MARKET_DATA_PROVIDER_ERROR:{type(exc).__name__}"
        runtime.errors.append(error)
        return RuntimeCycleResult(decision_time, [], list(runtime.symbols), None, False, [error])

    if not isinstance(markets, list) or any(not isinstance(item, MarketData) for item in markets):
        error = "INVALID_PROVIDER_RESULT"
        runtime.errors.append(error)
        return RuntimeCycleResult(decision_time, [], list(runtime.symbols), None, False, [error])

    provider_symbols = [market.symbol.upper() for market in markets]
    expected = set(runtime.symbols)
    unexpected = sorted(set(provider_symbols) - expected)
    missing = sorted(expected - set(provider_symbols))
    if unexpected:
        errors.append("UNEXPECTED_PROVIDER_SYMBOLS:" + ",".join(unexpected))
    if missing:
        errors.append("MISSING_PROVIDER_SYMBOLS:" + ",".join(missing))
    if unexpected or (missing and cfg.require_all_symbols):
        runtime.errors.extend(errors)
        return RuntimeCycleResult(decision_time, provider_symbols, missing, None, False, errors)

    cycle = run_paper_cycle(
        runtime.runner_state,
        runtime.session,
        markets,
        decision_time=decision_time,
        config=runner_config,
        paper_config=paper_config,
        agent_config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
    )

    checkpoint_saved = False
    if cycle.errors:
        errors.extend(cycle.errors)
    # Symbol-level runner errors do not invalidate a consumed cycle. Persist the
    # consumed timeline so restart cannot replay already evaluated symbols.
    if cfg.checkpoint_after_cycle and runtime.runner_state.last_cycle_time == decision_time:
        try:
            save_checkpoint(runtime.checkpoint_path, runtime.session, runtime.runner_state)
            checkpoint_saved = True
        except (OSError, TypeError, ValueError) as exc:
            error = f"CHECKPOINT_SAVE_FAILED:{type(exc).__name__}"
            runtime.errors.append(error)
            errors.append(error)

    return RuntimeCycleResult(
        decision_time=decision_time,
        provider_symbols=provider_symbols,
        missing_symbols=missing,
        cycle=cycle,
        checkpoint_saved=checkpoint_saved,
        errors=errors,
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Paper runtime boundary ready; external MarketDataProvider required.")
