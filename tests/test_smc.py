"""Unit tests for the SMC market structure engine."""

from src.market_data import Candle, MarketData
from src.smc import analyze_smc, detect_structure_events, detect_swings


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
    # Produces alternating confirmed pivots and a final close above the latest
    # swing high, which should register as bullish BOS.
    return [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 103, 100, 102),
        candle(2, 102, 106, 101, 105),  # swing high
        candle(3, 105, 104, 99, 100),
        candle(4, 100, 102, 96, 98),   # swing low
        candle(5, 98, 104, 98, 103),
        candle(6, 103, 108, 102, 107),  # higher swing high
        candle(7, 107, 106, 101, 103),
        candle(8, 103, 105, 99, 101),   # higher swing low
        candle(9, 101, 107, 101, 106),
        candle(10, 106, 110, 105, 109),
        candle(11, 109, 112, 108, 111),  # breaks swing high by close
        candle(12, 111, 113, 110, 112),
    ]


def make_bullish_then_bearish_choch() -> list[Candle]:
    candles = make_bullish_structure()
    candles.extend(
        [
            candle(13, 112, 113, 108, 109),
            candle(14, 109, 110, 103, 104),
            candle(15, 104, 105, 97, 98),  # closes below latest swing low
            candle(16, 98, 100, 95, 96),
        ]
    )
    return candles


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
    candles = make_bullish_then_bearish_choch()
    result = analyze_smc(
        market_with_only_one_hour(candles),
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
        candle(2, 103, 106, 102, 105),  # swing high
        candle(3, 105, 104, 99, 100),
        candle(4, 100, 102, 96, 98),   # swing low
        candle(5, 98, 107, 98, 105),   # wick above 106, close below 106
        candle(6, 105, 105.5, 100, 101),
    ]
    swings = detect_swings(candles, left=1, right=1)
    events = detect_structure_events(candles, swings, use_close_confirmation=True)

    assert not any(
        event.direction == "BULLISH"
        and event.broken_swing_price == 106
        for event in events
    )


def test_smc_requires_only_selected_timeframe() -> None:
    market = market_with_only_one_hour(make_bullish_structure())

    result = analyze_smc(
        market,
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
    assert "1H_DATA_UNAVAILABLE" in result.errors
