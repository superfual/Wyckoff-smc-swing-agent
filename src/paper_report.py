"""Paper Cycle Decision Snapshot / Reporting.

Turns RuntimeCycleResult + PaperSession state into a compact, serializable report
for human inspection. Reporting is read-only: it does not alter strategy state,
positions, risk decisions, checkpoints, safety state, or exchange state.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

try:
    from .paper_runtime import RuntimeCycleResult
    from .paper_session import PaperSession, summarize_paper_session
except ImportError:
    from paper_runtime import RuntimeCycleResult
    from paper_session import PaperSession, summarize_paper_session


@dataclass(frozen=True)
class SymbolDecisionSnapshot:
    symbol: str
    processed: bool
    action: str
    scanner_classification: str | None = None
    scanner_score: float | None = None
    wyckoff_bias: str | None = None
    wyckoff_phase: str | None = None
    smc_bias: str | None = None
    smc_trend_state: str | None = None
    confluence_classification: str | None = None
    confluence_confidence: float | None = None
    thesis_state: str | None = None
    thesis_direction: str | None = None
    risk_decision: str | None = None
    execution_state: str | None = None
    execution_action: str | None = None
    open_position: bool = False
    event_kinds: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    errors: tuple[str, ...] = ()


@dataclass(frozen=True)
class PaperCycleReport:
    decision_time: int
    processed_symbols: int
    skipped_symbols: int
    checkpoint_saved: bool
    equity: float
    realized_pnl: float
    unrealized_pnl: float
    exposure_pct: float
    open_positions: int
    total_trades: int
    kill_switch_active: bool = False
    daily_pnl_pct: float = 0.0
    symbols: tuple[SymbolDecisionSnapshot, ...] = ()
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _round_optional(value: Any, digits: int = 2) -> float | None:
    if value is None:
        return None
    return round(float(value), digits)


def _spot_operator_action(action: str | None) -> str:
    return {
        "ENTER_LONG": "BUY_SPOT",
        "ENTER_SHORT": "FUTURES_SHORT",
        "AVOID_BUY": "AVOID_BUY",
        "WAIT_RETRACE": "WAIT_RETRACE",
        "BLOCKED": "BLOCKED",
        "WAIT": "WAIT",
        "SKIP": "SKIP",
        "SKIPPED": "SKIPPED",
    }.get(action or "", action or "N/A")


def _spot_thesis(direction: str | None) -> str:
    return {
        "LONG": "BULLISH (SPOT BUY THESIS)",
        "SHORT": "BEARISH (AVOID BUY IN SPOT)",
        "NEUTRAL": "NEUTRAL",
        "UNKNOWN": "UNKNOWN",
    }.get(direction or "", direction or "")


def build_paper_cycle_report(result: RuntimeCycleResult, session: PaperSession) -> PaperCycleReport:
    summary = summarize_paper_session(session)
    snapshots: list[SymbolDecisionSnapshot] = []

    if result.cycle is not None:
        for symbol_result in result.cycle.symbol_results:
            step = symbol_result.step
            decision = step.decision if step is not None else None
            scan = decision.scan if decision is not None else None
            wyckoff = decision.wyckoff if decision is not None else None
            smc = decision.smc if decision is not None else None
            confluence = decision.confluence if decision is not None else None
            thesis = decision.thesis if decision is not None else None
            risk = decision.risk if decision is not None else None
            execution = decision.execution if decision is not None else None
            account = session.accounts.get(symbol_result.symbol)

            errors = list(symbol_result.errors)
            if step is not None:
                errors.extend(step.errors)
            if decision is not None:
                errors.extend(decision.errors)

            snapshots.append(SymbolDecisionSnapshot(
                symbol=symbol_result.symbol,
                processed=symbol_result.processed,
                action=decision.action if decision is not None else "SKIPPED",
                scanner_classification=scan.classification if scan is not None else None,
                scanner_score=_round_optional(scan.score) if scan is not None else None,
                wyckoff_bias=wyckoff.bias if wyckoff is not None else None,
                wyckoff_phase=wyckoff.phase if wyckoff is not None else None,
                smc_bias=smc.bias if smc is not None else None,
                smc_trend_state=smc.trend_state if smc is not None else None,
                confluence_classification=confluence.classification if confluence is not None else None,
                confluence_confidence=_round_optional(confluence.confidence) if confluence is not None else None,
                thesis_state=thesis.state if thesis is not None else None,
                thesis_direction=thesis.direction if thesis is not None else None,
                risk_decision=risk.decision if risk is not None else None,
                execution_state=execution.state if execution is not None else None,
                execution_action=execution.action if execution is not None else None,
                open_position=account is not None and account.open_position is not None,
                event_kinds=tuple(event.kind for event in step.events) if step is not None else (),
                blockers=tuple(execution.blockers) if execution is not None else (),
                errors=tuple(dict.fromkeys(errors)),
            ))

    cycle = result.cycle
    errors = list(result.errors)
    if cycle is not None:
        errors.extend(cycle.errors)

    return PaperCycleReport(
        decision_time=result.decision_time,
        processed_symbols=cycle.processed_symbols if cycle is not None else 0,
        skipped_symbols=cycle.skipped_symbols if cycle is not None else len(result.missing_symbols),
        checkpoint_saved=result.checkpoint_saved,
        equity=summary.equity,
        realized_pnl=summary.realized_pnl,
        unrealized_pnl=summary.unrealized_pnl,
        exposure_pct=summary.exposure_pct,
        open_positions=summary.open_positions,
        total_trades=summary.total_trades,
        kill_switch_active=summary.kill_switch_active,
        daily_pnl_pct=summary.daily_pnl_pct,
        symbols=tuple(snapshots),
        errors=tuple(dict.fromkeys(errors)),
    )


def render_paper_cycle_report(report: PaperCycleReport) -> str:
    lines = [
        f"PAPER CYCLE {report.decision_time}",
        (
            f"Portfolio: equity={report.equity:.2f} | realized={report.realized_pnl:.2f} | "
            f"unrealized={report.unrealized_pnl:.2f} | daily={report.daily_pnl_pct:.2f}% | "
            f"exposure={report.exposure_pct:.2f}% | open={report.open_positions} | trades={report.total_trades}"
        ),
        f"Safety: kill_switch={'ON' if report.kill_switch_active else 'OFF'}",
        "Mode: SPOT PAPER — BUY_SPOT means acquire the asset; no Futures long is implied.",
        (
            f"Cycle: processed={report.processed_symbols} | skipped={report.skipped_symbols} | "
            f"checkpoint={'YES' if report.checkpoint_saved else 'NO'}"
        ),
    ]

    for item in report.symbols:
        lines.append("")
        lines.append(f"{item.symbol} | {_spot_operator_action(item.action)} | processed={'YES' if item.processed else 'NO'}")
        scanner = item.scanner_classification or "N/A"
        if item.scanner_score is not None:
            scanner += f" ({item.scanner_score:.1f})"
        lines.append(f"  Scanner: {scanner}")
        lines.append(f"  Wyckoff: {item.wyckoff_bias or 'N/A'} / {item.wyckoff_phase or 'N/A'}")
        lines.append(f"  SMC: {item.smc_bias or 'N/A'} / {item.smc_trend_state or 'N/A'}")
        confluence = item.confluence_classification or "N/A"
        if item.confluence_confidence is not None:
            confluence += f" ({item.confluence_confidence:.1f}%)"
        lines.append(f"  Confluence: {confluence}")
        thesis_text = _spot_thesis(item.thesis_direction)
        lines.append(f"  Thesis: {item.thesis_state or 'N/A'} {thesis_text}".rstrip())
        lines.append(f"  Risk: {item.risk_decision or 'N/A'}")
        lines.append(f"  Execution: {item.execution_state or 'N/A'} / {_spot_operator_action(item.execution_action)}")
        lines.append(f"  Position: {'SPOT HOLDING OPEN' if item.open_position else 'FLAT'}")
        if item.event_kinds:
            lines.append("  Events: " + ", ".join(item.event_kinds))
        if item.blockers:
            lines.append("  Blockers: " + "; ".join(item.blockers))
        if item.errors:
            lines.append("  Errors: " + "; ".join(item.errors))

    if report.errors:
        lines.append("")
        lines.append("Cycle errors: " + "; ".join(report.errors))
    return "\n".join(lines)


if __name__ == "__main__":
    print("Paper cycle decision reporting ready.")
