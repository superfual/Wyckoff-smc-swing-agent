"""
Bar-by-Bar Replay Engine
Wyckoff + SMC Spot Swing Agent

Replays normalized historical candles without future leakage. Each decision is
made only after the reference bar has closed, and higher/lower timeframe
snapshots include only candles whose own close time is already known.

Replay V1 records the agent decision timeline and action counts. It does not
simulate fills, fees, slippage or PnL yet; those belong to a later backtest
portfolio layer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .execution import ExecutionConfig
    from .market_data import Candle, MarketData
    from .orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from .risk import RiskConfig
except ImportError:  # Allows: python src/replay.py
    from execution import ExecutionConfig
    from market_data import Candle, MarketData
    from orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from risk import RiskConfig


ReplayTimeframe = Literal["1d", "4h", "1h", "15m"]

_TIMEFRAME_MS: dict[str, int] = {
    "1d": 86_400_000,
    "4h": 14_400_000,
    "1h": 3_600_000,
    "15m": 900_000,
}

_TIMEFRAME_FIELD: dict[str, str] = {
    "1d": "daily",
    "4h": "four_hour",
    "1h": "one_hour",
    "15m": "fifteen_minute",
}


@dataclass(frozen=True)
class ReplayConfig:
    reference_timeframe: ReplayTimeframe = "1h"
    warmup_bars: int = 40
    # Optional historical cutoff. Reference candles closing after this instant
    # are excluded even when the caller passes a raw Binance snapshot that also
    # contains the currently forming candle.
    as_of_time: int | None = None


@dataclass
class ReplayStep:
    bar_index: int
    bar_timestamp: int
    decision_time: int
    current_price: float
    action: str
    decision: AgentDecision
    snapshot_candle_counts: dict[str, int] | None = None
    latest_closed_times: dict[str, int | None] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ReplayResult:
    symbol: str
    reference_timeframe: str
    steps: list[ReplayStep]
    action_counts: dict[str, int]
    first_decision_time: int | None
    last_decision_time: int | None
    errors: list[str]
    as_of_time: int | None = None
    excluded_reference_bars: int = 0
    no_lookahead_verified: bool = False
    audit_errors: list[str] | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _timeframe_candles(market: MarketData, timeframe: str) -> list[Candle]:
    if timeframe not in _TIMEFRAME_FIELD:
        raise ValueError(f"Unsupported replay timeframe: {timeframe}")
    return getattr(market, _TIMEFRAME_FIELD[timeframe])


def _closed_by(candles: list[Candle], timeframe: str, decision_time: int) -> list[Candle]:
    duration = _TIMEFRAME_MS[timeframe]
    return [candle for candle in candles if candle.timestamp + duration <= decision_time]


def _chronology_errors(market: MarketData) -> list[str]:
    errors: list[str] = []
    for timeframe, field in _TIMEFRAME_FIELD.items():
        timestamps = [candle.timestamp for candle in getattr(market, field)]
        if any(timestamp < 0 for timestamp in timestamps):
            errors.append(f"NEGATIVE_CANDLE_TIMESTAMP:{timeframe}")
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            errors.append(f"NON_MONOTONIC_CANDLES:{timeframe}")
    return errors


def _snapshot_audit(snapshot: MarketData, decision_time: int) -> tuple[dict[str, int], dict[str, int | None], list[str]]:
    counts: dict[str, int] = {}
    latest_closes: dict[str, int | None] = {}
    violations: list[str] = []
    for timeframe, field in _TIMEFRAME_FIELD.items():
        candles = getattr(snapshot, field)
        duration = _TIMEFRAME_MS[timeframe]
        counts[timeframe] = len(candles)
        latest_closes[timeframe] = candles[-1].timestamp + duration if candles else None
        if any(candle.timestamp + duration > decision_time for candle in candles):
            violations.append(f"FUTURE_CANDLE_LEAK:{timeframe}:{decision_time}")
    return counts, latest_closes, violations


def slice_market_at_decision_time(
    market: MarketData,
    decision_time: int,
    *,
    reference_timeframe: ReplayTimeframe = "1h",
) -> MarketData:
    """Return a historical snapshot containing only fully closed candles."""

    if decision_time < 0:
        raise ValueError("decision_time must be >= 0")
    if reference_timeframe not in _TIMEFRAME_MS:
        raise ValueError(f"Unsupported replay timeframe: {reference_timeframe}")

    daily = _closed_by(market.daily, "1d", decision_time)
    four_hour = _closed_by(market.four_hour, "4h", decision_time)
    one_hour = _closed_by(market.one_hour, "1h", decision_time)
    fifteen_minute = _closed_by(market.fifteen_minute, "15m", decision_time)

    reference = {
        "1d": daily,
        "4h": four_hour,
        "1h": one_hour,
        "15m": fifteen_minute,
    }[reference_timeframe]
    current_price = reference[-1].close if reference else None

    return MarketData(
        symbol=market.symbol,
        current_price=current_price,
        daily=daily,
        four_hour=four_hour,
        one_hour=one_hour,
        fifteen_minute=fifteen_minute,
    )


def run_replay(
    market: MarketData,
    *,
    account_equity: float,
    current_portfolio_exposure_pct: float = 0.0,
    config: ReplayConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
) -> ReplayResult:
    """Replay one symbol bar-by-bar through the full agent orchestrator."""

    cfg = config or ReplayConfig()
    errors: list[str] = []
    if cfg.reference_timeframe not in _TIMEFRAME_MS:
        errors.append("INVALID_REFERENCE_TIMEFRAME")
    if cfg.warmup_bars < 1:
        errors.append("INVALID_WARMUP_BARS")
    if cfg.as_of_time is not None and cfg.as_of_time < 0:
        errors.append("INVALID_AS_OF_TIME")
    if account_equity <= 0:
        errors.append("INVALID_ACCOUNT_EQUITY")
    errors.extend(_chronology_errors(market))

    if errors:
        return ReplayResult(
            market.symbol, cfg.reference_timeframe, [], {}, None, None, errors,
            as_of_time=cfg.as_of_time, audit_errors=list(errors),
        )

    reference = _timeframe_candles(market, cfg.reference_timeframe)
    duration = _TIMEFRAME_MS[cfg.reference_timeframe]
    eligible = [
        (index, candle) for index, candle in enumerate(reference)
        if cfg.as_of_time is None or candle.timestamp + duration <= cfg.as_of_time
    ]
    excluded_reference_bars = len(reference) - len(eligible)
    if len(eligible) < cfg.warmup_bars:
        return ReplayResult(
            market.symbol,
            cfg.reference_timeframe,
            [],
            {},
            None,
            None,
            ["INSUFFICIENT_REPLAY_BARS"],
            as_of_time=cfg.as_of_time,
            excluded_reference_bars=excluded_reference_bars,
            audit_errors=["INSUFFICIENT_REPLAY_BARS"],
        )

    steps: list[ReplayStep] = []
    action_counts: dict[str, int] = {}
    audit_errors: list[str] = []

    for eligible_index in range(cfg.warmup_bars - 1, len(eligible)):
        bar_index, bar = eligible[eligible_index]
        decision_time = bar.timestamp + duration
        snapshot = slice_market_at_decision_time(
            market,
            decision_time,
            reference_timeframe=cfg.reference_timeframe,
        )
        counts, latest_closes, violations = _snapshot_audit(snapshot, decision_time)
        audit_errors.extend(violations)
        if snapshot.current_price != bar.close:
            audit_errors.append(f"REFERENCE_PRICE_MISMATCH:{bar_index}")
        decision = analyze_symbol(
            snapshot,
            account_equity=account_equity,
            current_portfolio_exposure_pct=current_portfolio_exposure_pct,
            config=agent_config,
            risk_config=risk_config,
            execution_config=execution_config,
        )
        action_counts[decision.action] = action_counts.get(decision.action, 0) + 1
        steps.append(ReplayStep(
            bar_index=bar_index,
            bar_timestamp=bar.timestamp,
            decision_time=decision_time,
            current_price=bar.close,
            action=decision.action,
            decision=decision,
            snapshot_candle_counts=counts,
            latest_closed_times=latest_closes,
        ))

    return ReplayResult(
        symbol=market.symbol,
        reference_timeframe=cfg.reference_timeframe,
        steps=steps,
        action_counts=action_counts,
        first_decision_time=steps[0].decision_time if steps else None,
        last_decision_time=steps[-1].decision_time if steps else None,
        errors=list(dict.fromkeys(audit_errors)),
        as_of_time=cfg.as_of_time,
        excluded_reference_bars=excluded_reference_bars,
        no_lookahead_verified=not audit_errors,
        audit_errors=list(dict.fromkeys(audit_errors)),
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Bar-by-bar replay engine ready; PnL simulation is not enabled in V1.")
