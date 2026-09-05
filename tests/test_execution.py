"""Unit tests for the execution guard engine."""

from src.execution import ExecutionConfig, build_execution_intent
from src.risk import RiskAssessment
from src.thesis import PriceZone, TradeThesis


def ready_long() -> TradeThesis:
    return TradeThesis("TESTUSDT","READY","LONG",86.0,PriceZone(100.0,104.0,102.0,"OB_FVG_OVERLAP"),98.0,112.0,"Buy-side liquidity","Wait for retracement",[],["Bullish confluence"],"Ready for risk evaluation.",[])


def ready_short() -> TradeThesis:
    return TradeThesis("TESTUSDT","READY","SHORT",84.0,PriceZone(106.0,110.0,108.0,"BEARISH_OB"),112.0,96.0,"Sell-side liquidity","Wait for retracement",[],["Bearish confluence"],"Ready for risk evaluation.",[])


def risk_allow(symbol: str = "TESTUSDT") -> RiskAssessment:
    return RiskAssessment(symbol,"ALLOW",10_000.0,40.0,102.0,98.0,112.0,3.92,2.5,50.0,1_275.0,12.5,32.75,["Risk acceptable"],"Allowed",[])


def test_long_inside_entry_zone_creates_enter_intent() -> None:
    result=build_execution_intent(ready_long(),risk_allow(),current_price=102.5)
    assert result.allowed is True and result.state=="READY_TO_EXECUTE" and result.action=="ENTER_LONG"


def test_short_inside_entry_zone_creates_enter_intent() -> None:
    risk=risk_allow(); risk.entry_price=108.0; risk.stop_price=112.0; risk.target_price=96.0
    result=build_execution_intent(ready_short(),risk,current_price=108.5,config=ExecutionConfig(trading_mode="FUTURES"))
    assert result.allowed is True and result.action=="ENTER_SHORT" and result.state=="READY_TO_EXECUTE"


def test_valid_setup_waits_for_retrace_when_price_not_in_zone() -> None:
    result=build_execution_intent(ready_long(),risk_allow(),current_price=104.8)
    assert result.allowed is False and result.state=="WAITING" and result.action=="WAIT_RETRACE" and result.blockers==[]


def test_runaway_price_is_blocked_to_prevent_chasing() -> None:
    result=build_execution_intent(ready_long(),risk_allow(),current_price=107.0)
    assert result.allowed is False and any("chasing is prohibited" in b for b in result.blockers)


def test_breached_invalidation_blocks_execution() -> None:
    result=build_execution_intent(ready_long(),risk_allow(),current_price=97.5)
    assert result.action=="BLOCKED" and any("invalidation" in b for b in result.blockers)


def test_no_trade_risk_decision_blocks_execution() -> None:
    risk=risk_allow(); risk.decision="NO_TRADE"; risk.position_size_quote=0.0
    result=build_execution_intent(ready_long(),risk,current_price=102.0)
    assert result.allowed is False and any("Risk engine rejected" in b for b in result.blockers)


def test_reduce_size_is_allowed_with_reduced_size() -> None:
    risk=risk_allow(); risk.decision="REDUCE_SIZE"; risk.position_size_quote=800.0
    result=build_execution_intent(ready_long(),risk,current_price=101.5)
    assert result.allowed is True and result.position_size_quote==800.0


def test_stale_thesis_is_blocked() -> None:
    result=build_execution_intent(ready_long(),risk_allow(),current_price=102.0,bars_since_thesis=5,config=ExecutionConfig(max_chase_pct=1.5,max_thesis_age_bars=4))
    assert result.allowed is False and any("stale" in b for b in result.blockers)


def test_duplicate_open_position_is_blocked() -> None:
    assert build_execution_intent(ready_long(),risk_allow(),current_price=102.0,has_open_position=True).allowed is False


def test_cooldown_blocks_execution() -> None:
    assert build_execution_intent(ready_long(),risk_allow(),current_price=102.0,cooldown_active=True).allowed is False


def test_non_ready_thesis_is_blocked() -> None:
    thesis=ready_long(); thesis.state="WATCH"
    assert build_execution_intent(thesis,risk_allow(),current_price=102.0).allowed is False


def test_symbol_mismatch_is_invalid() -> None:
    assert "SYMBOL_MISMATCH" in build_execution_intent(ready_long(),risk_allow("OTHERUSDT"),current_price=102.0).errors


def test_invalid_current_price_is_invalid() -> None:
    assert "INVALID_CURRENT_PRICE" in build_execution_intent(ready_long(),risk_allow(),current_price=0.0).errors
