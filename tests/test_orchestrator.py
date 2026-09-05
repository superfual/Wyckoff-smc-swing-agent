"""Unit tests for the end-to-end agent orchestration flow."""

from types import SimpleNamespace

import pytest

import src.orchestrator as orchestrator
from src.market_data import MarketData
from src.scanner import ScanResult, ScoreBreakdown


def market(price: float = 102.0) -> MarketData:
    return MarketData(
        symbol="TESTUSDT",
        current_price=price,
        daily=[],
        four_hour=[],
        one_hour=[],
        fifteen_minute=[],
    )


def scan(classification: str = "HIGH_INTEREST", score: float = 82.0) -> ScanResult:
    return ScanResult(
        symbol="TESTUSDT",
        score=score,
        classification=classification,
        priority="HIGH",
        signals=["TEST_SIGNAL"],
        breakdown=ScoreBreakdown(20, 20, 15, 15, 12),
        errors=[],
    )


def install_pipeline(monkeypatch: pytest.MonkeyPatch, *, execution_state: str, execution_action: str, allowed: bool) -> None:
    monkeypatch.setattr(orchestrator, "scan_market", lambda market, priority="MEDIUM": scan())
    monkeypatch.setattr(
        orchestrator,
        "analyze_wyckoff",
        lambda market: SimpleNamespace(symbol=market.symbol, bias="ACCUMULATION", phase="C_TO_D", confidence=82.0, errors=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "analyze_smc",
        lambda market, timeframe="1h": SimpleNamespace(symbol=market.symbol, bias="BULLISH", trend_state="BULLISH_TRANSITION", errors=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "analyze_confluence",
        lambda wyckoff, smc: SimpleNamespace(symbol="TESTUSDT", classification="HIGH_CONVICTION_BULLISH", confidence=86.0, errors=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "build_trade_thesis",
        lambda confluence, wyckoff, smc: SimpleNamespace(symbol="TESTUSDT", state="READY", direction="LONG", errors=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "evaluate_risk",
        lambda thesis, account_equity, current_portfolio_exposure_pct=0.0, config=None: SimpleNamespace(symbol="TESTUSDT", decision="ALLOW", errors=[]),
    )
    monkeypatch.setattr(
        orchestrator,
        "build_execution_intent",
        lambda thesis, risk, current_price, **kwargs: SimpleNamespace(
            symbol="TESTUSDT",
            state=execution_state,
            action=execution_action,
            allowed=allowed,
            blockers=[] if execution_state != "BLOCKED" else ["Safety gate blocked execution."],
            notes=["Synthetic execution test."],
            errors=[],
        ),
    )


def test_high_interest_candidate_can_reach_enter_long(monkeypatch: pytest.MonkeyPatch) -> None:
    install_pipeline(monkeypatch, execution_state="READY_TO_EXECUTE", execution_action="ENTER_LONG", allowed=True)
    result = orchestrator.analyze_symbol(market(), account_equity=10_000)
    assert result.action == "ENTER_LONG"
    assert result.execution.allowed is True
    assert result.risk.decision == "ALLOW"
    assert any("HIGH_INTEREST" in reason for reason in result.reasons)


def test_valid_candidate_waits_when_execution_requires_retrace(monkeypatch: pytest.MonkeyPatch) -> None:
    install_pipeline(monkeypatch, execution_state="WAITING", execution_action="WAIT_RETRACE", allowed=False)
    result = orchestrator.analyze_symbol(market(105.0), account_equity=10_000)
    assert result.action == "WAIT"
    assert "patience" in result.interpretation


def test_execution_block_maps_to_final_blocked(monkeypatch: pytest.MonkeyPatch) -> None:
    install_pipeline(monkeypatch, execution_state="BLOCKED", execution_action="BLOCKED", allowed=False)
    result = orchestrator.analyze_symbol(market(110.0), account_equity=10_000)
    assert result.action == "BLOCKED"
    assert any("Safety gate blocked" in reason for reason in result.reasons)


def test_low_interest_candidate_short_circuits_before_deep_analysis(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "scan_market", lambda market, priority="MEDIUM": scan("LOW_INTEREST", 30.0))

    def should_not_run(*args, **kwargs):
        raise AssertionError("Deep analysis should not run for a filtered candidate")

    monkeypatch.setattr(orchestrator, "analyze_wyckoff", should_not_run)
    result = orchestrator.analyze_symbol(market(), account_equity=10_000)
    assert result.action == "SKIP"
    assert result.wyckoff is None
    assert result.execution is None


def test_neutral_candidate_is_filtered_by_default_watch_threshold(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "scan_market", lambda market, priority="MEDIUM": scan("NEUTRAL", 50.0))
    result = orchestrator.analyze_symbol(market(), account_equity=10_000)
    assert result.action == "SKIP"


def test_scanner_threshold_can_be_lowered_to_neutral(monkeypatch: pytest.MonkeyPatch) -> None:
    install_pipeline(monkeypatch, execution_state="WAITING", execution_action="WAIT_RETRACE", allowed=False)
    monkeypatch.setattr(orchestrator, "scan_market", lambda market, priority="MEDIUM": scan("NEUTRAL", 50.0))
    cfg = orchestrator.AgentConfig(scanner_min_classification="NEUTRAL")
    result = orchestrator.analyze_symbol(market(), account_equity=10_000, config=cfg)
    assert result.action == "WAIT"
    assert result.wyckoff is not None


def test_invalid_scanner_threshold_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(orchestrator, "scan_market", lambda market, priority="MEDIUM": scan())
    cfg = orchestrator.AgentConfig(scanner_min_classification="SUPER_HIGH")
    with pytest.raises(ValueError, match="Unsupported scanner minimum classification"):
        orchestrator.analyze_symbol(market(), account_equity=10_000, config=cfg)
