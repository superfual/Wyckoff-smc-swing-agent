"""Unit tests for the risk management engine."""

from src.risk import RiskConfig, evaluate_risk
from src.thesis import PriceZone, TradeThesis


def ready_long() -> TradeThesis:
    return TradeThesis(
        symbol="TESTUSDT",
        state="READY",
        direction="LONG",
        confidence=85.0,
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
        confidence=82.0,
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


def test_ready_long_can_pass_risk_controls() -> None:
    result = evaluate_risk(ready_long(), account_equity=10_000, current_portfolio_exposure_pct=20)
    assert result.decision == "ALLOW"
    assert result.reward_risk > 2
    assert result.position_size_quote > 0
    assert result.projected_exposure_pct <= 60


def test_position_is_reduced_when_raw_risk_size_exceeds_cap() -> None:
    cfg = RiskConfig(risk_per_trade_pct=2.0, max_position_pct=10.0, max_portfolio_exposure_pct=60.0, min_reward_risk=2.0, max_stop_distance_pct=8.0)
    result = evaluate_risk(ready_long(), account_equity=10_000, current_portfolio_exposure_pct=20, config=cfg)
    assert result.decision == "REDUCE_SIZE"
    assert result.position_size_quote == 1_000
    assert result.projected_exposure_pct == 30


def test_low_reward_risk_is_rejected() -> None:
    thesis = ready_long()
    thesis.target_level = 106.0
    result = evaluate_risk(thesis, account_equity=10_000)
    assert result.decision == "NO_TRADE"
    assert any("Reward/risk" in reason for reason in result.reasons)
    assert result.position_size_quote == 0


def test_stop_too_wide_is_rejected() -> None:
    thesis = ready_long()
    thesis.invalidation_level = 90.0
    result = evaluate_risk(thesis, account_equity=10_000)
    assert result.decision == "NO_TRADE"
    assert any("Stop distance" in reason for reason in result.reasons)


def test_portfolio_exposure_cap_blocks_trade() -> None:
    result = evaluate_risk(ready_long(), account_equity=10_000, current_portfolio_exposure_pct=60)
    assert result.decision == "NO_TRADE"
    assert any("Portfolio exposure cap" in reason for reason in result.reasons)


def test_non_ready_thesis_is_blocked() -> None:
    thesis = ready_long()
    thesis.state = "WATCH"
    result = evaluate_risk(thesis, account_equity=10_000)
    assert result.decision == "NO_TRADE"
    assert result.risk_budget == 0
    assert any("not READY" in reason for reason in result.reasons)


def test_short_geometry_is_supported() -> None:
    result = evaluate_risk(ready_short(), account_equity=10_000, current_portfolio_exposure_pct=10)
    assert result.decision in {"ALLOW", "REDUCE_SIZE"}
    assert result.stop_distance_pct > 0
    assert result.reward_risk >= 2


def test_invalid_account_equity_returns_error() -> None:
    result = evaluate_risk(ready_long(), account_equity=0)
    assert result.decision == "NO_TRADE"
    assert "INVALID_ACCOUNT_EQUITY" in result.errors


def test_invalid_stop_geometry_is_rejected() -> None:
    thesis = ready_long()
    thesis.invalidation_level = 103.0
    result = evaluate_risk(thesis, account_equity=10_000)
    assert result.decision == "NO_TRADE"
    assert any("Invalid stop placement" in reason for reason in result.reasons)
