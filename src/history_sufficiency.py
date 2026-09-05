"""Closed-candle history sufficiency checks for the live paper pipeline.

This gate is intentionally tied to the requirements of the current V1 modules,
not to generic indicator folklore. It answers whether a normalized closed-candle
snapshot contains enough history for the scanner, Wyckoff engine and configured
SMC timeframe to run as intended.

It does not place orders and does not mutate portfolio state.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass

try:
    from .market_data import MarketData
except ImportError:
    from market_data import MarketData


_TIMEFRAME_FIELD = {
    "1d": "daily",
    "4h": "four_hour",
    "1h": "one_hour",
    "15m": "fifteen_minute",
}


@dataclass(frozen=True)
class HistoryRequirement:
    component: str
    timeframe: str
    required_closed_candles: int
    available_closed_candles: int
    passed: bool
    note: str


@dataclass(frozen=True)
class HistorySufficiency:
    symbol: str
    ready: bool
    requirements: tuple[HistoryRequirement, ...]
    blockers: tuple[str, ...]
    warnings: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _count(market: MarketData, timeframe: str) -> int:
    return len(getattr(market, _TIMEFRAME_FIELD[timeframe]))


def evaluate_history_sufficiency(
    market: MarketData,
    *,
    smc_timeframe: str = "1h",
) -> HistorySufficiency:
    if smc_timeframe not in _TIMEFRAME_FIELD:
        raise ValueError(f"Unsupported SMC timeframe: {smc_timeframe}")

    requirements: list[HistoryRequirement] = []

    def add(component: str, timeframe: str, required: int, note: str) -> None:
        available = _count(market, timeframe)
        requirements.append(
            HistoryRequirement(
                component=component,
                timeframe=timeframe,
                required_closed_candles=required,
                available_closed_candles=available,
                passed=available >= required,
                note=note,
            )
        )

    # Scanner V1 uses SMA20 and 20-bar 4H volume/compression/range windows.
    add("SCANNER", "1d", 20, "Daily SMA20 trend gate requires 20 closed candles.")
    add("SCANNER", "4h", 20, "4H trend/volume/compression/range scoring requires 20 closed candles.")

    # Wyckoff can technically detect a range from 16 bars, but its intended
    # recent auction window is 30 bars. Live validation requires the full window.
    add("WYCKOFF", "4h", 30, "Full intended Wyckoff trading-range lookback is 30 closed 4H candles.")

    # Default SMC swings use left=2/right=2, so five closed candles is the hard
    # structural minimum. Larger samples improve evidence density but are not a
    # correctness requirement of the current engine.
    add("SMC", smc_timeframe, 5, "Default confirmed swing primitive requires at least 5 closed candles.")

    # 15M is currently part of the normalized live feed contract even when the
    # default SMC engine runs on 1H. At least one closed candle keeps the feed
    # complete without pretending the strategy needs MA200 on 15M.
    add("LIVE_FEED", "15m", 1, "Normalized live feed requires a non-empty closed 15M series.")

    blockers = tuple(
        f"INSUFFICIENT_HISTORY:{item.component}:{item.timeframe}:{item.available_closed_candles}<{item.required_closed_candles}"
        for item in requirements
        if not item.passed
    )
    warnings: list[str] = []
    if _count(market, "1d") < 200:
        warnings.append("1D_MA200_UNAVAILABLE_NOT_REQUIRED_BY_V1")

    return HistorySufficiency(
        symbol=market.symbol.upper(),
        ready=not blockers,
        requirements=tuple(requirements),
        blockers=blockers,
        warnings=tuple(warnings),
    )


def render_history_sufficiency(result: HistorySufficiency) -> str:
    lines = [f"HISTORY SUFFICIENCY — {result.symbol}: {'PASS' if result.ready else 'BLOCKED'}"]
    for item in result.requirements:
        lines.append(
            f"  {'PASS' if item.passed else 'FAIL'} {item.component}/{item.timeframe}: "
            f"{item.available_closed_candles}/{item.required_closed_candles}"
        )
    if result.warnings:
        lines.append("Warnings: " + ", ".join(result.warnings))
    if result.blockers:
        lines.append("Blockers: " + ", ".join(result.blockers))
    return "\n".join(lines)
