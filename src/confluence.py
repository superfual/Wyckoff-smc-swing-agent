"""
Wyckoff + SMC Confluence Engine

Combines already-computed Wyckoff and SMC evidence into an explainable,
deterministic thesis score. This module does not fetch market data and does
not create trade entries. It evaluates agreement, contradiction and evidence
quality so later thesis/risk layers can decide what deserves attention.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .smc import SMCAnalysis
    from .wyckoff import WyckoffAnalysis
except ImportError:  # Allows: python src/confluence.py
    from smc import SMCAnalysis
    from wyckoff import WyckoffAnalysis


ConfluenceBias = Literal["BULLISH", "BEARISH", "NEUTRAL", "UNKNOWN"]
ConfluenceClass = Literal[
    "HIGH_CONVICTION_BULLISH",
    "BULLISH",
    "HIGH_CONVICTION_BEARISH",
    "BEARISH",
    "MIXED",
    "INSUFFICIENT_DATA",
]


@dataclass(frozen=True)
class ConfluenceEvidence:
    source: str
    code: str
    direction: str
    points: float
    note: str


@dataclass
class ConfluenceAnalysis:
    symbol: str
    bias: ConfluenceBias
    classification: ConfluenceClass
    bullish_score: float
    bearish_score: float
    confidence: float
    agreement_score: float
    evidence: list[ConfluenceEvidence]
    contradictions: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _add(
    evidence: list[ConfluenceEvidence],
    source: str,
    code: str,
    direction: str,
    points: float,
    note: str,
) -> None:
    evidence.append(ConfluenceEvidence(source, code, direction, round(points, 2), note))


def _wyckoff_evidence(wyckoff: WyckoffAnalysis) -> list[ConfluenceEvidence]:
    evidence: list[ConfluenceEvidence] = []
    confidence_factor = max(0.35, min(1.0, wyckoff.confidence / 100.0))

    if wyckoff.bias == "ACCUMULATION":
        _add(evidence, "WYCKOFF", "ACCUMULATION_BIAS", "BULLISH", 18 * confidence_factor, "Wyckoff bias favors accumulation.")
    elif wyckoff.bias == "DISTRIBUTION":
        _add(evidence, "WYCKOFF", "DISTRIBUTION_BIAS", "BEARISH", 18 * confidence_factor, "Wyckoff bias favors distribution.")

    phase_bonus = {"B_TO_C": 3.0, "C_TO_D": 6.0, "D_TO_E": 9.0}.get(wyckoff.phase, 0.0)
    if phase_bonus and wyckoff.bias == "ACCUMULATION":
        _add(evidence, "WYCKOFF", f"PHASE_{wyckoff.phase}", "BULLISH", phase_bonus, "Bullish Wyckoff sequence has progressed beyond early range evidence.")
    elif phase_bonus and wyckoff.bias == "DISTRIBUTION":
        _add(evidence, "WYCKOFF", f"PHASE_{wyckoff.phase}", "BEARISH", phase_bonus, "Bearish Wyckoff sequence has progressed beyond early range evidence.")

    bullish_events = {"SPRING": 7.0, "TEST": 3.0, "SOS": 7.0, "LPS": 5.0}
    bearish_events = {"UTAD": 7.0, "UTAD_TEST": 3.0, "SOW": 7.0, "LPSY": 5.0}
    for event in wyckoff.events:
        if event.code in bullish_events:
            points = bullish_events[event.code] * max(0.5, event.confidence / 100.0)
            _add(evidence, "WYCKOFF", event.code, "BULLISH", points, event.note)
        elif event.code in bearish_events:
            points = bearish_events[event.code] * max(0.5, event.confidence / 100.0)
            _add(evidence, "WYCKOFF", event.code, "BEARISH", points, event.note)

    return evidence


def _smc_evidence(smc: SMCAnalysis) -> list[ConfluenceEvidence]:
    evidence: list[ConfluenceEvidence] = []

    if smc.events:
        latest = smc.events[-1]
        points = 14.0 if latest.kind == "CHOCH" else 11.0
        _add(evidence, "SMC", latest.kind, latest.direction, points, f"Latest confirmed structure event is {latest.direction.lower()} {latest.kind}.")
    elif smc.bias in {"BULLISH", "BEARISH"}:
        _add(evidence, "SMC", "STRUCTURE_BIAS", smc.bias, 6.0, "Confirmed swing structure favors this direction.")

    if smc.liquidity_sweeps:
        latest = smc.liquidity_sweeps[-1]
        _add(evidence, "SMC", f"{latest.side}_SWEEP", latest.direction, 10.0, "Liquidity was swept and price reclaimed back through the pool.")

    active_gaps = [gap for gap in smc.fair_value_gaps if gap.status != "MITIGATED"]
    if active_gaps:
        latest = active_gaps[-1]
        points = 7.0 if latest.status == "OPEN" else 5.0
        _add(evidence, "SMC", latest.kind, latest.direction, points, f"Active FVG is {latest.status.lower()} and supports directional displacement evidence.")

    active_blocks = [block for block in smc.order_blocks if block.status != "INVALIDATED"]
    if active_blocks:
        latest = active_blocks[-1]
        status_points = {"FRESH": 9.0, "TOUCHED": 7.0, "MITIGATED": 4.0}.get(latest.status, 0.0)
        if status_points:
            _add(evidence, "SMC", latest.kind, latest.direction, status_points, f"Order block remains {latest.status.lower()} after a confirmed structure break.")

    return evidence


def _direction_score(evidence: list[ConfluenceEvidence], direction: str) -> float:
    return sum(item.points for item in evidence if item.direction == direction)


def _contradictions(wyckoff: WyckoffAnalysis, smc: SMCAnalysis) -> list[str]:
    contradictions: list[str] = []
    wyckoff_direction = "BULLISH" if wyckoff.bias == "ACCUMULATION" else "BEARISH" if wyckoff.bias == "DISTRIBUTION" else None
    smc_direction = smc.bias if smc.bias in {"BULLISH", "BEARISH"} else None

    if wyckoff_direction and smc_direction and wyckoff_direction != smc_direction:
        contradictions.append(f"Wyckoff is {wyckoff_direction.lower()} while SMC structure is {smc_direction.lower()}.")

    if smc.liquidity_sweeps and wyckoff_direction:
        sweep_direction = smc.liquidity_sweeps[-1].direction
        if sweep_direction != wyckoff_direction:
            contradictions.append(f"Latest liquidity sweep rejects {sweep_direction.lower()}, opposite the Wyckoff directional thesis.")

    active_blocks = [block for block in smc.order_blocks if block.status != "INVALIDATED"]
    if active_blocks and wyckoff_direction and active_blocks[-1].direction != wyckoff_direction:
        contradictions.append("Latest active order block points opposite the Wyckoff thesis.")

    return contradictions


def analyze_confluence(wyckoff: WyckoffAnalysis, smc: SMCAnalysis) -> ConfluenceAnalysis:
    """Combine Wyckoff and SMC outputs into an explainable directional score."""
    symbol = wyckoff.symbol or smc.symbol
    errors: list[str] = []

    if wyckoff.symbol and smc.symbol and wyckoff.symbol != smc.symbol:
        errors.append("SYMBOL_MISMATCH")
    if wyckoff.phase == "INVALID_DATA" or wyckoff.errors:
        errors.append("WYCKOFF_DATA_INVALID")
    if smc.trend_state == "INVALID_DATA" or smc.errors:
        errors.append("SMC_DATA_INVALID")

    if errors:
        return ConfluenceAnalysis(
            symbol=symbol,
            bias="UNKNOWN",
            classification="INSUFFICIENT_DATA",
            bullish_score=0.0,
            bearish_score=0.0,
            confidence=0.0,
            agreement_score=0.0,
            evidence=[],
            contradictions=[],
            interpretation="Confluence cannot be evaluated because required engine outputs are invalid or mismatched.",
            errors=errors,
        )

    evidence = _wyckoff_evidence(wyckoff) + _smc_evidence(smc)
    bullish_score = min(100.0, _direction_score(evidence, "BULLISH"))
    bearish_score = min(100.0, _direction_score(evidence, "BEARISH"))
    contradictions = _contradictions(wyckoff, smc)

    dominant = max(bullish_score, bearish_score)
    opposing = min(bullish_score, bearish_score)
    edge = dominant - opposing
    agreement_score = 0.0 if dominant == 0 else max(0.0, min(100.0, edge / dominant * 100.0))

    if bullish_score >= bearish_score + 12:
        bias: ConfluenceBias = "BULLISH"
    elif bearish_score >= bullish_score + 12:
        bias = "BEARISH"
    else:
        bias = "NEUTRAL"

    contradiction_penalty = min(24.0, len(contradictions) * 8.0)
    confidence = min(95.0, dominant * 0.85 + edge * 0.25)
    confidence = max(0.0, confidence - contradiction_penalty)

    if bias == "BULLISH" and bullish_score >= 55 and agreement_score >= 65 and not contradictions:
        classification: ConfluenceClass = "HIGH_CONVICTION_BULLISH"
    elif bias == "BULLISH":
        classification = "BULLISH"
    elif bias == "BEARISH" and bearish_score >= 55 and agreement_score >= 65 and not contradictions:
        classification = "HIGH_CONVICTION_BEARISH"
    elif bias == "BEARISH":
        classification = "BEARISH"
    else:
        classification = "MIXED"
        confidence = min(confidence, 55.0)

    if classification == "HIGH_CONVICTION_BULLISH":
        interpretation = "Wyckoff and SMC evidence align strongly on a bullish accumulation/markup thesis."
    elif classification == "HIGH_CONVICTION_BEARISH":
        interpretation = "Wyckoff and SMC evidence align strongly on a bearish distribution/markdown thesis."
    elif classification == "BULLISH":
        interpretation = "Bullish evidence dominates, but the thesis is not yet fully aligned across all confluence layers."
    elif classification == "BEARISH":
        interpretation = "Bearish evidence dominates, but the thesis is not yet fully aligned across all confluence layers."
    else:
        interpretation = "Wyckoff and SMC evidence is mixed or lacks enough directional separation for a strong thesis."

    return ConfluenceAnalysis(
        symbol=symbol,
        bias=bias,
        classification=classification,
        bullish_score=round(bullish_score, 1),
        bearish_score=round(bearish_score, 1),
        confidence=round(confidence, 1),
        agreement_score=round(agreement_score, 1),
        evidence=evidence,
        contradictions=contradictions,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Confluence engine ready.")
