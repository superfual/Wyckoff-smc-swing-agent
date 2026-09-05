"""
Backtest Performance Analytics
Wyckoff + SMC Spot Swing Agent

Turns simulated trades into explainable research segments so we can identify
where the strategy's edge appears to come from. This module does not optimize
parameters automatically and does not use future information beyond the
already-completed backtest results.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf
from typing import Callable

try:
    from .backtest import BacktestResult, SimulatedTrade
except ImportError:  # Allows: python src/analytics.py
    from backtest import BacktestResult, SimulatedTrade


@dataclass(frozen=True)
class AnalyticsConfig:
    min_sample_size: int = 3


@dataclass
class SegmentMetrics:
    dimension: str
    segment: str
    total_trades: int
    resolved_trades: int
    wins: int
    losses: int
    open_end: int
    win_rate_pct: float
    expectancy_r: float
    average_win_r: float | None
    average_loss_r: float | None
    total_net_pnl: float
    profit_factor: float | None
    sample_status: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PerformanceAnalytics:
    symbol: str
    total_trades: int
    by_direction: list[SegmentMetrics]
    by_wyckoff_phase: list[SegmentMetrics]
    by_confluence: list[SegmentMetrics]
    by_scanner_bucket: list[SegmentMetrics]
    strongest_segments: list[SegmentMetrics]
    weakest_segments: list[SegmentMetrics]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def scanner_score_bucket(score: float) -> str:
    if score >= 80:
        return "80_PLUS"
    if score >= 70:
        return "70_TO_79"
    if score >= 60:
        return "60_TO_69"
    return "BELOW_60"


def _segment_metrics(
    dimension: str,
    segment: str,
    trades: list[SimulatedTrade],
    min_sample_size: int,
) -> SegmentMetrics:
    wins = [trade for trade in trades if trade.outcome == "WIN"]
    losses = [trade for trade in trades if trade.outcome == "LOSS"]
    open_end = [trade for trade in trades if trade.outcome == "OPEN_END"]
    resolved = wins + losses

    win_rate = len(wins) / len(resolved) * 100 if resolved else 0.0
    expectancy = sum(trade.net_r for trade in trades) / len(trades) if trades else 0.0
    avg_win = sum(trade.net_r for trade in wins) / len(wins) if wins else None
    avg_loss = sum(trade.net_r for trade in losses) / len(losses) if losses else None
    gross_profit = sum(max(trade.net_pnl_quote, 0.0) for trade in trades)
    gross_loss = abs(sum(min(trade.net_pnl_quote, 0.0) for trade in trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (inf if gross_profit > 0 else None)

    if len(trades) < min_sample_size:
        sample_status = "INSUFFICIENT_SAMPLE"
    elif expectancy > 0:
        sample_status = "POSITIVE_EDGE"
    elif expectancy < 0:
        sample_status = "NEGATIVE_EDGE"
    else:
        sample_status = "FLAT"

    return SegmentMetrics(
        dimension=dimension,
        segment=segment,
        total_trades=len(trades),
        resolved_trades=len(resolved),
        wins=len(wins),
        losses=len(losses),
        open_end=len(open_end),
        win_rate_pct=round(win_rate, 4),
        expectancy_r=round(expectancy, 4),
        average_win_r=None if avg_win is None else round(avg_win, 4),
        average_loss_r=None if avg_loss is None else round(avg_loss, 4),
        total_net_pnl=round(sum(trade.net_pnl_quote for trade in trades), 8),
        profit_factor=None if profit_factor is None else (profit_factor if profit_factor == inf else round(profit_factor, 4)),
        sample_status=sample_status,
    )


def _group(
    trades: list[SimulatedTrade],
    dimension: str,
    key_fn: Callable[[SimulatedTrade], str],
    min_sample_size: int,
) -> list[SegmentMetrics]:
    grouped: dict[str, list[SimulatedTrade]] = {}
    for trade in trades:
        key = key_fn(trade)
        grouped.setdefault(key, []).append(trade)

    metrics = [
        _segment_metrics(dimension, key, values, min_sample_size)
        for key, values in grouped.items()
    ]
    return sorted(metrics, key=lambda item: (-item.total_trades, item.segment))


def _rankable(segments: list[SegmentMetrics]) -> list[SegmentMetrics]:
    return [segment for segment in segments if segment.sample_status != "INSUFFICIENT_SAMPLE"]


def analyze_backtest(
    backtest: BacktestResult,
    *,
    config: AnalyticsConfig | None = None,
) -> PerformanceAnalytics:
    """Break down a completed backtest by major strategy dimensions."""

    cfg = config or AnalyticsConfig()
    errors: list[str] = []
    if cfg.min_sample_size < 1:
        errors.append("INVALID_MIN_SAMPLE_SIZE")
    if backtest.errors:
        errors.append("BACKTEST_INVALID")

    if errors:
        return PerformanceAnalytics(
            symbol=backtest.symbol,
            total_trades=backtest.total_trades,
            by_direction=[],
            by_wyckoff_phase=[],
            by_confluence=[],
            by_scanner_bucket=[],
            strongest_segments=[],
            weakest_segments=[],
            interpretation="Performance analytics cannot be trusted because its inputs are invalid.",
            errors=errors,
        )

    trades = backtest.trades
    by_direction = _group(trades, "DIRECTION", lambda trade: trade.direction, cfg.min_sample_size)
    by_phase = _group(
        trades,
        "WYCKOFF_PHASE",
        lambda trade: trade.wyckoff_phase or "UNKNOWN",
        cfg.min_sample_size,
    )
    by_confluence = _group(
        trades,
        "CONFLUENCE",
        lambda trade: trade.confluence_classification or "UNKNOWN",
        cfg.min_sample_size,
    )
    by_scanner = _group(
        trades,
        "SCANNER_SCORE",
        lambda trade: scanner_score_bucket(trade.scanner_score),
        cfg.min_sample_size,
    )

    all_segments = by_direction + by_phase + by_confluence + by_scanner
    rankable = _rankable(all_segments)
    strongest = sorted(rankable, key=lambda item: (item.expectancy_r, item.total_trades), reverse=True)[:5]
    weakest = sorted(rankable, key=lambda item: (item.expectancy_r, -item.total_trades))[:5]

    if not trades:
        interpretation = "No simulated trades are available, so the source of strategy edge cannot be evaluated yet."
    elif not rankable:
        interpretation = (
            "Trades exist, but every segment is below the minimum sample threshold. "
            "Collect more replay history before drawing conclusions about edge."
        )
    else:
        best = strongest[0]
        worst = weakest[0]
        interpretation = (
            f"Best sufficiently-sampled segment: {best.dimension}/{best.segment} "
            f"at {best.expectancy_r:+.2f}R expectancy. "
            f"Weakest sufficiently-sampled segment: {worst.dimension}/{worst.segment} "
            f"at {worst.expectancy_r:+.2f}R. Treat these as research evidence, not automatic optimization rules."
        )

    return PerformanceAnalytics(
        symbol=backtest.symbol,
        total_trades=backtest.total_trades,
        by_direction=by_direction,
        by_wyckoff_phase=by_phase,
        by_confluence=by_confluence,
        by_scanner_bucket=by_scanner,
        strongest_segments=strongest,
        weakest_segments=weakest,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Backtest performance analytics ready.")
