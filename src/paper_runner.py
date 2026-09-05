"""
Closed-Candle Paper Trading Runner
Wyckoff + SMC Spot Swing Agent

Consumes normalized MarketData snapshots supplied by an external market-data
adapter, strips candles that are not closed at decision time, and feeds the
result into the shared PaperSession with portfolio-level entry safety guards.

V2 builds an immutable same-cycle allocation plan for fresh Spot candidates and
supports idempotent same-time retries by processing only symbols that have not
already consumed the decision timestamp.

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
    from .portfolio_safety import CORRELATION_GROUPS, PortfolioSafetyConfig
    from .risk import RiskConfig
except ImportError:
    from execution import ExecutionConfig
    from market_data import Candle, MarketData
    from orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from paper_session import PaperSession, process_session_snapshot
    from paper_trading import PaperStepResult, PaperTradingConfig
    from portfolio_safety import CORRELATION_GROUPS, PortfolioSafetyConfig
    from risk import RiskConfig

RunnerTimeframe = Literal["1d", "4h", "1h", "15m"]
AllocationStatus = Literal["SELECTED", "NOT_SELECTED", "LIFECYCLE", "ALREADY_PROCESSED"]

_TIMEFRAME_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000, "15m": 900_000}
_TIMEFRAME_FIELD = {"1d": "daily", "4h": "four_hour", "1h": "one_hour", "15m": "fifteen_minute"}


@dataclass(frozen=True)
class PaperRunnerConfig:
    reference_timeframe: RunnerTimeframe = "1h"
    require_reference_candle: bool = True
    require_exact_reference_close: bool = False
    continue_on_symbol_error: bool = True
    fair_same_cycle_allocation: bool = True


@dataclass(frozen=True)
class AllocationDecision:
    symbol: str
    status: AllocationStatus
    rank: int | None
    reason: str
    confluence_confidence: float | None = None
    scanner_score: float | None = None


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
    allocation_plan: tuple[AllocationDecision, ...] = ()
    retry: bool = False

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
    candles = getattr(market, _TIMEFRAME_FIELD[timeframe])
    return candles[-1].timestamp + _TIMEFRAME_MS[timeframe] if candles else None


def _portfolio_exposure_pct(session: PaperSession) -> float:
    if session.equity <= 0:
        return 0.0
    quote = sum(a.open_position.position_size_quote for a in session.accounts.values() if a.open_position is not None)
    return quote / session.equity * 100


def _has_active_lifecycle(session: PaperSession, symbol: str) -> bool:
    account = session.accounts.get(symbol)
    return bool(account and (account.open_position is not None or account.pending_entry_price is not None))


def _pre_analyze_fresh(session: PaperSession, market: MarketData, *, agent_config: AgentConfig | None, risk_config: RiskConfig | None, execution_config: ExecutionConfig | None) -> AgentDecision:
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
    executable = 1.0 if decision.action == "ENTER_LONG" else 0.0
    confluence = float(decision.confluence.confidence) if decision.confluence is not None else -1.0
    scanner = float(decision.scan.score) if decision.scan is not None else -1.0
    return (-executable, -confluence, -scanner, decision.symbol.upper())


def _build_allocation_plan(session: PaperSession, closed_markets: list[MarketData], *, safety_config: PortfolioSafetyConfig | None, agent_config: AgentConfig | None, risk_config: RiskConfig | None, execution_config: ExecutionConfig | None, decision_time: int) -> tuple[AllocationDecision, ...]:
    cfg = safety_config or PortfolioSafetyConfig()
    open_symbols = [symbol for symbol, account in session.accounts.items() if account.open_position is not None]
    reserved_symbols = list(open_symbols)
    remaining_slots = max(cfg.max_concurrent_positions - len(open_symbols), 0)
    ranked: list[tuple[tuple[float, float, float, str], MarketData, AgentDecision]] = []
    plan: list[AllocationDecision] = []

    for market in closed_markets:
        symbol = market.symbol.upper()
        account = session.accounts.get(symbol)
        if account and account.last_processed_timestamp is not None and account.last_processed_timestamp >= decision_time:
            plan.append(AllocationDecision(symbol, "ALREADY_PROCESSED", None, "ALREADY_PROCESSED_TIMESTAMP"))
        elif _has_active_lifecycle(session, symbol):
            plan.append(AllocationDecision(symbol, "LIFECYCLE", None, "EXISTING_POSITION_OR_PENDING_ORDER"))
        else:
            decision = _pre_analyze_fresh(session, market, agent_config=agent_config, risk_config=risk_config, execution_config=execution_config)
            ranked.append((_candidate_rank(decision), market, decision))

    ranked.sort(key=lambda item: item[0])
    candidate_rank = 0
    for _, market, decision in ranked:
        symbol = market.symbol.upper()
        confluence = float(decision.confluence.confidence) if decision.confluence is not None else None
        scanner = float(decision.scan.score) if decision.scan is not None else None
        if decision.action != "ENTER_LONG":
            plan.append(AllocationDecision(symbol, "NOT_SELECTED", None, "NOT_EXECUTABLE_BUY_CANDIDATE", confluence, scanner))
            continue
        candidate_rank += 1
        if remaining_slots <= 0:
            plan.append(AllocationDecision(symbol, "NOT_SELECTED", candidate_rank, "PORTFOLIO_SLOT_EXHAUSTED", confluence, scanner))
            continue
        group = CORRELATION_GROUPS.get(symbol)
        if group:
            group_count = sum(CORRELATION_GROUPS.get(existing.upper()) == group for existing in reserved_symbols)
            if group_count >= cfg.max_positions_per_correlation_group:
                plan.append(AllocationDecision(symbol, "NOT_SELECTED", candidate_rank, f"CORRELATION_SLOT_EXHAUSTED:{group}", confluence, scanner))
                continue
        plan.append(AllocationDecision(symbol, "SELECTED", candidate_rank, "SELECTED_BY_SAME_CYCLE_RANK", confluence, scanner))
        reserved_symbols.append(symbol)
        remaining_slots -= 1

    return tuple(sorted(plan, key=lambda item: (0 if item.status == "LIFECYCLE" else 1 if item.status == "SELECTED" else 2, item.rank or 9999, item.symbol)))


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
    retry = state.last_cycle_time == decision_time

    if cfg.reference_timeframe not in _TIMEFRAME_FIELD:
        errors.append("INVALID_REFERENCE_TIMEFRAME")
    if decision_time < 0:
        errors.append("INVALID_DECISION_TIME")
    if state.last_cycle_time is not None and decision_time < state.last_cycle_time:
        errors.append("NON_MONOTONIC_CYCLE_TIME")
    if errors:
        state.errors.extend(errors)
        return RunnerCycleResult(decision_time, 0, len(markets), [], errors, (), retry)

    if paper_config is None:
        paper_cfg = PaperTradingConfig(reference_timeframe=cfg.reference_timeframe)
    else:
        paper_cfg = paper_config
        if paper_cfg.reference_timeframe != cfg.reference_timeframe:
            errors.append("RUNNER_PAPER_TIMEFRAME_MISMATCH")
            state.errors.extend(errors)
            return RunnerCycleResult(decision_time, 0, len(markets), [], errors, (), retry)

    results: list[RunnerSymbolResult] = []
    processed = 0
    skipped = 0
    seen: set[str] = set()
    valid_closed: list[MarketData] = []

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
                break
            continue
        assert closed is not None
        valid_closed.append(closed)

    allocation_plan = _build_allocation_plan(
        session,
        valid_closed,
        safety_config=portfolio_safety_config,
        agent_config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
        decision_time=decision_time,
    ) if cfg.fair_same_cycle_allocation else ()
    by_symbol = {item.symbol: item for item in allocation_plan}

    if cfg.fair_same_cycle_allocation:
        order_index = {item.symbol: i for i, item in enumerate(allocation_plan)}
        processing_order = sorted(valid_closed, key=lambda market: order_index.get(market.symbol.upper(), 9999))
    else:
        processing_order = valid_closed

    for closed in processing_order:
        symbol = closed.symbol.upper()
        account = session.accounts.get(symbol)
        if account and account.last_processed_timestamp is not None and account.last_processed_timestamp >= decision_time:
            results.append(RunnerSymbolResult(symbol, False, None, []))
            continue
        allocation = by_symbol.get(symbol)
        allocation_blockers: tuple[str, ...] = ()
        if allocation and allocation.status == "NOT_SELECTED" and allocation.reason in {"PORTFOLIO_SLOT_EXHAUSTED"} or (allocation and allocation.status == "NOT_SELECTED" and allocation.reason.startswith("CORRELATION_SLOT_EXHAUSTED:")):
            allocation_blockers = (allocation.reason,)

        step = process_session_snapshot(
            session,
            closed,
            timestamp=decision_time,
            paper_config=paper_cfg,
            agent_config=agent_config,
            risk_config=risk_config,
            execution_config=execution_config,
            portfolio_safety_config=portfolio_safety_config,
            allocation_blockers=allocation_blockers,
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

    if not retry:
        state.cycles += 1
    state.last_cycle_time = decision_time
    return RunnerCycleResult(decision_time, processed, skipped, results, errors, allocation_plan, retry)


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Closed-candle paper runner V2 ready; immutable allocation plans enabled.")
