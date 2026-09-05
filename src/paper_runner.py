"""
Closed-Candle Paper Trading Runner
Wyckoff + SMC Spot Swing Agent

Consumes normalized MarketData snapshots supplied by an external market-data
adapter, strips candles that are not closed at decision time, and feeds the
result into the shared PaperSession with portfolio-level entry safety guards.

V1.1 adds same-cycle fairness for fresh Spot entries: active positions/pending
orders are serviced first, then all fresh symbols are pre-analyzed against the
same portfolio baseline and ranked by setup quality before portfolio slots are
allocated. This removes watchlist/input ordering as the primary allocator.

This module performs no network requests, stores no credentials and sends no
exchange orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

try:
    from .execution import ExecutionConfig
    from .market_data import Candle, MarketData
    from .orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from .paper_session import PaperSession, process_session_snapshot
    from .paper_trading import PaperStepResult, PaperTradingConfig
    from .portfolio_safety import PortfolioSafetyConfig
    from .risk import RiskConfig
except ImportError:
    from execution import ExecutionConfig
    from market_data import Candle, MarketData
    from orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from paper_session import PaperSession, process_session_snapshot
    from paper_trading import PaperStepResult, PaperTradingConfig
    from portfolio_safety import PortfolioSafetyConfig
    from risk import RiskConfig

RunnerTimeframe = Literal["1d", "4h", "1h", "15m"]

_TIMEFRAME_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000, "15m": 900_000}
_TIMEFRAME_FIELD = {"1d": "daily", "4h": "four_hour", "1h": "one_hour", "15m": "fifteen_minute"}


@dataclass(frozen=True)
class PaperRunnerConfig:
    reference_timeframe: RunnerTimeframe = "1h"
    require_reference_candle: bool = True
    require_exact_reference_close: bool = False
    continue_on_symbol_error: bool = True
    fair_same_cycle_allocation: bool = True


@dataclass
class RunnerSymbolResult:
    symbol: str
    processed: bool
    step: PaperStepResult | None
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RunnerCycleResult:
    decision_time: int
    processed_symbols: int
    skipped_symbols: int
    symbol_results: list[RunnerSymbolResult]
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PaperRunnerState:
    last_cycle_time: int | None = None
    cycles: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _closed_candles(candles: list[Candle], timeframe: str, decision_time: int) -> list[Candle]:
    duration = _TIMEFRAME_MS[timeframe]
    return [candle for candle in candles if candle.timestamp + duration <= decision_time]


def build_closed_snapshot(market: MarketData, *, decision_time: int, reference_timeframe: RunnerTimeframe = "1h") -> MarketData:
    if reference_timeframe not in _TIMEFRAME_FIELD:
        raise ValueError(f"Unsupported runner timeframe: {reference_timeframe}")
    if decision_time < 0:
        raise ValueError("decision_time must be >= 0")

    daily = _closed_candles(market.daily, "1d", decision_time)
    four_hour = _closed_candles(market.four_hour, "4h", decision_time)
    one_hour = _closed_candles(market.one_hour, "1h", decision_time)
    fifteen_minute = _closed_candles(market.fifteen_minute, "15m", decision_time)
    by_field = {"daily": daily, "four_hour": four_hour, "one_hour": one_hour, "fifteen_minute": fifteen_minute}
    reference = by_field[_TIMEFRAME_FIELD[reference_timeframe]]
    current_price = reference[-1].close if reference else None
    return MarketData(market.symbol, current_price, daily, four_hour, one_hour, fifteen_minute)


def _reference_close_time(market: MarketData, timeframe: str) -> int | None:
    field = _TIMEFRAME_FIELD[timeframe]
    candles = getattr(market, field)
    if not candles:
        return None
    return candles[-1].timestamp + _TIMEFRAME_MS[timeframe]


def _portfolio_exposure_pct(session: PaperSession) -> float:
    if session.equity <= 0:
        return 0.0
    quote = sum(
        account.open_position.position_size_quote
        for account in session.accounts.values()
        if account.open_position is not None
    )
    return quote / session.equity * 100


def _has_active_lifecycle(session: PaperSession, symbol: str) -> bool:
    account = session.accounts.get(symbol)
    return bool(account and (account.open_position is not None or account.pending_entry_price is not None))


def _pre_analyze_fresh(
    session: PaperSession,
    market: MarketData,
    *,
    agent_config: AgentConfig | None,
    risk_config: RiskConfig | None,
    execution_config: ExecutionConfig | None,
) -> AgentDecision:
    account = session.accounts.get(market.symbol)
    cooldown_active = bool(account and account.cooldown_bars_remaining > 0)
    return analyze_symbol(
        market,
        account_equity=session.equity,
        current_portfolio_exposure_pct=_portfolio_exposure_pct(session),
        has_open_position=False,
        cooldown_active=cooldown_active,
        config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
    )


def _candidate_rank(decision: AgentDecision) -> tuple[float, float, float, str]:
    """Higher quality first; symbol is a deterministic tie-break, not a preference."""
    executable = 1.0 if decision.action == "ENTER_LONG" else 0.0
    confluence = float(decision.confluence.confidence) if decision.confluence is not None else -1.0
    scanner = float(decision.scan.score) if decision.scan is not None else -1.0
    return (-executable, -confluence, -scanner, decision.symbol.upper())


def _fair_processing_order(
    session: PaperSession,
    closed_markets: list[MarketData],
    *,
    agent_config: AgentConfig | None,
    risk_config: RiskConfig | None,
    execution_config: ExecutionConfig | None,
) -> list[MarketData]:
    active: list[MarketData] = []
    fresh: list[tuple[tuple[float, float, float, str], MarketData]] = []
    for market in closed_markets:
        symbol = market.symbol.upper()
        if _has_active_lifecycle(session, symbol):
            active.append(market)
            continue
        decision = _pre_analyze_fresh(
            session,
            market,
            agent_config=agent_config,
            risk_config=risk_config,
            execution_config=execution_config,
        )
        fresh.append((_candidate_rank(decision), market))
    fresh.sort(key=lambda item: item[0])
    return active + [market for _, market in fresh]


def run_paper_cycle(
    state: PaperRunnerState,
    session: PaperSession,
    markets: list[MarketData],
    *,
    decision_time: int,
    config: PaperRunnerConfig | None = None,
    paper_config: PaperTradingConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
    portfolio_safety_config: PortfolioSafetyConfig | None = None,
) -> RunnerCycleResult:
    cfg = config or PaperRunnerConfig()
    errors: list[str] = []

    if cfg.reference_timeframe not in _TIMEFRAME_FIELD:
        errors.append("INVALID_REFERENCE_TIMEFRAME")
    if decision_time < 0:
        errors.append("INVALID_DECISION_TIME")
    if state.last_cycle_time is not None and decision_time <= state.last_cycle_time:
        errors.append("NON_MONOTONIC_CYCLE_TIME")
    if errors:
        state.errors.extend(errors)
        return RunnerCycleResult(decision_time, 0, len(markets), [], errors)

    if paper_config is None:
        paper_cfg = PaperTradingConfig(reference_timeframe=cfg.reference_timeframe)
    else:
        paper_cfg = paper_config
        if paper_cfg.reference_timeframe != cfg.reference_timeframe:
            errors.append("RUNNER_PAPER_TIMEFRAME_MISMATCH")
            state.errors.extend(errors)
            return RunnerCycleResult(decision_time, 0, len(markets), [], errors)

    results: list[RunnerSymbolResult] = []
    processed = 0
    skipped = 0
    seen: set[str] = set()
    valid_closed: list[MarketData] = []

    # Validation/closed-candle construction is intentionally input-order neutral.
    for market in markets:
        symbol = market.symbol.upper()
        symbol_errors: list[str] = []
        if symbol in seen:
            symbol_errors.append("DUPLICATE_SYMBOL_IN_CYCLE")
        seen.add(symbol)

        closed = None
        if not symbol_errors:
            closed = build_closed_snapshot(market, decision_time=decision_time, reference_timeframe=cfg.reference_timeframe)
            close_time = _reference_close_time(closed, cfg.reference_timeframe)
            if cfg.require_reference_candle and close_time is None:
                symbol_errors.append("REFERENCE_CANDLE_UNAVAILABLE")
            if cfg.require_exact_reference_close and close_time is not None and close_time != decision_time:
                symbol_errors.append("REFERENCE_CANDLE_NOT_FRESH")

        if symbol_errors:
            skipped += 1
            results.append(RunnerSymbolResult(symbol, False, None, symbol_errors))
            state.errors.extend(f"{symbol}:{error}" for error in symbol_errors)
            if not cfg.continue_on_symbol_error:
                state.last_cycle_time = decision_time
                state.cycles += 1
                return RunnerCycleResult(decision_time, processed, skipped, results, errors)
            continue
        assert closed is not None
        valid_closed.append(closed)

    processing_order = valid_closed
    if cfg.fair_same_cycle_allocation and len(valid_closed) > 1:
        processing_order = _fair_processing_order(
            session,
            valid_closed,
            agent_config=agent_config,
            risk_config=risk_config,
            execution_config=execution_config,
        )

    for closed in processing_order:
        symbol = closed.symbol.upper()
        step = process_session_snapshot(
            session,
            closed,
            timestamp=decision_time,
            paper_config=paper_cfg,
            agent_config=agent_config,
            risk_config=risk_config,
            execution_config=execution_config,
            portfolio_safety_config=portfolio_safety_config,
        )
        if step.errors:
            skipped += 1
            results.append(RunnerSymbolResult(symbol, False, step, list(step.errors)))
            state.errors.extend(f"{symbol}:{error}" for error in step.errors)
            if not cfg.continue_on_symbol_error:
                break
            continue
        processed += 1
        results.append(RunnerSymbolResult(symbol, True, step, []))

    state.last_cycle_time = decision_time
    state.cycles += 1
    return RunnerCycleResult(decision_time, processed, skipped, results, errors)


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Closed-candle paper runner ready; fair same-cycle allocation enabled.")
