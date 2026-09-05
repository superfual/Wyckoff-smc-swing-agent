from types import SimpleNamespace

from src.paper_report import build_paper_cycle_report, render_paper_cycle_report
from src.paper_runner import RunnerCycleResult, RunnerSymbolResult
from src.paper_runtime import RuntimeCycleResult
from src.paper_session import create_paper_session


def _decision(action="WAIT"):
    return SimpleNamespace(
        action=action,
        scan=SimpleNamespace(classification="WATCH", score=67.25),
        wyckoff=SimpleNamespace(bias="BULLISH", phase="C_TO_D"),
        smc=SimpleNamespace(bias="BULLISH", trend_state="BULLISH_STRUCTURE"),
        confluence=SimpleNamespace(classification="BULLISH", confidence=72.5),
        thesis=SimpleNamespace(state="WATCH", direction="LONG"),
        risk=SimpleNamespace(decision="ALLOW"),
        execution=SimpleNamespace(state="WAITING", action="WAIT_RETRACE", blockers=["WAIT_FOR_RETRACE"]),
        errors=[],
    )


def test_build_report_exposes_decision_pipeline_without_mutating_session():
    session = create_paper_session()
    before = session.to_dict()
    step = SimpleNamespace(decision=_decision(), events=[SimpleNamespace(kind="DECISION")], errors=[])
    cycle = RunnerCycleResult(1000, 1, 0, [RunnerSymbolResult("BTCUSDT", True, step, [])], [])
    runtime_result = RuntimeCycleResult(1000, ["BTCUSDT"], [], cycle, True, [])

    report = build_paper_cycle_report(runtime_result, session)

    assert session.to_dict() == before
    assert report.processed_symbols == 1
    assert report.checkpoint_saved is True
    item = report.symbols[0]
    assert item.symbol == "BTCUSDT"
    assert item.scanner_classification == "WATCH"
    assert item.scanner_score == 67.25
    assert item.wyckoff_phase == "C_TO_D"
    assert item.confluence_confidence == 72.5
    assert item.thesis_state == "WATCH"
    assert item.risk_decision == "ALLOW"
    assert item.execution_action == "WAIT_RETRACE"
    assert item.blockers == ("WAIT_FOR_RETRACE",)


def test_report_handles_scanner_skip_with_missing_deep_analysis():
    session = create_paper_session()
    decision = SimpleNamespace(
        action="SKIP",
        scan=SimpleNamespace(classification="LOW_INTEREST", score=31.0),
        wyckoff=None,
        smc=None,
        confluence=None,
        thesis=None,
        risk=None,
        execution=None,
        errors=[],
    )
    step = SimpleNamespace(decision=decision, events=[SimpleNamespace(kind="DECISION")], errors=[])
    cycle = RunnerCycleResult(2000, 1, 0, [RunnerSymbolResult("ETHUSDT", True, step, [])], [])
    result = RuntimeCycleResult(2000, ["ETHUSDT"], [], cycle, False, [])

    report = build_paper_cycle_report(result, session)
    item = report.symbols[0]
    assert item.action == "SKIP"
    assert item.wyckoff_bias is None
    assert item.execution_action is None
    text = render_paper_cycle_report(report)
    assert "ETHUSDT | SKIP" in text
    assert "Wyckoff: N/A / N/A" in text


def test_report_preserves_symbol_and_cycle_errors():
    session = create_paper_session()
    symbol_result = RunnerSymbolResult("BNBUSDT", False, None, ["REFERENCE_CANDLE_NOT_FRESH"])
    cycle = RunnerCycleResult(3000, 0, 1, [symbol_result], ["CYCLE_ERROR"])
    result = RuntimeCycleResult(3000, ["BNBUSDT"], [], cycle, False, ["RUNTIME_ERROR"])

    report = build_paper_cycle_report(result, session)

    assert report.symbols[0].action == "SKIPPED"
    assert "REFERENCE_CANDLE_NOT_FRESH" in report.symbols[0].errors
    assert "RUNTIME_ERROR" in report.errors
    assert "CYCLE_ERROR" in report.errors
    text = render_paper_cycle_report(report)
    assert "Errors: REFERENCE_CANDLE_NOT_FRESH" in text
    assert "Cycle errors: RUNTIME_ERROR; CYCLE_ERROR" in text


def test_report_uses_session_summary_for_portfolio_state():
    session = create_paper_session()
    session.realized_pnl = 125.5
    session.equity = 10125.5
    session.decisions = 4
    result = RuntimeCycleResult(4000, [], [], None, False, ["PROVIDER_DOWN"])

    report = build_paper_cycle_report(result, session)

    assert report.equity == 10125.5
    assert report.realized_pnl == 125.5
    assert report.processed_symbols == 0
    assert report.errors == ("PROVIDER_DOWN",)
    assert "equity=10125.50" in render_paper_cycle_report(report)
