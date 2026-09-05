"""Regression tests for SMC pivot/pool confirmation timing."""

from src.market_data import Candle
from src.smc import (
    LiquidityPool,
    SwingPoint,
    detect_liquidity_pools,
    detect_liquidity_sweeps,
    detect_structure_events,
    detect_swings,
)


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
    # Manual pivots isolate the timing rule: the high at index 1 is not usable
    # until index 3 even if price trades above its level earlier.
    swings = [
        SwingPoint("LOW", 0, 0, 98, 1, 0),
        SwingPoint("HIGH", 1, 3_600_000, 105, 1, 3),
        SwingPoint("LOW", 2, 7_200_000, 97, 1, 2),
    ]
    candles = [
        candle(0, 100, 98, 99),
        candle(1, 105, 99, 104),
        candle(2, 106, 97, 106),
        candle(3, 103, 96, 100),
        candle(4, 107, 98, 107),
    ]
    events = detect_structure_events(candles, swings)
    assert not any(e.index == 2 and e.direction == "BULLISH" for e in events)
    assert any(e.index == 4 and e.direction == "BULLISH" for e in events)


def test_liquidity_pool_confirmation_uses_latest_touch_confirmation() -> None:
    swings = [
        SwingPoint("HIGH", 1, 3_600_000, 105.00, 1, 3),
        SwingPoint("HIGH", 5, 18_000_000, 105.05, 1, 7),
    ]
    pool = next(p for p in detect_liquidity_pools(swings, tolerance_pct=0.25) if p.side == "BUY_SIDE")
    assert pool.last_index == 5
    assert pool.confirmed_index == 7


def test_liquidity_sweep_cannot_exist_before_pool_confirmation() -> None:
    pool = LiquidityPool(
        "EQUAL_HIGHS",
        "BUY_SIDE",
        105.0,
        0.25,
        (1, 3),
        1,
        3,
        2,
        5,
    )
    candles = [
        candle(0, 100, 98, 99),
        candle(1, 105.0, 99, 104),
        candle(2, 102, 97, 100),
        candle(3, 105.0, 99, 104),
        candle(4, 106.0, 98, 104.5),  # apparent sweep before pool confirmation
        candle(5, 103, 96, 100),      # pool becomes confirmed here
        candle(6, 106.2, 98, 104.5),  # valid post-confirmation sweep
    ]
    buy_sweeps = [s for s in detect_liquidity_sweeps(candles, [pool]) if s.side == "BUY_SIDE"]
    assert buy_sweeps
    assert buy_sweeps[0].index == 6
    assert buy_sweeps[0].pool_confirmed_index == 5
    assert not any(s.index == 4 for s in buy_sweeps)
