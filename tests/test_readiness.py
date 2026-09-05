import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from execution import ExecutionConfig
from orchestrator import AgentConfig
from readiness import ReadinessConfig, SafetyEvidence, derive_safety_evidence, evaluate_system_readiness


def _oos(verdict="ROBUST", errors=None):
    return SimpleNamespace(verdict=verdict, errors=errors or [])


def _wf(verdict="ROBUST", errors=None):
    return SimpleNamespace(verdict=verdict, errors=errors or [])


def _paper(trades=25, decisions=200, expectancy=0.25, drawdown=5.0, errors=None):
    return SimpleNamespace(
        total_trades=trades,
        total_decisions=decisions,
        expectancy_r=expectancy,
        max_drawdown_pct=drawdown,
        errors=errors or [],
    )


def _comparator(verdict="ALIGNED", promotion_allowed=True, errors=None):
    return SimpleNamespace(verdict=verdict, promotion_allowed=promotion_allowed, errors=errors or [])


def test_default_spot_configs_prove_upstream_safety_automatically():
    safety = derive_safety_evidence()
    assert safety.derived_from_configs is True
    assert safety.trading_mode == "SPOT"
    assert safety.execution_mode == "SPOT"
    assert safety.mode_consistent is True
    assert safety.spot_short_execution_blocked_upstream is True


def test_good_evidence_and_default_spot_config_can_reach_tiny_live_readiness():
    result = evaluate_system_readiness(_oos(), _wf(), _paper(), _comparator())
    assert result.state == "READY_FOR_TINY_LIVE"
    assert result.promotion_allowed is True
    assert "SPOT_SHORT_BLOCKED_UPSTREAM" not in result.blockers


def test_mode_mismatch_forces_live_blocked():
    result = evaluate_system_readiness(
        _oos(), _wf(), _paper(), _comparator(),
        agent_config=AgentConfig(trading_mode="SPOT"),
        execution_config=ExecutionConfig(trading_mode="FUTURES"),
    )
    assert result.state == "LIVE_BLOCKED"
    assert result.promotion_allowed is False
    assert "TRADING_MODE_CONSISTENT" in result.blockers


def test_futures_mode_cannot_pass_spot_readiness_policy():
    result = evaluate_system_readiness(
        _oos(), _wf(), _paper(), _comparator(),
        agent_config=AgentConfig(trading_mode="FUTURES"),
        execution_config=ExecutionConfig(trading_mode="FUTURES"),
    )
    assert result.state == "PAPER_ONLY"
    assert "REQUIRED_TRADING_MODE" in result.blockers


def test_live_orders_enabled_during_promotion_blocks_readiness():
    result = evaluate_system_readiness(
        _oos(), _wf(), _paper(), _comparator(),
        live_exchange_orders_enabled=True,
    )
    assert result.state == "PAPER_ONLY"
    assert "LIVE_ORDERS_DISABLED_DURING_PROMOTION" in result.blockers


def test_explicit_safety_evidence_remains_supported():
    result = evaluate_system_readiness(
        _oos(), _wf(), _paper(), _comparator(),
        safety=SafetyEvidence(
            spot_short_execution_blocked_upstream=True,
            trading_mode="SPOT",
            execution_mode="SPOT",
        ),
    )
    assert result.state == "READY_FOR_TINY_LIVE"
    assert result.promotion_allowed is True


def test_insufficient_paper_sample_keeps_system_paper_only():
    result = evaluate_system_readiness(_oos(), _wf(), _paper(trades=5), _comparator())
    assert result.state == "PAPER_ONLY"
    assert "PAPER_SAMPLE_SUFFICIENT" in result.blockers


def test_negative_paper_expectancy_blocks_live():
    result = evaluate_system_readiness(
        _oos(), _wf(), _paper(expectancy=-0.10), _comparator(verdict="DIVERGED", promotion_allowed=False)
    )
    assert result.state == "PAPER_ONLY"
    assert result.promotion_allowed is False
    assert "PAPER_EXPECTANCY_POSITIVE" in result.blockers


def test_failed_research_stays_research_only_when_no_paper_evidence():
    result = evaluate_system_readiness(
        _oos("FAILED"), _wf("FAILED"), _paper(trades=0, decisions=0, expectancy=0.0), _comparator("INSUFFICIENT_DATA", False)
    )
    assert result.state == "RESEARCH_ONLY"


def test_source_errors_force_live_blocked():
    result = evaluate_system_readiness(
        _oos(errors=["BAD_SOURCE"]), _wf(), _paper(), _comparator()
    )
    assert result.state == "LIVE_BLOCKED"
    assert "INVALID_OOS_RESULT" in result.errors


def test_explicit_critical_error_forces_live_blocked():
    result = evaluate_system_readiness(
        _oos(), _wf(), _paper(), _comparator(),
        unresolved_critical_errors=("EXECUTION_ADAPTER_BYPASS",),
    )
    assert result.state == "LIVE_BLOCKED"
    assert result.promotion_allowed is False


def test_drawdown_limit_is_enforced():
    result = evaluate_system_readiness(
        _oos(), _wf(), _paper(drawdown=15.0), _comparator(),
        config=ReadinessConfig(max_paper_drawdown_pct=12.0),
    )
    assert result.state == "PAPER_ONLY"
    assert "PAPER_DRAWDOWN_WITHIN_LIMIT" in result.blockers
