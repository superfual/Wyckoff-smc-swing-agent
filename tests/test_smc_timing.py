"""Regression tests for SMC pivot/pool confirmation timing."""

from src.market_data import Candle
from src.smc import detect_liquidity_pools, detect_liquidity_sweeps, detect_structure_events, detect_swings


def candle(index: int, high: float, low: float, close: float) -> Candle:
    return Candle(
        timestamp=index * 3_600_000,
        open=close,
        high=high,
        low=low,
        close=close,
        volume=1_000.0,
    )


def test_swing_records_when_pivot_becomes_confirmed() -> None:
    candles = [
        candle(0, 100, 98, 99),
        candle(1, 105, 99, 104),
        candle(2, 103, 97, 100),
        candle(3, 102, 96, 99),
    ]
    swing = next(s for s in detect_swings(candles, left=1, right=2) if s.kind == "HIGH")
    assert swing.index == 1
    assert swing.confirmed_index == 3


def test_structure_break_cannot_use_unconfirmed_swing() -> None:
    candles = [
        candle(0, 100, 98, 99),
        candle(1, 105, 99, 104),
        candle(2, 106, 97, 106),  # would look like a break, but pivot 1 is not confirmed yet
        candle(3, 103, 96, 100),
        candle(4, 104, 95, 99),
        candle(5, 107, 98, 107),  # break after pivot confirmation
    ]
    swings = detect_swings(candles, left=1, right=2)
    events = detect_structure_events(candles, swings)
    assert not any(e.index == 2 and e.direction == "BULLISH" for e in events)


def test_liquidity_pool_confirmation_uses_latest_touch_confirmation() -> None:
    candles = [
        candle(0, 100, 98, 99),
        candle(1, 105.00, 99, 104),
        candle(2, 102, 97, 100),
        candle(3, 105.05, 99, 104),
        candle(4, 102, 97, 100),
        candle(5, 101, 96, 99),
    ]
    swings = detect_swings(candles, left=1, right=2)
    pool = next(p for p in detect_liquidity_pools(swings, tolerance_pct=0.25) if p.side == "BUY_SIDE")
    assert pool.last_index == 3
    assert pool.confirmed_index == 5


def test_liquidity_sweep_cannot_exist_before_pool_confirmation() -> None:
    candles = [
        candle(0, 100, 98, 99),
        candle(1, 105.00, 99, 104),
        candle(2, 102, 97, 100),
        candle(3, 105.05, 99, 104),
        candle(4, 106.0, 98, 104.5),  # apparent reclaim sweep before second pivot confirms
        candle(5, 103, 96, 100),      # second equal-high pivot becomes confirmed here
        candle(6, 106.2, 98, 104.5),  # valid post-confirmation sweep
    ]
    swings = detect_swings(candles, left=1, right=2)
    pools = detect_liquidity_pools(swings, tolerance_pct=0.25)
    sweeps = detect_liquidity_sweeps(candles, pools)
    buy_sweeps = [s for s in sweeps if s.side == "BUY_SIDE"]
    assert buy_sweeps
    assert all(s.index > s.pool_confirmed_index for s in buy_sweeps)
    assert not any(s.index == 4 for s in buy_sweeps)
