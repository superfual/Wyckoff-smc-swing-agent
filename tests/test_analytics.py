"""Unit tests for backtest performance analytics."""

from src.analytics import AnalyticsConfig, analyze_backtest, scanner_score_bucket
from src.backtest import BacktestResult, EquityPoint, SimulatedTrade


def trade(
    *,
    direction: str,
    outcome: str,
    net_r: float,
    pnl: float,
    phase: str,
    confluence: str,
    scanner: float,
    index: int,
) -> SimulatedTrade:
    return SimulatedTrade(
        symbol="TESTUSDT",
        direction=direction,
        entry_bar_index=index,
        exit_bar_index=index + 1,
        entry_time=index,
        exit_time=index + 1,
        entry_price=100.0,
        exit_price=110.0 if outcome == "WIN" else 95.0,
        stop_price=95.0,
        target_price=110.0,
        position_size_quote=1_000.0,
        gross_pnl_quote=pnl,
        fees_quote=0.0,
        net_pnl_quote=pnl,
        gross_r=net_r,
        net_r=net_r,
        outcome=outcome,
        exit_reason="TARGET" if outcome == "WIN" else ("STOP" if outcome == "LOSS" else "END_OF_DATA"),
        confluence_classification=confluence,
        confluence_confidence=80.0,
        wyckoff_phase=phase,
        scanner_score=scanner,
    )


def result(trades: list[SimulatedTrade], errors: list[str] | None = None) -> BacktestResult:
    total_pnl = sum(item.net_pnl_quote for item in trades)
    wins = sum(item.outcome == "WIN" for item in trades)
    losses = sum(item.outcome == "LOSS" for item in trades)
    open_end = sum(item.outcome == "OPEN_END" for item in trades)
    return BacktestResult(
        symbol="TESTUSDT",
        initial_equity=10_000.0,
        final_equity=10_000.0 + total_pnl,
        trades=trades,
        equity_curve=[EquityPoint(-1, 0, 10_000.0)],
        total_trades=len(trades),
        wins=wins,
        losses=losses,
        open_end=open_end,
        win_rate_pct=0.0,
        expectancy_r=0.0,
        profit_factor=None,
        total_net_pnl=total_pnl,
        total_return_pct=0.0,
        max_drawdown_pct=0.0,
        ignored_overlapping_entries=0,
        errors=errors or [],
    )


def sample_trades() -> list[SimulatedTrade]:
    return [
        trade(direction="LONG", outcome="WIN", net_r=2.0, pnl=200, phase="D_TO_E", confluence="HIGH_CONVICTION_BULLISH", scanner=84, index=1),
        trade(direction="LONG", outcome="WIN", net_r=1.5, pnl=150, phase="D_TO_E", confluence="HIGH_CONVICTION_BULLISH", scanner=82, index=2),
        trade(direction="LONG", outcome="LOSS", net_r=-1.0, pnl=-100, phase="D_TO_E", confluence="HIGH_CONVICTION_BULLISH", scanner=81, index=3),
        trade(direction="SHORT", outcome="LOSS", net_r=-1.0, pnl=-100, phase="B_TO_C", confluence="BEARISH", scanner=65, index=4),
        trade(direction="SHORT", outcome="LOSS", net_r=-1.0, pnl=-100, phase="B_TO_C", confluence="BEARISH", scanner=67, index=5),
        trade(direction="SHORT", outcome="WIN", net_r=0.5, pnl=50, phase="B_TO_C", confluence="BEARISH", scanner=66, index=6),
    ]


def test_scanner_score_buckets_are_stable() -> None:
    assert scanner_score_bucket(59.9) == "BELOW_60"
    assert scanner_score_bucket(60) == "60_TO_69"
    assert scanner_score_bucket(70) == "70_TO_79"
    assert scanner_score_bucket(80) == "80_PLUS"


def test_direction_segments_calculate_expectancy_and_win_rate() -> None:
    analytics = analyze_backtest(result(sample_trades()), config=AnalyticsConfig(min_sample_size=3))
    long_segment = next(item for item in analytics.by_direction if item.segment == "LONG")
    short_segment = next(item for item in analytics.by_direction if item.segment == "SHORT")
    assert long_segment.total_trades == 3
    assert long_segment.win_rate_pct == 66.6667
    assert long_segment.expectancy_r == 0.8333
    assert long_segment.sample_status == "POSITIVE_EDGE"
    assert short_segment.expectancy_r == -0.5
    assert short_segment.sample_status == "NEGATIVE_EDGE"


def test_phase_and_confluence_segments_identify_stronger_edge() -> None:
    analytics = analyze_backtest(result(sample_trades()), config=AnalyticsConfig(min_sample_size=3))
    assert analytics.strongest_segments
    best = analytics.strongest_segments[0]
    assert best.expectancy_r > 0
    assert any(item.segment == "D_TO_E" and item.expectancy_r == 0.8333 for item in analytics.by_wyckoff_phase)
    assert any(item.segment == "HIGH_CONVICTION_BULLISH" and item.expectancy_r == 0.8333 for item in analytics.by_confluence)


def test_small_segments_are_not_ranked_as_edge() -> None:
    trades = [
        trade(direction="LONG", outcome="WIN", net_r=5.0, pnl=500, phase="RARE", confluence="RARE", scanner=90, index=1),
        trade(direction="SHORT", outcome="LOSS", net_r=-1.0, pnl=-100, phase="COMMON", confluence="COMMON", scanner=65, index=2),
        trade(direction="SHORT", outcome="LOSS", net_r=-1.0, pnl=-100, phase="COMMON", confluence="COMMON", scanner=66, index=3),
        trade(direction="SHORT", outcome="LOSS", net_r=-1.0, pnl=-100, phase="COMMON", confluence="COMMON", scanner=67, index=4),
    ]
    analytics = analyze_backtest(result(trades), config=AnalyticsConfig(min_sample_size=3))
    rare = next(item for item in analytics.by_wyckoff_phase if item.segment == "RARE")
    assert rare.sample_status == "INSUFFICIENT_SAMPLE"
    assert all(item.segment != "RARE" for item in analytics.strongest_segments)


def test_open_end_trade_is_counted_but_not_resolved_win_rate() -> None:
    trades = [
        trade(direction="LONG", outcome="WIN", net_r=1.0, pnl=100, phase="D_TO_E", confluence="BULLISH", scanner=75, index=1),
        trade(direction="LONG", outcome="LOSS", net_r=-1.0, pnl=-100, phase="D_TO_E", confluence="BULLISH", scanner=75, index=2),
        trade(direction="LONG", outcome="OPEN_END", net_r=0.5, pnl=50, phase="D_TO_E", confluence="BULLISH", scanner=75, index=3),
    ]
    analytics = analyze_backtest(result(trades), config=AnalyticsConfig(min_sample_size=3))
    segment = analytics.by_direction[0]
    assert segment.total_trades == 3
    assert segment.resolved_trades == 2
    assert segment.open_end == 1
    assert segment.win_rate_pct == 50.0
    assert segment.expectancy_r == 0.1667


def test_invalid_backtest_is_rejected() -> None:
    analytics = analyze_backtest(result([], errors=["REPLAY_INVALID"]))
    assert analytics.errors == ["BACKTEST_INVALID"]
    assert analytics.by_direction == []


def test_invalid_min_sample_size_is_rejected() -> None:
    analytics = analyze_backtest(result(sample_trades()), config=AnalyticsConfig(min_sample_size=0))
    assert "INVALID_MIN_SAMPLE_SIZE" in analytics.errors
