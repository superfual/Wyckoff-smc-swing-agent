"""Unit tests for the market candidate scanner."""

from src.market_data import Candle, MarketData
from src.scanner import (
    classify_score,
    load_watchlist,
    rank_scan_results,
    scan_market,
)


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


def make_daily_bullish() -> list[Candle]:
    candles = []
    for i in range(20):
        close = 90.0 + i
        candles.append(
            candle(i, close - 0.5, close + 1.0, close - 1.0, close, 1_000.0)
        )
    return candles


def make_four_hour_accumulation_like() -> list[Candle]:
    candles = []

    # Older, wider range with higher volume. This provides a broad baseline.
    for i in range(8):
        close = 98.0 + (i % 3)
        candles.append(
            candle(i, close - 0.5, 110.0, 90.0, close, 2_000.0)
        )

    # Previous structure window.
    previous_closes = [99.0, 100.0, 100.5, 101.0, 101.5, 102.0]
    for offset, close in enumerate(previous_closes, start=8):
        candles.append(
            candle(offset, close - 0.4, close + 1.0, close - 1.5, close, 1_600.0)
        )

    # Recent structure: higher low, higher high, narrower range and lighter volume.
    recent_closes = [102.2, 102.8, 103.4, 104.0, 104.8, 105.6]
    for offset, close in enumerate(recent_closes, start=14):
        candles.append(
            candle(offset, close - 0.6, close + 0.8, close - 0.8, close, 700.0)
        )

    return candles


def make_four_hour_weak() -> list[Candle]:
    candles = []
    for i in range(20):
        close = 120.0 - (i * 1.2)
        candles.append(
            candle(
                i,
                close + 0.8,
                close + 1.2,
                close - 1.0,
                close,
                1_000.0 + (i * 40.0),
            )
        )
    return candles


def make_intraday_stub(count: int = 20) -> list[Candle]:
    return [
        candle(i, 100.0, 101.0, 99.0, 100.2, 1_000.0)
        for i in range(count)
    ]


def make_market(symbol: str, daily: list[Candle], four_hour: list[Candle]) -> MarketData:
    intraday = make_intraday_stub()
    return MarketData(
        symbol=symbol,
        current_price=four_hour[-1].close if four_hour else None,
        daily=daily,
        four_hour=four_hour,
        one_hour=intraday,
        fifteen_minute=intraday,
    )


def test_accumulation_like_market_is_high_interest() -> None:
    market = make_market(
        "TESTUSDT",
        make_daily_bullish(),
        make_four_hour_accumulation_like(),
    )

    result = scan_market(market, priority="HIGH")

    assert result.classification == "HIGH_INTEREST"
    assert result.score >= 75
    assert result.priority == "HIGH"
    assert "4H_HIGHER_LOW" in result.signals
    assert "4H_HIGHER_HIGH" in result.signals
    assert "4H_VOLUME_CONTRACTION" in result.signals
    assert "4H_BUY_VOLUME_DOMINANCE" in result.signals
    assert any(
        signal in result.signals
        for signal in ("4H_TIGHT_COMPRESSION", "4H_RANGE_COMPRESSION")
    )
    assert result.errors == []


def test_weak_market_is_not_promoted_to_watch() -> None:
    daily = []
    for i in range(20):
        close = 140.0 - (i * 1.5)
        daily.append(
            candle(i, close + 0.5, close + 1.0, close - 1.0, close, 1_000.0)
        )

    market = make_market("WEAKUSDT", daily, make_four_hour_weak())
    result = scan_market(market)

    assert result.score < 60
    assert result.classification in {"LOW_INTEREST", "NEUTRAL"}
    assert "4H_HIGHER_LOW" not in result.signals
    assert "4H_HIGHER_HIGH" not in result.signals
    assert "4H_BUY_VOLUME_DOMINANCE" not in result.signals


def test_missing_required_timeframe_returns_invalid_data() -> None:
    market = MarketData(
        symbol="BROKENUSDT",
        current_price=100.0,
        daily=make_daily_bullish(),
        four_hour=make_four_hour_accumulation_like(),
        one_hour=make_intraday_stub(),
        fifteen_minute=[],
    )

    result = scan_market(market)

    assert result.score == 0.0
    assert result.classification == "INVALID_DATA"
    assert "15M_DATA_UNAVAILABLE" in result.errors
    assert result.signals == []


def test_valid_results_rank_ahead_of_invalid_results() -> None:
    strong = scan_market(
        make_market(
            "STRONGUSDT",
            make_daily_bullish(),
            make_four_hour_accumulation_like(),
        ),
        priority="HIGH",
    )

    weak = scan_market(
        make_market("WEAKUSDT", make_daily_bullish(), make_four_hour_weak()),
        priority="MEDIUM",
    )

    invalid_market = MarketData(
        symbol="INVALIDUSDT",
        current_price=None,
        daily=[],
        four_hour=[],
        one_hour=[],
        fifteen_minute=[],
    )
    invalid = scan_market(invalid_market)

    ranked = rank_scan_results([invalid, weak, strong])

    assert ranked[0].symbol == "STRONGUSDT"
    assert ranked[-1].classification == "INVALID_DATA"


def test_score_classification_boundaries() -> None:
    assert classify_score(75.0) == "HIGH_INTEREST"
    assert classify_score(60.0) == "WATCH"
    assert classify_score(45.0) == "NEUTRAL"
    assert classify_score(44.99) == "LOW_INTEREST"


def test_repository_watchlist_loads_enabled_symbols() -> None:
    watchlist = load_watchlist()
    symbols = {item.symbol for item in watchlist}

    assert {"BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT"}.issubset(symbols)
    assert all(item.symbol.endswith("USDT") for item in watchlist)
