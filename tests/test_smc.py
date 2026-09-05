"""Unit tests for the SMC structure + liquidity engine."""

from src.market_data import Candle, MarketData
from src.smc import (
    analyze_smc,
    detect_liquidity_pools,
    detect_liquidity_sweeps,
    detect_structure_events,
    detect_swings,
)


def candle(
    index: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float = 1_000.0,
) -> Candle:
    return Candle(
        timestamp=index * 3_600_000,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_bullish_structure() -> list[Candle]:
    return [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 103, 100, 102),
        candle(2, 102, 106, 101, 105),
        candle(3, 105, 104, 99, 100),
        candle(4, 100, 102, 96, 98),
        candle(5, 98, 104, 98, 103),
        candle(6, 103, 108, 102, 107),
        candle(7, 107, 106, 101, 103),
        candle(8, 103, 105, 99, 101),
        candle(9, 101, 107, 101, 106),
        candle(10, 106, 110, 105, 109),
        candle(11, 109, 112, 108, 111),
        candle(12, 111, 113, 110, 112),
    ]


def make_bullish_then_bearish_choch() -> list[Candle]:
    candles = make_bullish_structure()
    candles.extend(
        [
            candle(13, 112, 113, 108, 109),
            candle(14, 109, 110, 103, 104),
            candle(15, 104, 105, 97, 98),
            candle(16, 98, 100, 95, 96),
        ]
    )
    return candles


def make_equal_highs_buy_side_sweep() -> list[Candle]:
    return [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 105.00, 100, 104),  # equal-high touch 1
        candle(2, 104, 103, 98, 99),
        candle(3, 99, 104.95, 99, 104),    # equal-high touch 2
        candle(4, 104, 103, 98.5, 100),
        candle(5, 100, 106.2, 99.5, 104.7),  # wick sweeps, close reclaims below pool
        candle(6, 104.7, 104.8, 100, 101),
    ]


def make_equal_lows_sell_side_sweep() -> list[Candle]:
    return [
        candle(0, 100, 102, 99, 101),
        candle(1, 101, 103, 95.00, 96),   # equal-low touch 1
        candle(2, 96, 102, 97, 101),
        candle(3, 101, 102, 95.08, 96),   # equal-low touch 2
        candle(4, 96, 101, 97, 100),
        candle(5, 100, 101, 93.8, 95.4),  # wick sweeps, close reclaims above pool
        candle(6, 95.4, 100, 95, 99),
    ]


def market_with_only_one_hour(candles: list[Candle]) -> MarketData:
    return MarketData(
        symbol="TESTUSDT",
        current_price=None,
        daily=[],
        four_hour=[],
        one_hour=candles,
        fifteen_minute=[],
    )


def test_detect_swings_finds_confirmed_highs_and_lows() -> None:
    candles = make_bullish_structure()
    swings = detect_swings(candles, left=1, right=1)

    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]

    assert highs
    assert lows
    assert any(s.index == 2 for s in highs)
    assert any(s.index == 4 for s in lows)
    assert all(s.strength == 1 for s in swings)


def test_bullish_break_registers_bos() -> None:
    candles = make_bullish_structure()
    swings = detect_swings(candles, left=1, right=1)
    events = detect_structure_events(candles, swings)

    bullish = [e for e in events if e.direction == "BULLISH"]

    assert bullish
    assert bullish[-1].kind == "BOS"
    assert bullish[-1].confirmation == "CLOSE"
    assert bullish[-1].break_price > bullish[-1].broken_swing_price


def test_bearish_break_after_bullish_structure_registers_choch() -> None:
    result = analyze_smc(
        market_with_only_one_hour(make_bullish_then_bearish_choch()),
        timeframe="1h",
        swing_left=1,
        swing_right=1,
    )

    bearish_choch = [
        event
        for event in result.events
        if event.kind == "CHOCH" and event.direction == "BEARISH"
    ]

    assert bearish_choch
    assert result.bias == "BEARISH"
    assert result.trend_state == "BEARISH_TRANSITION"
    assert result.errors == []


def test_wick_only_break_does_not_confirm_when_close_confirmation_enabled() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 104, 100, 103),
        candle(2, 103, 106, 102, 105),
        candle(3, 105, 104, 99, 100),
        candle(4, 100, 102, 96, 98),
        candle(5, 98, 107, 98, 105),
        candle(6, 105, 105.5, 100, 101),
    ]
    swings = detect_swings(candles, left=1, right=1)
    events = detect_structure_events(candles, swings, use_close_confirmation=True)

    assert not any(
        event.direction == "BULLISH"
        and event.broken_swing_price == 106
        for event in events
    )


