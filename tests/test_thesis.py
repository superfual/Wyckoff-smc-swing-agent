"""Unit tests for the trade thesis engine."""

from src.confluence import ConfluenceAnalysis
from src.smc import FairValueGap, LiquidityPool, OrderBlock, SMCAnalysis, StructureEvent, SwingPoint
from src.thesis import build_trade_thesis
from src.wyckoff import TradingRange, WyckoffAnalysis


def confluence(classification: str, bias: str, confidence: float = 82.0, contradictions=None, errors=None) -> ConfluenceAnalysis:
    return ConfluenceAnalysis(
        symbol="TESTUSDT",
        bias=bias,
        classification=classification,
        bullish_score=70.0 if bias == "BULLISH" else 10.0,
        bearish_score=70.0 if bias == "BEARISH" else 10.0,
        confidence=confidence,
        agreement_score=80.0,
        evidence=[],
        contradictions=contradictions or [],
        interpretation="test",
        errors=errors or [],
    )


def wyckoff(bias: str = "ACCUMULATION", phase: str = "D_TO_E") -> WyckoffAnalysis:
    return WyckoffAnalysis(
        symbol="TESTUSDT",
        bias=bias,
        phase=phase,
        confidence=80.0,
        trading_range=TradingRange(95, 110, 102.5, 14.6, 0, 20, 80, 3, 3),
        events=[],
        interpretation="test",
        errors=[],
    )


def smc_bullish(with_zone: bool = True, with_event: bool = True, contradictions: bool = False) -> SMCAnalysis:
    event = StructureEvent("CHOCH", "BULLISH", 10, 10, 108, 6, 105, "CLOSE") if with_event else None
    ob = OrderBlock("BULLISH_OB", "BULLISH", 7, 7, 100, 104, 102, "CHOCH", 10, 2.0, "FRESH", None)
    fvg = FairValueGap("BULLISH_FVG", "BULLISH", 9, 9, 102, 105, 103.5, 2.9, 2.0, "OPEN", None)
    return SMCAnalysis(
        symbol="TESTUSDT",
        timeframe="1h",
        bias="BULLISH",
        trend_state="BULLISH_TRANSITION",
        swings=[SwingPoint("LOW", 6, 6, 98, 1), SwingPoint("HIGH", 8, 8, 108, 1)],
        events=[event] if event else [],
        liquidity_pools=[LiquidityPool("EQUAL_HIGHS", "BUY_SIDE", 112, 0.25, (3, 5), 3, 5, 2)],
        liquidity_sweeps=[],
        fair_value_gaps=[fvg] if with_zone else [],
        order_blocks=[ob] if with_zone else [],
        latest_swing_high=SwingPoint("HIGH", 8, 8, 108, 1),
        latest_swing_low=SwingPoint("LOW", 6, 6, 98, 1),
        interpretation="test",
        errors=[],
    )


def smc_bearish() -> SMCAnalysis:
    event = StructureEvent("BOS", "BEARISH", 10, 10, 96, 6, 99, "CLOSE")
    ob = OrderBlock("BEARISH_OB", "BEARISH", 7, 7, 101, 105, 103, "BOS", 10, 1.8, "TOUCHED", 12)
    return SMCAnalysis(
        symbol="TESTUSDT", timeframe="1h", bias="BEARISH", trend_state="BEARISH_CONTINUATION",
        swings=[SwingPoint("HIGH", 6, 6, 106, 1), SwingPoint("LOW", 8, 8, 96, 1)],
        events=[event], liquidity_pools=[LiquidityPool("EQUAL_LOWS", "SELL_SIDE", 92, 0.25, (3, 5), 3, 5, 2)],
        liquidity_sweeps=[], fair_value_gaps=[], order_blocks=[ob],
        latest_swing_high=SwingPoint("HIGH", 6, 6, 106, 1), latest_swing_low=SwingPoint("LOW", 8, 8, 96, 1), interpretation="test", errors=[]
    )


def test_high_conviction_bullish_with_zone_and_trigger_is_ready() -> None:
    thesis = build_trade_thesis(confluence("HIGH_CONVICTION_BULLISH", "BULLISH"), wyckoff(), smc_bullish())
    assert thesis.state == "READY"
    assert thesis.direction == "LONG"
    assert thesis.entry_zone is not None
    assert thesis.entry_zone.source == "OB_FVG_OVERLAP"
    assert thesis.entry_zone.lower == 102
    assert thesis.entry_zone.upper == 104
    assert thesis.invalidation_level == 100
    assert thesis.target_level == 112
    assert thesis.blockers == []


def test_bullish_without_zone_stays_watch() -> None:
    thesis = build_trade_thesis(confluence("BULLISH", "BULLISH", 70), wyckoff(), smc_bullish(with_zone=False))
    assert thesis.state == "WATCH"
    assert thesis.direction == "LONG"
    assert any("No active FVG or order block" in blocker for blocker in thesis.blockers)


def test_bullish_without_structure_trigger_stays_watch() -> None:
    thesis = build_trade_thesis(confluence("HIGH_CONVICTION_BULLISH", "BULLISH"), wyckoff(), smc_bullish(with_event=False))
    assert thesis.state == "WATCH"
    assert any("No latest BOS/CHoCH" in blocker for blocker in thesis.blockers)


def test_mixed_confluence_waits() -> None:
    thesis = build_trade_thesis(confluence("MIXED", "NEUTRAL", 52), wyckoff("NEUTRAL", "UNCONFIRMED"), smc_bullish())
    assert thesis.state == "WAIT"
    assert thesis.direction == "NEUTRAL"
    assert thesis.entry_zone is None


def test_contradiction_prevents_ready() -> None:
    c = confluence("BULLISH", "BULLISH", 68, contradictions=["Wyckoff bullish, SMC bearish."])
    thesis = build_trade_thesis(c, wyckoff(), smc_bullish())
    assert thesis.state == "WATCH"
    assert thesis.blockers


def test_bearish_thesis_uses_sell_side_liquidity_target_and_ob_invalidation() -> None:
    thesis = build_trade_thesis(confluence("HIGH_CONVICTION_BEARISH", "BEARISH"), wyckoff("DISTRIBUTION", "D_TO_E"), smc_bearish())
    assert thesis.state == "READY"
    assert thesis.direction == "SHORT"
    assert thesis.entry_zone is not None
    assert thesis.invalidation_level == 105
    assert thesis.target_level == 92
    assert thesis.target_reason == "Nearest sell-side liquidity pool"


def test_invalid_upstream_forces_wait() -> None:
    c = confluence("INSUFFICIENT_DATA", "UNKNOWN", 0, errors=["SMC_DATA_INVALID"])
    thesis = build_trade_thesis(c, wyckoff(), smc_bullish())
    assert thesis.state == "WAIT"
    assert thesis.direction == "UNKNOWN"
    assert thesis.errors
