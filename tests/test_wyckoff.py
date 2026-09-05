"""Unit tests for the hardened Wyckoff analysis engine."""

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
    return [candle(i, 100.0, 101.0, 99.0, 100.2, 1_000.0) for i in range(count)]


def make_daily_stub(count: int = 20) -> list[Candle]:
    return [candle(i, 100.0, 102.0, 98.0, 101.0, 2_000.0) for i in range(count)]


def make_accumulation_sequence() -> list[Candle]:
    candles: list[Candle] = []

    # Stable auction around 91-109 before the event sequence.
    for i in range(12):
        close = 99.0 + (i % 4)
        candles.append(candle(i, close - 0.4, 109.0, 91.0, close, 1_000.0))

    # SC -> AR -> ST.
    candles.append(candle(12, 96.0, 101.0, 88.5, 95.0, 2_500.0))
    candles.append(candle(13, 95.0, 108.0, 94.0, 106.0, 1_700.0))
    candles.append(candle(14, 98.0, 101.0, 91.5, 97.0, 850.0))

    # Phase-B rotation.
    for i, close in enumerate([99.0, 101.0, 100.0, 102.0, 101.5, 103.0], start=15):
        candles.append(candle(i, close - 0.5, close + 2.0, close - 2.0, close, 900.0))

    # Spring -> test -> SOS -> LPS.
    candles.append(candle(21, 94.0, 99.0, 87.0, 94.5, 1_250.0))
    candles.append(candle(22, 94.5, 104.0, 93.0, 102.5, 1_200.0))
    candles.append(candle(23, 103.0, 114.0, 102.0, 112.0, 1_900.0))
    candles.append(candle(24, 111.0, 115.0, 109.0, 113.0, 1_400.0))

    return candles


def make_strong_trend(count: int = 30) -> list[Candle]:
    candles: list[Candle] = []
    for i in range(count):
        close = 100.0 + i * 2.0
        candles.append(candle(i, close - 1.0, close + 1.5, close - 1.5, close, 1_000.0))
    return candles


def make_market(
    four_hour: list[Candle],
    *,
    include_other_timeframes: bool = True,
    include_current_price: bool = True,
) -> MarketData:
    intraday = make_intraday_stub() if include_other_timeframes else []
    return MarketData(
        symbol="TESTUSDT",
        current_price=(four_hour[-1].close if four_hour and include_current_price else None),
        daily=make_daily_stub() if include_other_timeframes else [],
        four_hour=four_hour,
        one_hour=intraday,
        fifteen_minute=intraday,
    )


def test_detect_trading_range_returns_stable_boundaries() -> None:
    trading_range = detect_trading_range(make_accumulation_sequence())

    assert trading_range is not None
    assert trading_range.support < 100 < trading_range.resistance
    assert trading_range.width_pct > 0
    assert trading_range.stability_score >= 50
    assert trading_range.support_touches >= 2
    assert trading_range.resistance_touches >= 2


def test_strong_directional_trend_is_not_misclassified_as_range() -> None:
    assert detect_trading_range(make_strong_trend()) is None

    result = analyze_wyckoff(make_market(make_strong_trend()))
    assert result.bias == "NEUTRAL"
    assert result.phase == "NO_RANGE"
    assert result.events == []


def test_accumulation_sequence_requires_ordered_evidence() -> None:
    result = analyze_wyckoff(make_market(make_accumulation_sequence()))
    codes = [event.code for event in result.events]

    assert result.bias == "ACCUMULATION"
    assert result.phase == "D_TO_E"
    assert result.confidence >= 60

    for required in ["SC", "AR", "ST", "SPRING", "SOS", "LPS"]:
        assert required in codes

    positions = {code: next(event.index for event in result.events if event.code == code) for code in ["SC", "AR", "ST", "SPRING", "SOS", "LPS"]}
    assert positions["SC"] < positions["AR"] < positions["ST"]
    assert positions["ST"] < positions["SPRING"] < positions["SOS"] < positions["LPS"]
    assert result.errors == []


def test_wyckoff_only_requires_four_hour_data() -> None:
    market = make_market(
        make_accumulation_sequence(),
        include_other_timeframes=False,
        include_current_price=False,
    )

    result = analyze_wyckoff(market)

    assert result.phase != "INVALID_DATA"
    assert "4H_DATA_UNAVAILABLE" not in result.errors


def test_events_before_current_range_window_are_ignored() -> None:
    old_noise = [
        candle(i, 95.0, 103.0, 80.0 if i == 5 else 90.0, 96.0, 5_000.0 if i == 5 else 1_000.0)
        for i in range(10)
    ]

    recent_range = []
    for i in range(10, 40):
        close = 100.0 + ((i % 5) - 2) * 0.5
        recent_range.append(candle(i, close - 0.4, 108.0, 92.0, close, 1_000.0))

    result = analyze_wyckoff(make_market(old_noise + recent_range), lookback=30)

    assert result.trading_range is not None
    assert result.trading_range.start_index == 10
    assert all(event.index >= result.trading_range.start_index for event in result.events)


def test_missing_four_hour_data_is_rejected_without_irrelevant_errors() -> None:
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
    assert result.errors == ["4H_DATA_UNAVAILABLE"]
