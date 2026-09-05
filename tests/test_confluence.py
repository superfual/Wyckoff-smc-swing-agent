"""Unit tests for the Wyckoff + SMC confluence engine."""

from src.confluence import analyze_confluence
from src.smc import (
    FairValueGap,
    LiquiditySweep,
    OrderBlock,
    SMCAnalysis,
    StructureEvent,
)
from src.wyckoff import TradingRange, WyckoffAnalysis, WyckoffEvent


def trading_range() -> TradingRange:
    return TradingRange(
        support=95.0,
        resistance=105.0,
        midpoint=100.0,
        width_pct=10.0,
        start_index=0,
        end_index=30,
        stability_score=82.0,
        support_touches=3,
        resistance_touches=3,
    )


def bullish_wyckoff() -> WyckoffAnalysis:
    return WyckoffAnalysis(
        symbol="TESTUSDT",
        bias="ACCUMULATION",
        phase="D_TO_E",
        confidence=84.0,
        trading_range=trading_range(),
        events=[
            WyckoffEvent("SPRING", 18, 93.8, 82.0, "Spring sweep below support."),
            WyckoffEvent("TEST", 20, 95.4, 76.0, "Post-spring test held."),
            WyckoffEvent("SOS", 24, 106.0, 85.0, "Sign of strength above resistance."),
            WyckoffEvent("LPS", 27, 104.8, 78.0, "Last point of support."),
        ],
        interpretation="Potential accumulation.",
        errors=[],
    )


def bearish_wyckoff() -> WyckoffAnalysis:
    return WyckoffAnalysis(
        symbol="TESTUSDT",
        bias="DISTRIBUTION",
        phase="D_TO_E",
        confidence=82.0,
        trading_range=trading_range(),
        events=[
            WyckoffEvent("UTAD", 18, 106.2, 82.0, "UTAD sweep above resistance."),
            WyckoffEvent("UTAD_TEST", 20, 104.7, 75.0, "Post-UTAD test failed."),
            WyckoffEvent("SOW", 24, 94.0, 84.0, "Sign of weakness below support."),
            WyckoffEvent("LPSY", 27, 95.2, 78.0, "Last point of supply."),
        ],
        interpretation="Potential distribution.",
        errors=[],
    )


def bullish_smc() -> SMCAnalysis:
    return SMCAnalysis(
        symbol="TESTUSDT",
        timeframe="1h",
        bias="BULLISH",
        trend_state="BULLISH_TRANSITION",
        swings=[],
        events=[StructureEvent("CHOCH", "BULLISH", 25, 25, 106.0, 20, 104.5, "CLOSE")],
        liquidity_pools=[],
        liquidity_sweeps=[
            LiquiditySweep("SELL_SIDE", "BULLISH", 18, 18, 95.0, 93.8, 95.4, 1.26, "EQUAL_LOWS", 16)
        ],
        fair_value_gaps=[
            FairValueGap("BULLISH_FVG", "BULLISH", 26, 26, 101.5, 103.0, 102.25, 1.46, 2.1, "OPEN", None)
        ],
        order_blocks=[
            OrderBlock("BULLISH_OB", "BULLISH", 22, 22, 98.0, 101.0, 99.5, "CHOCH", 25, 2.4, "FRESH", None)
        ],
        latest_swing_high=None,
        latest_swing_low=None,
        interpretation="Bullish SMC stack.",
        errors=[],
    )


def bearish_smc() -> SMCAnalysis:
    return SMCAnalysis(
        symbol="TESTUSDT",
        timeframe="1h",
        bias="BEARISH",
        trend_state="BEARISH_TRANSITION",
        swings=[],
        events=[StructureEvent("CHOCH", "BEARISH", 25, 25, 94.0, 20, 95.5, "CLOSE")],
        liquidity_pools=[],
        liquidity_sweeps=[
            LiquiditySweep("BUY_SIDE", "BEARISH", 18, 18, 105.0, 106.2, 104.7, 1.14, "EQUAL_HIGHS", 16)
        ],
        fair_value_gaps=[
            FairValueGap("BEARISH_FVG", "BEARISH", 26, 26, 97.0, 98.5, 97.75, 1.53, 2.0, "OPEN", None)
        ],
        order_blocks=[
            OrderBlock("BEARISH_OB", "BEARISH", 22, 22, 99.0, 102.0, 100.5, "CHOCH", 25, 2.3, "FRESH", None)
        ],
        latest_swing_high=None,
        latest_swing_low=None,
        interpretation="Bearish SMC stack.",
        errors=[],
    )


def test_strong_bullish_alignment_becomes_high_conviction() -> None:
    result = analyze_confluence(bullish_wyckoff(), bullish_smc())

    assert result.bias == "BULLISH"
    assert result.classification == "HIGH_CONVICTION_BULLISH"
    assert result.bullish_score >= 55
    assert result.agreement_score >= 65
    assert result.contradictions == []
    assert result.confidence >= 60


