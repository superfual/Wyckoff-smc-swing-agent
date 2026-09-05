"""
Promotion Policy / System Readiness Gate
Wyckoff + SMC Spot Swing Agent

Aggregates independent research, walk-forward, paper and safety evidence into a
single system-level readiness state. This module never places orders and cannot
override lower-level safety blockers.

A critical Spot-first rule is explicit: upstream short execution must be
hardened before any tiny-live readiness can be granted. Paper-layer suppression
alone is not sufficient evidence for live readiness.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

try:
    from .comparator import ResearchPaperComparison
    from .paper_session import PaperSessionSummary
    from .validation import OOSValidationResult
    from .walk_forward import WalkForwardResult
except ImportError:
    from comparator import ResearchPaperComparison
    from paper_session import PaperSessionSummary
    from validation import OOSValidationResult
    from walk_forward import WalkForwardResult

ReadinessState = Literal[
    "RESEARCH_ONLY",
    "PAPER_ONLY",
    "READY_FOR_TINY_LIVE",
    "LIVE_BLOCKED",
]


@dataclass(frozen=True)
class ReadinessConfig:
    min_paper_trades: int = 20
    min_paper_expectancy_r: float = 0.0
    max_paper_drawdown_pct: float = 12.0
    require_oos_robust: bool = True
    require_walk_forward_robust: bool = True
    require_comparator_aligned: bool = True


@dataclass(frozen=True)
class SafetyEvidence:
    spot_short_execution_blocked_upstream: bool = False
    no_live_exchange_orders_enabled: bool = True
    unresolved_critical_errors: tuple[str, ...] = ()


@dataclass
class ReadinessCheck:
    code: str
    passed: bool
    critical: bool
    note: str


@dataclass
class SystemReadiness:
    state: ReadinessState
    promotion_allowed: bool
    checks: list[ReadinessCheck]
    passed_checks: int
    failed_checks: int
    critical_failures: int
    blockers: list[str]
    reasons: list[str]
    interpretation: str
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def _check(code: str, passed: bool, critical: bool, note: str) -> ReadinessCheck:
    return ReadinessCheck(code=code, passed=passed, critical=critical, note=note)


def evaluate_system_readiness(
    oos: OOSValidationResult,
    walk_forward: WalkForwardResult,
    paper: PaperSessionSummary,
    comparator: ResearchPaperComparison,
    *,
    safety: SafetyEvidence | None = None,
    config: ReadinessConfig | None = None,
) -> SystemReadiness:
    """Return the highest risk tier justified by the supplied evidence."""

    cfg = config or ReadinessConfig()
    safety_evidence = safety or SafetyEvidence()
    errors: list[str] = []
    if cfg.min_paper_trades < 1 or cfg.max_paper_drawdown_pct <= 0:
        errors.append("INVALID_READINESS_CONFIG")
    if oos.errors:
        errors.append("INVALID_OOS_RESULT")
    if walk_forward.errors:
        errors.append("INVALID_WALK_FORWARD_RESULT")
    if paper.errors:
        errors.append("INVALID_PAPER_RESULT")
    if comparator.errors:
        errors.append("INVALID_COMPARATOR_RESULT")

    checks: list[ReadinessCheck] = []
    checks.append(_check(
        "OOS_ROBUST",
        oos.verdict == "ROBUST" if cfg.require_oos_robust else oos.verdict in {"ROBUST", "DEGRADED"},
        True,
        f"Out-of-sample verdict is {oos.verdict}.",
    ))
    checks.append(_check(
        "WALK_FORWARD_ROBUST",
        walk_forward.verdict == "ROBUST" if cfg.require_walk_forward_robust else walk_forward.verdict in {"ROBUST", "MIXED"},
        True,
        f"Walk-forward verdict is {walk_forward.verdict}.",
    ))
    checks.append(_check(
        "PAPER_SAMPLE_SUFFICIENT",
        paper.total_trades >= cfg.min_paper_trades,
        False,
        f"Paper sample has {paper.total_trades} trades; minimum is {cfg.min_paper_trades}.",
    ))
    checks.append(_check(
        "PAPER_EXPECTANCY_POSITIVE",
        paper.expectancy_r > cfg.min_paper_expectancy_r,
        True,
        f"Paper expectancy is {paper.expectancy_r:.4f}R.",
    ))
    checks.append(_check(
        "PAPER_DRAWDOWN_WITHIN_LIMIT",
        paper.max_drawdown_pct <= cfg.max_paper_drawdown_pct,
        True,
        f"Paper max drawdown is {paper.max_drawdown_pct:.2f}% versus {cfg.max_paper_drawdown_pct:.2f}% limit.",
    ))
    checks.append(_check(
        "COMPARATOR_ALIGNED",
        comparator.verdict == "ALIGNED" and comparator.promotion_allowed if cfg.require_comparator_aligned else comparator.verdict in {"ALIGNED", "DEGRADED"},
        True,
        f"Research-vs-paper comparator verdict is {comparator.verdict}.",
    ))
    checks.append(_check(
        "SPOT_SHORT_BLOCKED_UPSTREAM",
        safety_evidence.spot_short_execution_blocked_upstream,
        True,
        "Spot mode must prevent short execution upstream, not only suppress it in the paper layer.",
    ))
    checks.append(_check(
        "LIVE_ORDERS_DISABLED_DURING_PROMOTION",
        safety_evidence.no_live_exchange_orders_enabled,
        True,
        "Live exchange order placement must remain disabled while readiness is being evaluated.",
    ))
    checks.append(_check(
        "NO_CRITICAL_ERRORS",
        not safety_evidence.unresolved_critical_errors and not errors,
        True,
        "No unresolved critical implementation or source-result errors may remain.",
    ))

    failed = [item for item in checks if not item.passed]
    critical_failed = [item for item in failed if item.critical]
    blockers = [item.code for item in failed]
    reasons = [item.note for item in failed]

    research_passed = checks[0].passed and checks[1].passed
    paper_evidence_exists = paper.total_trades > 0 or paper.total_decisions > 0
    paper_passed = checks[2].passed and checks[3].passed and checks[4].passed and checks[5].passed
    safety_passed = checks[6].passed and checks[7].passed and checks[8].passed

    if errors or safety_evidence.unresolved_critical_errors:
        state: ReadinessState = "LIVE_BLOCKED"
    elif research_passed and paper_passed and safety_passed:
        state = "READY_FOR_TINY_LIVE"
    elif research_passed and paper_evidence_exists:
        state = "PAPER_ONLY"
    elif critical_failed and paper_evidence_exists:
        state = "PAPER_ONLY"
    else:
        state = "RESEARCH_ONLY"

    promotion_allowed = state == "READY_FOR_TINY_LIVE" and not critical_failed
    interpretation = {
        "READY_FOR_TINY_LIVE": "All configured research, paper and safety gates pass. The system may be considered for a separately controlled tiny-live stage; this result does not place or authorize orders by itself.",
        "PAPER_ONLY": "The system has enough evidence to continue paper validation, but one or more live-readiness gates remain unresolved.",
        "RESEARCH_ONLY": "Research evidence is incomplete or insufficient for promotion into a trusted paper-validation stage.",
        "LIVE_BLOCKED": "A critical source, configuration or implementation error explicitly blocks live promotion.",
    }[state]

    return SystemReadiness(
        state=state,
        promotion_allowed=promotion_allowed,
        checks=checks,
        passed_checks=sum(item.passed for item in checks),
        failed_checks=len(failed),
        critical_failures=len(critical_failed),
        blockers=blockers,
        reasons=reasons,
        interpretation=interpretation,
        errors=errors,
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("System readiness gate ready; no exchange orders are sent.")
