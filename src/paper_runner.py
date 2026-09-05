"""
Closed-Candle Paper Trading Runner
Wyckoff + SMC Spot Swing Agent

Consumes normalized MarketData snapshots supplied by an external market-data
adapter (for example Binance Agent OS / MCP), strips any candles that are not
closed at the supplied decision time, and feeds the resulting snapshots into
the shared PaperSession.

This module performs no network requests, stores no credentials and sends no
exchange orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

try:
    from .execution import ExecutionConfig
    from .market_data import Candle, MarketData
    from .orchestrator import AgentConfig
    from .paper_session import PaperSession, process_session_snapshot
    from .paper_trading import PaperStepResult, PaperTradingConfig
    from .risk import RiskConfig
except ImportError:
    from execution import ExecutionConfig
    from market_data import Candle, MarketData
    from orchestrator import AgentConfig
    from paper_session import PaperSession, process_session_snapshot
    from paper_trading import PaperStepResult, PaperTradingConfig
    from risk import RiskConfig

RunnerTimeframe = Literal["1d", "4h", "1h", "15m"]

_TIMEFRAME_MS = {
    "1d": 86_400_000,
    "4h": 14_400_000,
    "1h": 3_600_000,
    "15m": 900_000,
}

_TIMEFRAME_FIELD = {
    "1d": "daily",
    "4h": "four_hour",
    "1h": "one_hour",
    "15m": "fifteen_minute",
}


@dataclass(frozen=True)
class PaperRunnerConfig:
    reference_timeframe: RunnerTimeframe = "1h"
    require_reference_candle: bool = True
    require_exact_reference_close: bool = False
    continue_on_symbol_error: bool = True


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
    """Remove partially formed/future candles and derive price from the last closed reference candle."""
    if reference_timeframe not in _TIMEFRAME_FIELD:
        raise ValueError(f"Unsupported runner timeframe: {reference_timeframe}")
    if decision_time < 0:
        raise ValueError("decision_time must be >= 0")

    daily = _closed_candles(market.daily, "1d", decision_time)
    four_hour = _closed_candles(market.four_hour, "4h", decision_time)
    one_hour = _closed_candles(market.one_hour, "1h", decision_time)
    fifteen_minute = _closed_candles(market.fifteen_minute, "15m", decision_time)

    by_field = {
        "daily": daily,
        "four_hour": four_hour,
        "one_hour": one_hour,
        "fifteen_minute": fifteen_minute,
    }
    reference = by_field[_TIMEFRAME_FIELD[reference_timeframe]]
    current_price = reference[-1].close if reference else None

    return MarketData(
        symbol=market.symbol,
        current_price=current_price,
        daily=daily,
        four_hour=four_hour,
        one_hour=one_hour,
        fifteen_minute=fifteen_minute,
    )


def _reference_close_time(market: MarketData, timeframe: str) -> int | None:
    field = _TIMEFRAME_FIELD[timeframe]
    candles = getattr(market, field)
    if not candles:
        return None
    return candles[-1].timestamp + _TIMEFRAME_MS[timeframe]


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
) -> RunnerCycleResult:
    """Process one decision-time cycle across a batch of normalized market snapshots."""
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

    # Keep paper outcome timeframe aligned with runner semantics unless caller explicitly
    # supplies another valid paper config.
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
    for market in markets:
        symbol = market.symbol.upper()
        symbol_errors: list[str] = []
        if symbol in seen:
            symbol_errors.append("DUPLICATE_SYMBOL_IN_CYCLE")
        seen.add(symbol)

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

        step = process_session_snapshot(
            session,
            closed,
            timestamp=decision_time,
            paper_config=paper_cfg,
            agent_config=agent_config,
            risk_config=risk_config,
            execution_config=execution_config,
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

    # A cycle is considered consumed once its batch has been evaluated. This prevents
    # retries from duplicating decisions/trades; failed symbols can be inspected via errors.
    state.last_cycle_time = decision_time
    state.cycles += 1
    return RunnerCycleResult(decision_time, processed, skipped, results, errors)


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Closed-candle paper runner ready; external data adapter required.")
