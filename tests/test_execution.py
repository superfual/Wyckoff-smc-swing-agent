"""Unit tests for the execution guard engine."""

from src.execution import ExecutionConfig, build_execution_intent
from src.risk import RiskAssessment
from src.thesis import PriceZone, TradeThesis


def ready_long() -> TradeThesis:
    return TradeThesis(
        symbol="TESTUSDT",
        state="READY",
        direction="LONG",
        confidence=86.0,
        entry_zone=PriceZone(100.0, 104.0, 102.0, "OB_FVG_OVERLAP"),
        invalidation_level=98.0,
        target_level=112.0,
        target_reason="Buy-side liquidity",
        trigger="Wait for retracement",
        blockers=[],
        rationale=["Bullish confluence"],
        interpretation="Ready for risk evaluation.",
        errors=[],
    )


def ready_short() -> TradeThesis:
    return TradeThesis(
        symbol="TESTUSDT",
        state="READY",
        direction="SHORT",
        confidence=84.0,
        entry_zone=PriceZone(106.0, 110.0, 108.0, "BEARISH_OB"),
        invalidation_level=112.0,
        target_level=96.0,
        target_reason="Sell-side liquidity",
        trigger="Wait for retracement",
        blockers=[],
        rationale=["Bearish confluence"],
        interpretation="Ready for risk evaluation.",
        errors=[],
    )


def risk_allow(symbol: str = "TESTUSDT") -> RiskAssessment:
    return RiskAssessment(
        symbol=symbol,
        decision="ALLOW",
        account_equity=10_000.0,
        available_exposure=40.0,
        entry_price=102.0,
        stop_price=98.0,
        target_price=112.0,
        stop_distance_pct=3.92,
        reward_risk=2.5,
        risk_budget=50.0,
        position_size_quote=1_275.0,
        position_size_units=12.5,
        projected_exposure_pct=32.75,
        reasons=["Risk acceptable"],
        interpretation="Allowed",
        errors=[],
    )


def test_long_inside_entry_zone_creates_enter_intent() -> None:
    result = build_execution_intent(ready_long(), risk_allow(), current_price=102.5)
    assert result.allowed is True
    assert result.state == "READY_TO_EXECUTE"
    assert result.action == "ENTER_LONG"
    assert result.planned_entry == 102.5
    assert result.position_size_quote == 1275.0


def test_short_inside_entry_zone_creates_enter_intent() -> None:
    risk = risk_allow()
    risk.entry_price = 108.0
    risk.stop_price = 112.0
    risk.target_price = 96.0
    result = build_execution_intent(ready_short(), risk, current_price=108.5)
    assert result.allowed is True
    assert result.action == "ENTER_SHORT"
    assert result.state == "READY_TO_EXECUTE"


def test_valid_setup_waits_for_retrace_when_price_not_in_zone() -> None:
    result = build_execution_intent(ready_long(), risk_allow(), current_price=104.8)
    assert result.allowed is False
    assert result.state == "WAITING"
    assert result.action == "WAIT_RETRACE"
    assert result.blockers == []


def test_runaway_price_is_blocked_to_prevent_chasing() -> None:
    result = build_execution_intent(ready_long(), risk_allow(), current_price=107.0)
    assert result.allowed is False
    assert result.state == "BLOCKED"
    assert any("chasing is prohibited" in blocker for blocker in result.blockers)


def test_breached_invalidation_blocks_execution() -> None:
    result = build_execution_intent(ready_long(), risk_allow(), current_price=97.5)
    assert result.action == "BLOCKED"
    assert any("invalidation" in blocker for blocker in result.blockers)


def test_no_trade_risk_decision_blocks_execution() -> None:
    risk = risk_allow()
    risk.decision = "NO_TRADE"
    risk.position_size_quote = 0.0
    result = build_execution_intent(ready_long(), risk, current_price=102.0)
    assert result.allowed is False
    assert any("Risk engine rejected" in blocker for blocker in result.blockers)


def test_reduce_size_is_allowed_with_reduced_size() -> None:
    risk = risk_allow()
    risk.decision = "REDUCE_SIZE"
    risk.position_size_quote = 800.0
    result = build_execution_intent(ready_long(), risk, current_price=101.5)
    assert result.allowed is True
    assert result.position_size_quote == 800.0
    assert any("reduced position size" in note for note in result.notes)


def test_stale_thesis_is_blocked() -> None:
    cfg = ExecutionConfig(max_chase_pct=1.5, max_thesis_age_bars=4)
    result = build_execution_intent(ready_long(), risk_allow(), current_price=102.0, bars_since_thesis=5, config=cfg)
    assert result.allowed is False
    assert any("stale" in blocker for blocker in result.blockers)


def test_duplicate_open_position_is_blocked() -> None:
    result = build_execution_intent(ready_long(), risk_allow(), current_price=102.0, has_open_position=True)
    assert result.allowed is False
    assert any("open position" in blocker for blocker in result.blockers)


def test_cooldown_blocks_execution() -> None:
    result = build_execution_intent(ready_long(), risk_allow(), current_price=102.0, cooldown_active=True)
    assert result.allowed is False
    assert any("cooldown" in blocker for blocker in result.blockers)


def test_non_ready_thesis_is_blocked() -> None:
    thesis = ready_long()
    thesis.state = "WATCH"
    result = build_execution_intent(thesis, risk_allow(), current_price=102.0)
    assert result.allowed is False
    assert any("not READY" in blocker for blocker in result.blockers)


def test_symbol_mismatch_is_invalid() -> None:
    result = build_execution_intent(ready_long(), risk_allow("OTHERUSDT"), current_price=102.0)
    assert result.allowed is False
    assert "SYMBOL_MISMATCH" in result.errors


def test_invalid_current_price_is_invalid() -> None:
    result = build_execution_intent(ready_long(), risk_allow(), current_price=0.0)
    assert result.allowed is False
    assert "INVALID_CURRENT_PRICE" in result.errors
