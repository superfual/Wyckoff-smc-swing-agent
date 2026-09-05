import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backtest import BacktestResult
from market_data import Candle, MarketData
from replay import ReplayConfig
from walk_forward import WalkForwardConfig, _fold_verdict, run_walk_forward


def _bt(expectancy, trades=6, drawdown=5.0):
    return BacktestResult(
        symbol="BTCUSDT", initial_equity=10000, final_equity=10100,
        trades=[], equity_curve=[], total_trades=trades, wins=3, losses=3,
        open_end=0, win_rate_pct=50.0, expectancy_r=expectancy,
        profit_factor=1.5, total_net_pnl=100, total_return_pct=1.0,
        max_drawdown_pct=drawdown, ignored_overlapping_entries=0, errors=[],
    )


def _candles(count):
    return [Candle(i * 3_600_000, 100, 101, 99, 100, 10) for i in range(count)]


def _market(count=30):
    candles = _candles(count)
    return MarketData("BTCUSDT", 100, candles, candles, candles, candles)


def test_fold_verdict_robust_when_edge_survives():
    verdict, reasons, retention = _fold_verdict(
        _bt(0.60, drawdown=5.0), _bt(0.45, trades=4, drawdown=6.0), WalkForwardConfig()
    )
    assert verdict == "ROBUST"
    assert retention == 75.0
    assert reasons


def test_fold_verdict_degraded_when_expectancy_fades():
    verdict, _, retention = _fold_verdict(
        _bt(0.80), _bt(0.20, trades=4), WalkForwardConfig()
    )
    assert verdict == "DEGRADED"
    assert retention == 25.0


def test_fold_verdict_failed_when_validation_turns_negative():
    verdict, reasons, _ = _fold_verdict(
        _bt(0.50), _bt(-0.10, trades=4), WalkForwardConfig()
    )
    assert verdict == "FAILED"
    assert any("non-positive" in reason for reason in reasons)


def test_fold_verdict_requires_enough_trades():
    verdict, _, retention = _fold_verdict(
        _bt(0.50, trades=2), _bt(0.40, trades=1), WalkForwardConfig()
    )
    assert verdict == "INSUFFICIENT_DATA"
    assert retention is None


def test_walk_forward_rejects_history_too_short():
    result = run_walk_forward(
        _market(20),
        account_equity=10000,
        config=WalkForwardConfig(research_bars=12, validation_bars=8, step_bars=4),
        replay_config=ReplayConfig(reference_timeframe="1h", warmup_bars=10),
    )
    assert result.verdict == "INSUFFICIENT_DATA"
    assert "VALIDATION_WINDOW_BELOW_WARMUP" in result.errors


def test_walk_forward_generates_chronological_non_overlapping_test_windows():
    result = run_walk_forward(
        _market(30),
        account_equity=10000,
        config=WalkForwardConfig(
            research_bars=10,
            validation_bars=5,
            step_bars=5,
            min_folds=3,
            min_research_trades=1,
            min_validation_trades=1,
        ),
        replay_config=ReplayConfig(reference_timeframe="1h", warmup_bars=5),
    )
    assert result.total_folds == 4
    assert [fold.validation_start_index for fold in result.folds] == [10, 15, 20, 25]
    assert [fold.validation_end_index for fold in result.folds] == [14, 19, 24, 29]
    for fold in result.folds:
        assert fold.research_end_index < fold.validation_start_index
