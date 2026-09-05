"""Unit tests for the risk management engine."""

from src.risk import RiskConfig, evaluate_risk
from src.thesis import PriceZone, TradeThesis


def ready_long() -> TradeThesis:
    return TradeThesis("TESTUSDT","READY","LONG",85.0,PriceZone(100.0,104.0,102.0,"OB_FVG_OVERLAP"),98.0,112.0,"Buy-side liquidity","Wait for retracement",[],["Bullish confluence"],"Ready for risk evaluation.",[])


def ready_short() -> TradeThesis:
    return TradeThesis("TESTUSDT","READY","SHORT",82.0,PriceZone(106.0,110.0,108.0,"BEARISH_OB"),112.0,96.0,"Sell-side liquidity","Wait for retracement",[],["Bearish confluence"],"Ready for risk evaluation.",[])


def test_ready_long_can_pass_risk_controls() -> None:
    result=evaluate_risk(ready_long(),10_000,20,config=RiskConfig(risk_per_trade_pct=0.5))
    assert result.decision=="ALLOW" and result.reward_risk>2 and result.position_size_quote>0 and result.projected_exposure_pct<=60


def test_position_is_reduced_when_raw_risk_size_exceeds_cap() -> None:
    cfg=RiskConfig(risk_per_trade_pct=2.0,max_position_pct=10.0,max_portfolio_exposure_pct=60.0,min_reward_risk=2.0,max_stop_distance_pct=8.0)
    result=evaluate_risk(ready_long(),10_000,20,config=cfg)
    assert result.decision=="REDUCE_SIZE" and result.position_size_quote==1_000 and result.projected_exposure_pct==30


def test_low_reward_risk_is_rejected() -> None:
    thesis=ready_long(); thesis.target_level=106.0
    result=evaluate_risk(thesis,10_000)
    assert result.decision=="NO_TRADE" and any("Reward/risk" in r for r in result.reasons)


def test_stop_too_wide_is_rejected() -> None:
    thesis=ready_long(); thesis.invalidation_level=90.0
    result=evaluate_risk(thesis,10_000)
    assert result.decision=="NO_TRADE" and any("Stop distance" in r for r in result.reasons)


def test_portfolio_exposure_cap_blocks_trade() -> None:
    result=evaluate_risk(ready_long(),10_000,60)
    assert result.decision=="NO_TRADE" and any("Portfolio exposure cap" in r for r in result.reasons)


def test_non_ready_thesis_is_blocked() -> None:
    thesis=ready_long(); thesis.state="WATCH"
    result=evaluate_risk(thesis,10_000)
    assert result.decision=="NO_TRADE" and result.risk_budget==0 and any("not READY" in r for r in result.reasons)


def test_short_geometry_is_supported_in_futures_mode() -> None:
    result=evaluate_risk(ready_short(),10_000,10,config=RiskConfig(trading_mode="FUTURES"))
    assert result.decision in {"ALLOW","REDUCE_SIZE"} and result.stop_distance_pct>0 and result.reward_risk>=2


def test_invalid_account_equity_returns_error() -> None:
    result=evaluate_risk(ready_long(),0)
    assert result.decision=="NO_TRADE" and "INVALID_ACCOUNT_EQUITY" in result.errors


def test_invalid_stop_geometry_is_rejected() -> None:
    thesis=ready_long(); thesis.invalidation_level=103.0
    result=evaluate_risk(thesis,10_000)
    assert result.decision=="NO_TRADE" and any("Invalid stop placement" in r for r in result.reasons)
