from src.history_sufficiency import evaluate_history_sufficiency
from src.market_data import Candle, MarketData


def _candles(count: int):
    return [Candle(i, 100.0, 101.0, 99.0, 100.0, 10.0) for i in range(count)]


def _market(daily=20, four_hour=30, one_hour=5, fifteen=1):
    return MarketData(
        "BTCUSDT",
        100.0,
        _candles(daily),
        _candles(four_hour),
        _candles(one_hour),
        _candles(fifteen),
    )


def test_current_v1_requirements_pass_without_daily_ma200():
    result = evaluate_history_sufficiency(_market(daily=119, four_hour=239, one_hour=299, fifteen=299))
    assert result.ready is True
    assert result.blockers == ()
    assert "1D_MA200_UNAVAILABLE_NOT_REQUIRED_BY_V1" in result.warnings


def test_scanner_daily_history_is_required():
    result = evaluate_history_sufficiency(_market(daily=19))
    assert result.ready is False
    assert any(blocker.startswith("INSUFFICIENT_HISTORY:SCANNER:1d") for blocker in result.blockers)


def test_full_wyckoff_window_is_required_for_live_validation():
    result = evaluate_history_sufficiency(_market(four_hour=29))
    assert result.ready is False
    assert any(blocker.startswith("INSUFFICIENT_HISTORY:WYCKOFF:4h") for blocker in result.blockers)


def test_smc_minimum_tracks_configured_timeframe():
    market = _market(one_hour=1, fifteen=5)
    result = evaluate_history_sufficiency(market, smc_timeframe="15m")
    assert result.ready is True


def test_invalid_smc_timeframe_fails_fast():
    try:
        evaluate_history_sufficiency(_market(), smc_timeframe="5m")
    except ValueError as exc:
        assert "Unsupported SMC timeframe" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