def test_strong_bearish_alignment_becomes_high_conviction() -> None:
    result = analyze_confluence(bearish_wyckoff(), bearish_smc())

    assert result.bias == "BEARISH"
    assert result.classification == "HIGH_CONVICTION_BEARISH"
    assert result.bearish_score >= 55
    assert result.contradictions == []


def test_wyckoff_smc_direction_conflict_is_explicit() -> None:
    result = analyze_confluence(bullish_wyckoff(), bearish_smc())

    assert result.contradictions
    assert any("Wyckoff" in item and "SMC" in item for item in result.contradictions)
    assert result.classification != "HIGH_CONVICTION_BULLISH"
    assert result.classification != "HIGH_CONVICTION_BEARISH"


def test_invalid_wyckoff_data_returns_insufficient_data() -> None:
    invalid = WyckoffAnalysis(
        symbol="TESTUSDT",
        bias="UNKNOWN",
        phase="INVALID_DATA",
        confidence=0.0,
        trading_range=None,
        events=[],
        interpretation="invalid",
        errors=["4H_DATA_UNAVAILABLE"],
    )

    result = analyze_confluence(invalid, bullish_smc())

    assert result.bias == "UNKNOWN"
    assert result.classification == "INSUFFICIENT_DATA"
    assert "WYCKOFF_DATA_INVALID" in result.errors


def test_symbol_mismatch_is_rejected() -> None:
    smc = bullish_smc()
    smc.symbol = "OTHERUSDT"

    result = analyze_confluence(bullish_wyckoff(), smc)

    assert result.classification == "INSUFFICIENT_DATA"
    assert "SYMBOL_MISMATCH" in result.errors


def test_neutral_sparse_evidence_stays_mixed() -> None:
    wyckoff = WyckoffAnalysis(
        symbol="TESTUSDT",
        bias="NEUTRAL",
        phase="UNCONFIRMED",
        confidence=40.0,
        trading_range=trading_range(),
        events=[],
        interpretation="mixed",
        errors=[],
    )
    smc = SMCAnalysis(
        symbol="TESTUSDT",
        timeframe="1h",
        bias="NEUTRAL",
        trend_state="RANGE_OR_TRANSITION",
        swings=[],
        events=[],
        liquidity_pools=[],
        liquidity_sweeps=[],
        fair_value_gaps=[],
        order_blocks=[],
        latest_swing_high=None,
        latest_swing_low=None,
        interpretation="mixed",
        errors=[],
    )

    result = analyze_confluence(wyckoff, smc)

    assert result.bias == "NEUTRAL"
    assert result.classification == "MIXED"
    assert result.bullish_score == 0
    assert result.bearish_score == 0


def test_same_bar_spring_and_sell_side_sweep_are_correlation_discounted() -> None:
    result = analyze_confluence(bullish_wyckoff(), bullish_smc())

    sweep = next(item for item in result.evidence if item.code == "SELL_SIDE_SWEEP")
    assert sweep.points == 4.0
    assert "Correlation discount applied" in sweep.note


def test_same_bar_utad_and_buy_side_sweep_are_correlation_discounted() -> None:
    result = analyze_confluence(bearish_wyckoff(), bearish_smc())

    sweep = next(item for item in result.evidence if item.code == "BUY_SIDE_SWEEP")
    assert sweep.points == 4.0
    assert "Correlation discount applied" in sweep.note


def test_poi_family_cap_prevents_fvg_and_order_block_from_stacking_freely() -> None:
    result = analyze_confluence(bullish_wyckoff(), bullish_smc())

    fvg = next(item for item in result.evidence if item.code == "BULLISH_FVG")
    block = next(item for item in result.evidence if item.code == "BULLISH_OB")
    assert fvg.points + block.points == 10.0
    assert block.points == 3.0
    assert "POI family cap" in block.note


def test_wyckoff_family_cap_limits_multiple_same_direction_labels() -> None:
    result = analyze_confluence(bullish_wyckoff(), bullish_smc())
    wyckoff_points = sum(item.points for item in result.evidence if item.source == "WYCKOFF" and item.direction == "BULLISH")

    assert wyckoff_points == 38.0
    assert any("WYCKOFF family cap" in item.note for item in result.evidence if item.source == "WYCKOFF")


def test_opposing_choch_is_major_contradiction_and_reduces_confidence() -> None:
    conflicting_smc = bullish_smc()
    conflicting_smc.bias = "BEARISH"
    conflicting_smc.trend_state = "BEARISH_TRANSITION"
    conflicting_smc.events = [StructureEvent("CHOCH", "BEARISH", 25, 25, 94.0, 20, 95.5, "CLOSE")]
    conflicting_smc.liquidity_sweeps = []
    conflicting_smc.fair_value_gaps = []
    conflicting_smc.order_blocks = []

    aligned = analyze_confluence(bullish_wyckoff(), bullish_smc())
    conflicted = analyze_confluence(bullish_wyckoff(), conflicting_smc)

    assert any(item.startswith("MAJOR:") for item in conflicted.contradictions)
    assert conflicted.classification != "HIGH_CONVICTION_BULLISH"
    assert conflicted.confidence < aligned.confidence
