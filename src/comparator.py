"""
Research vs Paper Performance Comparator
Wyckoff + SMC Spot Swing Agent

Compares historical research expectations with live-time paper performance.
The comparator is deliberately conservative: unavailable metrics are reported
as unavailable rather than inferred from incompatible denominators.

No strategy parameters are changed by this module and no exchange orders are
sent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf, isinf
from typing import Literal

try:
    from .backtest import BacktestResult
    from .paper_session import PaperSessionSummary
    from .walk_forward import WalkForwardResult
except ImportError:
    from backtest import BacktestResult
    from paper_session import PaperSessionSummary
    from walk_forward import WalkForwardResult

ComparatorVerdict = Literal["ALIGNED", "DEGRADED", "DIVERGED", "INSUFFICIENT_DATA"]
MetricStatus = Literal["ALIGNED", "DEGRADED", "DIVERGED", "UNAVAILABLE"]


@dataclass(frozen=True)
class ComparatorConfig:
    min_paper_trades: int = 10
    max_expectancy_degradation_pct: float = 35.0
    max_win_rate_drop_pct_points: float = 10.0
    min_profit_factor_retention_pct: float = 65.0
    max_drawdown_multiplier: float = 1.50
    max_trade_frequency_drift_pct: float = 40.0
    max_degraded_metrics_for_aligned: int = 1


@dataclass(frozen=True)
class TradeFrequencyEvidence:
    research_trades: int
    research_decisions: int
    paper_trades: int
    paper_decisions: int


@dataclass
class MetricComparison:
    metric: str
    research_value: float | None
    paper_value: float | None
    drift_value: float | None
    status: MetricStatus
    note: str


@dataclass
class ResearchPaperComparison:
    symbol_scope: str
    research_source: str
    paper_trades: int
    comparisons: list[MetricComparison]
    aligned_metrics: int
    degraded_metrics: int
    diverged_metrics: int
    unavailable_metrics: int
    verdict: ComparatorVerdict
    promotion_allowed: bool
    reasons: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _safe_pf(value: float | None) -> float | None:
    if value is None:
        return None
    if isinf(value):
        return inf
    return float(value)


def _historical_expectancy(backtest: BacktestResult, walk_forward: WalkForwardResult | None) -> tuple[float, str]:
    if walk_forward is not None and not walk_forward.errors and walk_forward.verdict != "INSUFFICIENT_DATA":
        return walk_forward.average_validation_expectancy_r, "WALK_FORWARD_VALIDATION"
    return backtest.expectancy_r, "BACKTEST"


def _compare_expectancy(research: float, paper: float, cfg: ComparatorConfig) -> MetricComparison:
    if research <= 0:
        return MetricComparison("expectancy_r", research, paper, None, "UNAVAILABLE", "Historical expectancy is non-positive; there is no positive edge baseline to retain.")
    retention = paper / research * 100
    degradation = max(0.0, 100.0 - retention)
    if paper <= 0:
        status: MetricStatus = "DIVERGED"
    elif degradation <= cfg.max_expectancy_degradation_pct:
        status = "ALIGNED"
    else:
        status = "DEGRADED"
    return MetricComparison("expectancy_r", research, paper, round(degradation, 4), status, f"Paper retains {retention:.1f}% of historical expectancy.")


def _compare_win_rate(research: float, paper: float, cfg: ComparatorConfig) -> MetricComparison:
    drop = research - paper
    if drop <= cfg.max_win_rate_drop_pct_points:
        status: MetricStatus = "ALIGNED"
    elif paper < research * 0.70:
        status = "DIVERGED"
    else:
        status = "DEGRADED"
    return MetricComparison("win_rate_pct", research, paper, round(drop, 4), status, f"Paper win rate differs by {drop:.1f} percentage points versus research.")


def _compare_profit_factor(research: float | None, paper: float | None, cfg: ComparatorConfig) -> MetricComparison:
    research = _safe_pf(research)
    paper = _safe_pf(paper)
    if research is None or paper is None or research <= 0 or research == inf:
        if research == inf and paper == inf:
            return MetricComparison("profit_factor", research, paper, 100.0, "ALIGNED", "Both research and paper have no realized gross losses.")
        return MetricComparison("profit_factor", research, paper, None, "UNAVAILABLE", "Profit factor cannot be compared reliably from the available samples.")
    retention = paper / research * 100
    if retention >= cfg.min_profit_factor_retention_pct:
        status: MetricStatus = "ALIGNED"
    elif paper < 1.0:
        status = "DIVERGED"
    else:
        status = "DEGRADED"
    return MetricComparison("profit_factor", research, paper, round(retention, 4), status, f"Paper retains {retention:.1f}% of historical profit factor.")


def _compare_drawdown(research: float, paper: float, cfg: ComparatorConfig) -> MetricComparison:
    # Zero historical drawdown cannot safely define a multiplicative baseline.
    if research <= 0:
        status: MetricStatus = "ALIGNED" if paper <= 1.0 else "UNAVAILABLE"
        return MetricComparison("max_drawdown_pct", research, paper, None, status, "Historical drawdown is too small for a stable multiplicative comparison.")
    multiplier = paper / research
    if multiplier <= cfg.max_drawdown_multiplier:
        status = "ALIGNED"
    elif multiplier > cfg.max_drawdown_multiplier * 1.5:
        status = "DIVERGED"
    else:
        status = "DEGRADED"
    return MetricComparison("max_drawdown_pct", research, paper, round(multiplier, 4), status, f"Paper drawdown is {multiplier:.2f}x the historical baseline.")


def _compare_trade_frequency(evidence: TradeFrequencyEvidence | None, cfg: ComparatorConfig) -> MetricComparison:
    if evidence is None or evidence.research_decisions <= 0 or evidence.paper_decisions <= 0:
        return MetricComparison("trade_frequency_pct", None, None, None, "UNAVAILABLE", "A compatible decision denominator was not provided; trade frequency is not inferred.")
    research_rate = evidence.research_trades / evidence.research_decisions * 100
    paper_rate = evidence.paper_trades / evidence.paper_decisions * 100
    if research_rate <= 0:
        return MetricComparison("trade_frequency_pct", research_rate, paper_rate, None, "UNAVAILABLE", "Historical trade frequency is zero.")
    drift = abs(paper_rate - research_rate) / research_rate * 100
    if drift <= cfg.max_trade_frequency_drift_pct:
        status: MetricStatus = "ALIGNED"
    elif drift > cfg.max_trade_frequency_drift_pct * 2:
        status = "DIVERGED"
    else:
        status = "DEGRADED"
    return MetricComparison("trade_frequency_pct", round(research_rate, 4), round(paper_rate, 4), round(drift, 4), status, f"Paper trade frequency differs by {drift:.1f}% from research.")


def compare_research_to_paper(
    backtest: BacktestResult,
    paper: PaperSessionSummary,
    *,
    walk_forward: WalkForwardResult | None = None,
    frequency_evidence: TradeFrequencyEvidence | None = None,
    config: ComparatorConfig | None = None,
    symbol_scope: str = "PORTFOLIO",
) -> ResearchPaperComparison:
    """Compare paper evidence with historical expectations without optimization."""
    cfg = config or ComparatorConfig()
    errors: list[str] = []
    if cfg.min_paper_trades < 1 or cfg.max_expectancy_degradation_pct < 0:
        errors.append("INVALID_COMPARATOR_CONFIG")
    if cfg.max_win_rate_drop_pct_points < 0 or cfg.min_profit_factor_retention_pct <= 0:
        errors.append("INVALID_COMPARATOR_CONFIG")
    if cfg.max_drawdown_multiplier <= 0 or cfg.max_trade_frequency_drift_pct < 0:
        errors.append("INVALID_COMPARATOR_CONFIG")
    if backtest.errors or paper.errors:
        errors.append("INVALID_SOURCE_RESULT")
    if walk_forward is not None and walk_forward.errors:
        errors.append("INVALID_WALK_FORWARD_RESULT")

    historical_expectancy, research_source = _historical_expectancy(backtest, walk_forward)

    if errors or paper.total_trades < cfg.min_paper_trades:
        reasons = list(errors)
        if paper.total_trades < cfg.min_paper_trades:
            reasons.append(f"Paper sample has {paper.total_trades} trades; minimum is {cfg.min_paper_trades}.")
        return ResearchPaperComparison(
            symbol_scope, research_source, paper.total_trades, [], 0, 0, 0, 0,
            "INSUFFICIENT_DATA", False, reasons,
            "Paper evidence is not yet sufficient for a promotion decision.", errors,
        )

    comparisons = [
        _compare_expectancy(historical_expectancy, paper.expectancy_r, cfg),
        _compare_win_rate(backtest.win_rate_pct, paper.win_rate_pct, cfg),
        _compare_profit_factor(backtest.profit_factor, paper.profit_factor, cfg),
        _compare_drawdown(backtest.max_drawdown_pct, paper.max_drawdown_pct, cfg),
        _compare_trade_frequency(frequency_evidence, cfg),
    ]

    aligned = sum(item.status == "ALIGNED" for item in comparisons)
    degraded = sum(item.status == "DEGRADED" for item in comparisons)
    diverged = sum(item.status == "DIVERGED" for item in comparisons)
    unavailable = sum(item.status == "UNAVAILABLE" for item in comparisons)

    reasons: list[str] = []
    if diverged > 0 or paper.expectancy_r <= 0:
        verdict: ComparatorVerdict = "DIVERGED"
        reasons.append("At least one core paper metric materially diverges from research expectations.")
    elif degraded > cfg.max_degraded_metrics_for_aligned:
        verdict = "DEGRADED"
        reasons.append("Paper performance remains positive but multiple metrics have weakened beyond alignment limits.")
    else:
        verdict = "ALIGNED"
        reasons.append("Paper performance remains within configured drift limits for the available comparable metrics.")

    promotion_allowed = verdict == "ALIGNED" and paper.expectancy_r > 0
    interpretation = {
        "ALIGNED": "Paper behavior is broadly consistent with historical expectations. This comparator gate passes, but it does not by itself authorize live capital.",
        "DEGRADED": "Paper behavior is still viable but has weakened enough that promotion should remain blocked pending more evidence.",
        "DIVERGED": "Paper behavior materially disagrees with historical expectations; promotion must remain blocked.",
        "INSUFFICIENT_DATA": "Paper evidence is too limited for a trustworthy research-vs-paper comparison.",
    }[verdict]

    return ResearchPaperComparison(
        symbol_scope=symbol_scope,
        research_source=research_source,
        paper_trades=paper.total_trades,
        comparisons=comparisons,
        aligned_metrics=aligned,
        degraded_metrics=degraded,
        diverged_metrics=diverged,
        unavailable_metrics=unavailable,
        verdict=verdict,
        promotion_allowed=promotion_allowed,
        reasons=reasons,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Research vs paper comparator ready.")
