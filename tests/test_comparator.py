import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from backtest import BacktestResult
from comparator import ComparatorConfig, TradeFrequencyEvidence, compare_research_to_paper
from paper_session import PaperSessionSummary


def _backtest(expectancy=0.40, win_rate=52.0, pf=1.50, dd=6.0):
    return BacktestResult(
        symbol="BTCUSDT", initial_equity=10000, final_equity=11000,
        trades=[], equity_curve=[], total_trades=20, wins=10, losses=10,
        open_end=0, win_rate_pct=win_rate, expectancy_r=expectancy,
        profit_factor=pf, total_net_pnl=1000, total_return_pct=10.0,
        max_drawdown_pct=dd, ignored_overlapping_entries=0, errors=[],
    )


def _paper(trades=12, expectancy=0.32, win_rate=50.0, pf=1.35, dd=7.0):
    return PaperSessionSummary(
        initial_equity=10000, equity=10500, realized_pnl=500, return_pct=5.0,
        total_decisions=200, action_counts={"ENTER_LONG": trades}, open_positions=0,
        exposure_pct=0.0, total_trades=trades, wins=6, losses=6,
        win_rate_pct=win_rate, expectancy_r=expectancy, profit_factor=pf,
        max_drawdown_pct=dd, symbols_seen=4, errors=[],
    )


def test_aligned_when_core_metrics_stay_close():
    result = compare_research_to_paper(
        _backtest(),
        _paper(),
        frequency_evidence=TradeFrequencyEvidence(20, 300, 12, 200),
    )
    assert result.verdict == "ALIGNED"
    assert result.promotion_allowed is True
    assert result.diverged_metrics == 0


def test_degraded_when_multiple_metrics_weaken_but_edge_stays_positive():
    result = compare_research_to_paper(
        _backtest(),
        _paper(expectancy=0.20, win_rate=43.0, pf=1.05, dd=8.0),
        config=ComparatorConfig(max_degraded_metrics_for_aligned=0),
    )
    assert result.verdict == "DEGRADED"
    assert result.promotion_allowed is False


def test_diverged_when_paper_expectancy_turns_negative():
    result = compare_research_to_paper(_backtest(), _paper(expectancy=-0.10, pf=0.8))
    assert result.verdict == "DIVERGED"
    assert result.promotion_allowed is False


def test_insufficient_when_paper_sample_too_small():
    result = compare_research_to_paper(_backtest(), _paper(trades=4))
    assert result.verdict == "INSUFFICIENT_DATA"
    assert result.promotion_allowed is False


def test_trade_frequency_is_unavailable_without_compatible_denominator():
    result = compare_research_to_paper(_backtest(), _paper())
    frequency = next(item for item in result.comparisons if item.metric == "trade_frequency_pct")
    assert frequency.status == "UNAVAILABLE"
    assert result.unavailable_metrics >= 1


def test_trade_frequency_drift_can_diverge():
    result = compare_research_to_paper(
        _backtest(),
        _paper(),
        frequency_evidence=TradeFrequencyEvidence(20, 200, 12, 500),
        config=ComparatorConfig(max_trade_frequency_drift_pct=20.0),
    )
    frequency = next(item for item in result.comparisons if item.metric == "trade_frequency_pct")
    assert frequency.status == "DIVERGED"
    assert result.verdict == "DIVERGED"
    assert result.promotion_allowed is False
