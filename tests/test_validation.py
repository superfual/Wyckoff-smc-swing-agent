"""Unit tests for out-of-sample validation."""

from src.analytics import PerformanceAnalytics
from src.backtest import BacktestResult
from src.market_data import Candle, MarketData
from src.replay import ReplayConfig, ReplayResult
from src.validation import OOSConfig, ValidationWindowResult, validate_out_of_sample


def candle(index: int, close: float = 100.0) -> Candle:
    return Candle(index * 3_600_000, close, close + 1, close - 1, close, 1_000.0)


def market(bars: int = 100) -> MarketData:
    one_hour = [candle(i, 100 + i * 0.1) for i in range(bars)]
    return MarketData(
        symbol="TESTUSDT",
        current_price=one_hour[-1].close,
        daily=[Candle(0,100,105,95,102,1000), Candle(86_400_000,102,108,98,106,1000)],
        four_hour=[candle(i * 4, 100 + i * 0.2) for i in range(max(2, bars // 4))],
        one_hour=one_hour,
        fifteen_minute=[Candle(i * 900_000,100,101,99,100,1000) for i in range(bars * 4)],
    )


def fake_window(name: str, expectancy: float, trades: int, win_rate: float, pf: float, dd: float) -> ValidationWindowResult:
    replay = ReplayResult("TESTUSDT", "1h", [], {}, None, None, [])
    backtest = BacktestResult(
        symbol="TESTUSDT",
        initial_equity=10_000.0,
        final_equity=10_000.0,
        trades=[],
        equity_curve=[],
        total_trades=trades,
        wins=0,
        losses=0,
        open_end=0,
        win_rate_pct=win_rate,
        expectancy_r=expectancy,
        profit_factor=pf,
        total_net_pnl=0.0,
        total_return_pct=0.0,
        max_drawdown_pct=dd,
        ignored_overlapping_entries=0,
        errors=[],
    )
    analytics = PerformanceAnalytics(
        symbol="TESTUSDT",
        total_trades=trades,
        by_direction=[],
        by_wyckoff_phase=[],
        by_confluence=[],
        by_scanner_bucket=[],
        strongest_segments=[],
        weakest_segments=[],
        interpretation="test",
        errors=[],
    )
    return ValidationWindowResult(name, 0, 1, replay, backtest, analytics)


def test_robust_when_positive_edge_survives(monkeypatch) -> None:
    def stub(name, *args, **kwargs):
        return fake_window(name, 0.60, 12, 50.0, 1.8, 6.0) if name == "RESEARCH" else fake_window(name, 0.42, 7, 48.0, 1.5, 8.0)

    monkeypatch.setattr("src.validation._run_window", stub)
    result = validate_out_of_sample(
        market(), account_equity=10_000, replay_config=ReplayConfig(reference_timeframe="1h", warmup_bars=20)
    )
    assert result.verdict == "ROBUST"
    assert result.expectancy_retention_pct == 70.0
    assert result.errors == []


def test_degraded_when_expectancy_falls_too_far(monkeypatch) -> None:
    def stub(name, *args, **kwargs):
        return fake_window(name, 0.80, 12, 55.0, 2.0, 5.0) if name == "RESEARCH" else fake_window(name, 0.20, 7, 44.0, 1.1, 6.0)

    monkeypatch.setattr("src.validation._run_window", stub)
    result = validate_out_of_sample(
        market(), account_equity=10_000, replay_config=ReplayConfig(reference_timeframe="1h", warmup_bars=20)
    )
    assert result.verdict == "DEGRADED"
    assert any("Expectancy degraded" in reason for reason in result.reasons)


def test_failed_when_validation_expectancy_turns_negative(monkeypatch) -> None:
    def stub(name, *args, **kwargs):
        return fake_window(name, 0.50, 10, 50.0, 1.7, 5.0) if name == "RESEARCH" else fake_window(name, -0.15, 6, 35.0, 0.8, 8.0)

    monkeypatch.setattr("src.validation._run_window", stub)
    result = validate_out_of_sample(
        market(), account_equity=10_000, replay_config=ReplayConfig(reference_timeframe="1h", warmup_bars=20)
    )
    assert result.verdict == "FAILED"
    assert any("did not survive" in reason for reason in result.reasons)


def test_insufficient_trade_samples_prevent_judgment(monkeypatch) -> None:
    def stub(name, *args, **kwargs):
        return fake_window(name, 0.90, 2, 100.0, 9.0, 1.0)

    monkeypatch.setattr("src.validation._run_window", stub)
    result = validate_out_of_sample(
        market(),
        account_equity=10_000,
        config=OOSConfig(min_research_trades=5, min_validation_trades=3),
        replay_config=ReplayConfig(reference_timeframe="1h", warmup_bars=20),
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert len(result.reasons) == 2


def test_invalid_split_ratio_is_rejected_without_running_windows(monkeypatch) -> None:
    def should_not_run(*args, **kwargs):
        raise AssertionError("window should not run")

    monkeypatch.setattr("src.validation._run_window", should_not_run)
    result = validate_out_of_sample(
        market(),
        account_equity=10_000,
        config=OOSConfig(split_ratio=0.95),
        replay_config=ReplayConfig(reference_timeframe="1h", warmup_bars=20),
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert "INVALID_SPLIT_RATIO" in result.errors
