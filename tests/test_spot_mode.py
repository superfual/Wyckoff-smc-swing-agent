import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from execution import ExecutionConfig, build_execution_intent
from risk import RiskConfig, evaluate_risk
from thesis import PriceZone, TradeThesis


def _thesis(direction="SHORT"):
    if direction == "SHORT":
        zone = PriceZone(99, 101, 100, "TEST")
        stop, target = 105, 90
    else:
        zone = PriceZone(99, 101, 100, "TEST")
        stop, target = 95, 110
    return TradeThesis(
        symbol="BTCUSDT",
        state="READY",
        direction=direction,
        confidence=80.0,
        entry_zone=zone,
        invalidation_level=stop,
        target_level=target,
        target_reason="TEST",
        trigger="BOS",
        blockers=[],
        rationale=[],
        interpretation="test",
        errors=[],
    )


def test_default_spot_risk_blocks_short():
    risk = evaluate_risk(_thesis("SHORT"), 10_000)
    assert risk.decision == "NO_TRADE"
    assert "SPOT_MODE_SHORT_NOT_ALLOWED" in risk.reasons
    assert risk.position_size_quote == 0


def test_default_spot_execution_returns_avoid_buy_for_short():
    thesis = _thesis("SHORT")
    # Even a permissive-looking assessment must be blocked by execution defense-in-depth.
    futures_risk = evaluate_risk(thesis, 10_000, config=RiskConfig(trading_mode="FUTURES"))
    intent = build_execution_intent(thesis, futures_risk, 100)
    assert intent.action == "AVOID_BUY"
    assert intent.allowed is False
    assert "SPOT_MODE_SHORT_NOT_ALLOWED" in intent.blockers


def test_explicit_futures_mode_allows_short():
    thesis = _thesis("SHORT")
    risk = evaluate_risk(thesis, 10_000, config=RiskConfig(trading_mode="FUTURES"))
    assert risk.decision in {"ALLOW", "REDUCE_SIZE"}
    intent = build_execution_intent(thesis, risk, 100, config=ExecutionConfig(trading_mode="FUTURES"))
    assert intent.action == "ENTER_SHORT"
    assert intent.allowed is True


def test_spot_long_behavior_is_unchanged():
    thesis = _thesis("LONG")
    risk = evaluate_risk(thesis, 10_000)
    assert risk.decision in {"ALLOW", "REDUCE_SIZE"}
    intent = build_execution_intent(thesis, risk, 100)
    assert intent.action == "ENTER_LONG"
    assert intent.allowed is True