def test_equal_highs_form_buy_side_liquidity_pool() -> None:
    candles = make_equal_highs_buy_side_sweep()
    swings = detect_swings(candles, left=1, right=1)
    pools = detect_liquidity_pools(swings, tolerance_pct=0.25)

    buy_side = [pool for pool in pools if pool.side == "BUY_SIDE"]

    assert buy_side
    assert buy_side[0].kind == "EQUAL_HIGHS"
    assert buy_side[0].touches >= 2
    assert 104.9 <= buy_side[0].level <= 105.1


def test_equal_lows_form_sell_side_liquidity_pool() -> None:
    candles = make_equal_lows_sell_side_sweep()
    swings = detect_swings(candles, left=1, right=1)
    pools = detect_liquidity_pools(swings, tolerance_pct=0.25)

    sell_side = [pool for pool in pools if pool.side == "SELL_SIDE"]

    assert sell_side
    assert sell_side[0].kind == "EQUAL_LOWS"
    assert sell_side[0].touches >= 2
    assert 94.9 <= sell_side[0].level <= 95.2


def test_buy_side_liquidity_sweep_requires_reclaim_close() -> None:
    candles = make_equal_highs_buy_side_sweep()
    swings = detect_swings(candles, left=1, right=1)
    pools = detect_liquidity_pools(swings, tolerance_pct=0.25)
    sweeps = detect_liquidity_sweeps(candles, pools)

    buy_side_sweeps = [s for s in sweeps if s.side == "BUY_SIDE"]

    assert buy_side_sweeps
    sweep = buy_side_sweeps[0]
    assert sweep.direction == "BEARISH"
    assert sweep.extreme_price > sweep.pool_level
    assert sweep.close_price <= sweep.pool_level
    assert sweep.penetration_pct > 0


def test_sell_side_liquidity_sweep_requires_reclaim_close() -> None:
    candles = make_equal_lows_sell_side_sweep()
    swings = detect_swings(candles, left=1, right=1)
    pools = detect_liquidity_pools(swings, tolerance_pct=0.25)
    sweeps = detect_liquidity_sweeps(candles, pools)

    sell_side_sweeps = [s for s in sweeps if s.side == "SELL_SIDE"]

    assert sell_side_sweeps
    sweep = sell_side_sweeps[0]
    assert sweep.direction == "BULLISH"
    assert sweep.extreme_price < sweep.pool_level
    assert sweep.close_price >= sweep.pool_level


def test_close_acceptance_beyond_pool_is_not_a_sweep() -> None:
    candles = make_equal_highs_buy_side_sweep()
    candles[5] = candle(5, 100, 106.2, 99.5, 105.7)  # closes above equal highs

    swings = detect_swings(candles, left=1, right=1)
    pools = detect_liquidity_pools(swings, tolerance_pct=0.25)
    sweeps = detect_liquidity_sweeps(candles, pools)

    assert not any(s.side == "BUY_SIDE" and s.index == 5 for s in sweeps)


def test_analyze_smc_exposes_liquidity_evidence() -> None:
    result = analyze_smc(
        market_with_only_one_hour(make_equal_lows_sell_side_sweep()),
        timeframe="1h",
        swing_left=1,
        swing_right=1,
        liquidity_tolerance_pct=0.25,
    )

    assert result.liquidity_pools
    assert result.liquidity_sweeps
    assert any(s.side == "SELL_SIDE" for s in result.liquidity_sweeps)
    assert result.errors == []


def test_smc_requires_only_selected_timeframe() -> None:
    result = analyze_smc(
        market_with_only_one_hour(make_bullish_structure()),
        timeframe="1h",
        swing_left=1,
        swing_right=1,
    )

    assert result.trend_state != "INVALID_DATA"
    assert result.errors == []
    assert result.timeframe == "1h"


def test_missing_selected_timeframe_is_invalid() -> None:
    market = MarketData(
        symbol="BROKENUSDT",
        current_price=None,
        daily=[],
        four_hour=[],
        one_hour=[],
        fifteen_minute=[],
    )

    result = analyze_smc(market, timeframe="1h")

    assert result.bias == "UNKNOWN"
    assert result.trend_state == "INVALID_DATA"
    assert result.liquidity_pools == []
    assert result.liquidity_sweeps == []
    assert "1H_DATA_UNAVAILABLE" in result.errors
