"""Unit tests for the Wyckoff analysis engine."""

from src.market_data import Candle, MarketData
from src.wyckoff import analyze_wyckoff, detect_trading_range


def candle(
    index: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    volume: float,
) -> Candle:
    return Candle(
        timestamp=index * 14_400_000,
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=volume,
    )


def make_intraday_stub(count: int = 20) -> list[Candle]:
    return [
        candle(i, 100.0, 101.0, 99.0, 100.2, 1_000.0)
        for i in range(count)
    ]


def make_daily_stub(count: int = 20) -> list[Candle]:
    return [
        candle(i, 100.0, 102.0, 98.0, 101.0, 2_000.0)
        for i in range(count)
    ]


def make_accumulation_sequence() -> list[Candle]:
    candles: list[Candle] = []

    # Establish a broad trading range around 90-110.
    for i in range(12):
        close = 99.0 + (i % 4)
        candles.append(candle(i, close - 0.4, 109.0, 91.0, close, 1_000.0))

    # Selling climax near support with range expansion and high volume.
    candles.append(candle(12, 96.0, 101.0, 88.5, 95.0, 2_500.0))

    # Automatic rally / range recovery.
    candles.append(candle(13, 95.0, 108.0, 94.0, 106.0, 1_700.0))

    # Secondary-test style lower-range revisit on lighter volume.
    candles.append(candle(14, 98.0, 101.0, 91.5, 97.0, 850.0))

    # Mid-range rotation.
    for i, close in enumerate([99.0, 101.0, 100.0, 102.0, 101.5, 103.0], start=15):
        candles.append(candle(i, close - 0.5, close + 2.0, close - 2.0, close, 900.0))

    # Spring: sweep below support, then reclaim.
    candles.append(candle(21, 94.0, 99.0, 87.0, 94.5, 1_250.0))

    # Follow-through inside the range.
    candles.append(candle(22, 94.5, 104.0, 93.0, 102.5, 1_200.0))

    # SOS-style breakout above resistance with stronger volume.
    candles.append(candle(23, 103.0, 114.0, 102.0, 112.0, 1_900.0))

    # Hold above the range.
    candles.append(candle(24, 111.0, 115.0, 109.0, 113.0, 1_400.0))

    return candles


def make_market(four_hour: list[Candle]) -> MarketData:
    intraday = make_intraday_stub()
    return MarketData(
        symbol="TESTUSDT",
        current_price=four_hour[-1].close if four_hour else None,
        daily=make_daily_stub(),
        four_hour=four_hour,
        one_hour=intraday,
        fifteen_minute=intraday,
    )


def test_detect_trading_range_returns_valid_boundaries() -> None:
    candles = make_accumulation_sequence()
    trading_range = detect_trading_range(candles)

    assert trading_range is not None
    assert trading_range.support < trading_range.resistance
    assert trading_range.support < 100 < trading_range.resistance
    assert trading_range.width_pct > 0


def test_accumulation_sequence_detects_bullish_wyckoff_evidence() -> None:
    result = analyze_wyckoff(make_market(make_accumulation_sequence()))
    codes = {event.code for event in result.events}

    assert result.bias == "ACCUMULATION"
    assert result.phase in {"C_TO_D", "D_TO_E"}
    assert result.confidence >= 50
    assert "SPRING" in codes
    assert "SOS" in codes
    assert result.trading_range is not None
    assert result.errors == []


def test_invalid_market_data_is_rejected() -> None:
    market = MarketData(
        symbol="BROKENUSDT",
        current_price=None,
        daily=[],
        four_hour=[],
        one_hour=[],
        fifteen_minute=[],
    )

    result = analyze_wyckoff(market)

    assert result.bias == "UNKNOWN"
    assert result.phase == "INVALID_DATA"
    assert result.confidence == 0.0
    assert result.trading_range is None
    assert result.events == []
    assert "CURRENT_PRICE_UNAVAILABLE" in result.errors
