"""
Trade Thesis Engine
Wyckoff + SMC Spot Swing Agent

Transforms confluence + SMC evidence into an actionable but non-executing
trade thesis. The engine never places trades. It decides whether a setup is
WAIT, WATCH or READY and explains entry zone, invalidation, objectives and
blockers in deterministic terms.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .confluence import ConfluenceAnalysis
    from .smc import FairValueGap, OrderBlock, SMCAnalysis
    from .wyckoff import WyckoffAnalysis
except ImportError:  # Allows: python src/thesis.py
    from confluence import ConfluenceAnalysis
    from smc import FairValueGap, OrderBlock, SMCAnalysis
    from wyckoff import WyckoffAnalysis


ThesisState = Literal["WAIT", "WATCH", "READY"]
ThesisDirection = Literal["LONG", "SHORT", "NEUTRAL", "UNKNOWN"]


@dataclass(frozen=True)
class PriceZone:
    lower: float
    upper: float
    midpoint: float
    source: str


@dataclass
class TradeThesis:
    symbol: str
    state: ThesisState
    direction: ThesisDirection
    confidence: float
    entry_zone: PriceZone | None
    invalidation_level: float | None
    target_level: float | None
    target_reason: str | None
    trigger: str | None
    blockers: list[str]
    rationale: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _direction_from_confluence(confluence: ConfluenceAnalysis) -> ThesisDirection:
    if confluence.bias == "BULLISH":
        return "LONG"
    if confluence.bias == "BEARISH":
        return "SHORT"
    if confluence.bias == "NEUTRAL":
        return "NEUTRAL"
    return "UNKNOWN"


def _active_blocks(smc: SMCAnalysis, direction: str) -> list[OrderBlock]:
    return [b for b in smc.order_blocks if b.direction == direction and b.status != "INVALIDATED"]


def _active_gaps(smc: SMCAnalysis, direction: str) -> list[FairValueGap]:
    return [g for g in smc.fair_value_gaps if g.direction == direction and g.status != "MITIGATED"]


def _preferred_zone(smc: SMCAnalysis, direction: str) -> PriceZone | None:
    blocks = _active_blocks(smc, direction)
    gaps = _active_gaps(smc, direction)

    if blocks and gaps:
        block = blocks[-1]
        gap = gaps[-1]
        overlap_low = max(block.lower, gap.lower)
        overlap_high = min(block.upper, gap.upper)
        if overlap_low < overlap_high:
            return PriceZone(round(overlap_low, 8), round(overlap_high, 8), round((overlap_low + overlap_high) / 2, 8), "OB_FVG_OVERLAP")

    if blocks:
        block = blocks[-1]
        return PriceZone(block.lower, block.upper, block.midpoint, block.kind)
    if gaps:
        gap = gaps[-1]
        return PriceZone(gap.lower, gap.upper, gap.midpoint, gap.kind)
    return None


def _invalidation(smc: SMCAnalysis, direction: str, zone: PriceZone | None) -> float | None:
    if direction == "BULLISH":
        blocks = _active_blocks(smc, "BULLISH")
        if blocks:
            return blocks[-1].lower
        if smc.latest_swing_low:
            return smc.latest_swing_low.price
        return zone.lower if zone else None
    if direction == "BEARISH":
        blocks = _active_blocks(smc, "BEARISH")
        if blocks:
            return blocks[-1].upper
        if smc.latest_swing_high:
            return smc.latest_swing_high.price
        return zone.upper if zone else None
    return None


def _target(wyckoff: WyckoffAnalysis, smc: SMCAnalysis, direction: str) -> tuple[float | None, str | None]:
    if direction == "BULLISH":
        buy_side = [p for p in smc.liquidity_pools if p.side == "BUY_SIDE"]
        if buy_side:
            return buy_side[-1].level, "Nearest buy-side liquidity pool"
        if wyckoff.trading_range:
            return wyckoff.trading_range.resistance, "Wyckoff trading-range resistance"
        if smc.latest_swing_high:
            return smc.latest_swing_high.price, "Latest confirmed swing high"
    elif direction == "BEARISH":
        sell_side = [p for p in smc.liquidity_pools if p.side == "SELL_SIDE"]
        if sell_side:
            return sell_side[-1].level, "Nearest sell-side liquidity pool"
        if wyckoff.trading_range:
            return wyckoff.trading_range.support, "Wyckoff trading-range support"
        if smc.latest_swing_low:
            return smc.latest_swing_low.price, "Latest confirmed swing low"
    return None, None


def build_trade_thesis(
    confluence: ConfluenceAnalysis,
    wyckoff: WyckoffAnalysis,
    smc: SMCAnalysis,
) -> TradeThesis:
    """Build a deterministic, non-executing trade thesis from engine outputs."""

    symbol = confluence.symbol or wyckoff.symbol or smc.symbol
    errors: list[str] = []
    if confluence.errors:
        errors.append("CONFLUENCE_INVALID")
    if wyckoff.errors or wyckoff.phase == "INVALID_DATA":
        errors.append("WYCKOFF_INVALID")
    if smc.errors or smc.trend_state == "INVALID_DATA":
        errors.append("SMC_INVALID")
    if len({s for s in [confluence.symbol, wyckoff.symbol, smc.symbol] if s}) > 1:
        errors.append("SYMBOL_MISMATCH")

    if errors:
        return TradeThesis(
            symbol=symbol,
            state="WAIT",
            direction="UNKNOWN",
            confidence=0.0,
            entry_zone=None,
            invalidation_level=None,
            target_level=None,
            target_reason=None,
            trigger=None,
            blockers=["Required upstream analysis is invalid or mismatched."],
            rationale=[],
            interpretation="Trade thesis cannot be formed from invalid upstream outputs.",
            errors=errors,
        )

    direction = _direction_from_confluence(confluence)
    smc_direction = "BULLISH" if direction == "LONG" else "BEARISH" if direction == "SHORT" else None
    blockers: list[str] = []
    rationale: list[str] = []

    if direction in {"NEUTRAL", "UNKNOWN"}:
        blockers.append("Confluence does not have a clear directional edge.")
    if confluence.contradictions:
        blockers.extend(confluence.contradictions)

    zone = _preferred_zone(smc, smc_direction) if smc_direction else None
    if smc_direction and zone is None:
        blockers.append("No active FVG or order block is available as a structured entry zone.")

    latest_event = smc.events[-1] if smc.events else None
    has_structure_trigger = bool(latest_event and latest_event.direction == smc_direction)
    if smc_direction and not has_structure_trigger:
        blockers.append("No latest BOS/CHoCH confirms the confluence direction.")

    supporting_sweep = any(s.direction == smc_direction for s in smc.liquidity_sweeps[-2:]) if smc_direction else False
    if supporting_sweep:
        rationale.append("Recent liquidity sweep rejects in the thesis direction.")

    if latest_event and latest_event.direction == smc_direction:
        rationale.append(f"Latest SMC trigger is {latest_event.direction.lower()} {latest_event.kind}.")

    if zone:
        rationale.append(f"Preferred retracement zone comes from {zone.source}.")

    if wyckoff.bias == "ACCUMULATION" and direction == "LONG":
        rationale.append(f"Wyckoff supports accumulation in phase {wyckoff.phase}.")
    elif wyckoff.bias == "DISTRIBUTION" and direction == "SHORT":
        rationale.append(f"Wyckoff supports distribution in phase {wyckoff.phase}.")

    high_conviction = confluence.classification in {"HIGH_CONVICTION_BULLISH", "HIGH_CONVICTION_BEARISH"}
    directional = confluence.classification in {"BULLISH", "BEARISH", "HIGH_CONVICTION_BULLISH", "HIGH_CONVICTION_BEARISH"}

    if not directional or direction in {"NEUTRAL", "UNKNOWN"}:
        state: ThesisState = "WAIT"
    elif blockers:
        state = "WATCH"
    elif high_conviction and zone and has_structure_trigger:
        state = "READY"
    else:
        state = "WATCH"

    invalidation = _invalidation(smc, smc_direction, zone) if smc_direction else None
    target_level, target_reason = _target(wyckoff, smc, smc_direction) if smc_direction else (None, None)

    trigger = None
    if state == "READY" and latest_event:
        trigger = f"Wait for retracement into {zone.source} while {latest_event.kind} structure remains valid."
    elif state == "WATCH" and smc_direction:
        trigger = "Wait for missing structure/zone confirmation before considering execution."

    confidence = confluence.confidence
    if state == "WATCH":
        confidence = min(confidence, 74.0)
    elif state == "WAIT":
        confidence = min(confidence, 50.0)

    if state == "READY":
        interpretation = "Confluence, structure and a defined retracement zone align; setup is ready for risk evaluation, not automatic execution."
    elif state == "WATCH":
        interpretation = "Directional thesis exists, but one or more execution conditions remain incomplete."
    else:
        interpretation = "No actionable trade thesis should be prepared until directional evidence improves."

    return TradeThesis(
        symbol=symbol,
        state=state,
        direction=direction,
        confidence=round(confidence, 1),
        entry_zone=zone,
        invalidation_level=round(invalidation, 8) if invalidation is not None else None,
        target_level=round(target_level, 8) if target_level is not None else None,
        target_reason=target_reason,
        trigger=trigger,
        blockers=blockers,
        rationale=rationale,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Trade thesis engine ready.")
