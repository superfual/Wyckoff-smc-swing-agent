"""
Agent Orchestration Pipeline
Wyckoff + SMC Spot Swing Agent

Connects the scanner, Wyckoff, SMC, confluence, thesis, risk and execution
guard into one deterministic end-to-end decision flow.

This module does not fetch exchange data and does not place orders. External
adapters may consume an ENTER intent only after this pipeline has passed every
gate.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .confluence import ConfluenceAnalysis, analyze_confluence
    from .execution import ExecutionConfig, ExecutionIntent, build_execution_intent
    from .market_data import MarketData
    from .risk import RiskAssessment, RiskConfig, evaluate_risk
    from .scanner import ScanResult, scan_market
    from .smc import SMCAnalysis, analyze_smc
    from .thesis import TradeThesis, build_trade_thesis
    from .wyckoff import WyckoffAnalysis, analyze_wyckoff
except ImportError:  # Allows: python src/orchestrator.py
    from confluence import ConfluenceAnalysis, analyze_confluence
    from execution import ExecutionConfig, ExecutionIntent, build_execution_intent
    from market_data import MarketData
    from risk import RiskAssessment, RiskConfig, evaluate_risk
    from scanner import ScanResult, scan_market
    from smc import SMCAnalysis, analyze_smc
    from thesis import TradeThesis, build_trade_thesis
    from wyckoff import WyckoffAnalysis, analyze_wyckoff


AgentAction = Literal["ENTER_LONG", "ENTER_SHORT", "WAIT", "BLOCKED", "SKIP"]


@dataclass(frozen=True)
class AgentConfig:
    scanner_min_classification: str = "WATCH"
    smc_timeframe: str = "1h"
    watchlist_priority: str = "MEDIUM"


@dataclass
class AgentDecision:
    symbol: str
    action: AgentAction
    scan: ScanResult
    wyckoff: WyckoffAnalysis | None
    smc: SMCAnalysis | None
    confluence: ConfluenceAnalysis | None
    thesis: TradeThesis | None
    risk: RiskAssessment | None
    execution: ExecutionIntent | None
    reasons: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


_SCAN_RANK = {
    "INVALID_DATA": -1,
    "LOW_INTEREST": 0,
    "NEUTRAL": 1,
    "WATCH": 2,
    "HIGH_INTEREST": 3,
}


def _scanner_passes(scan: ScanResult, minimum: str) -> bool:
    if minimum not in _SCAN_RANK:
        raise ValueError(f"Unsupported scanner minimum classification: {minimum}")
    return _SCAN_RANK.get(scan.classification, -1) >= _SCAN_RANK[minimum]


def _final_action(execution: ExecutionIntent) -> AgentAction:
    if execution.allowed and execution.action == "ENTER_LONG":
        return "ENTER_LONG"
    if execution.allowed and execution.action == "ENTER_SHORT":
        return "ENTER_SHORT"
    if execution.state == "WAITING":
        return "WAIT"
    return "BLOCKED"


def analyze_symbol(
    market: MarketData,
    *,
    account_equity: float,
    current_portfolio_exposure_pct: float = 0.0,
    bars_since_thesis: int = 0,
    has_open_position: bool = False,
    cooldown_active: bool = False,
    config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
) -> AgentDecision:
    """Run one normalized symbol through every decision layer."""

    cfg = config or AgentConfig()
    scan = scan_market(market, priority=cfg.watchlist_priority)

    if not _scanner_passes(scan, cfg.scanner_min_classification):
        reasons = [f"Scanner classification {scan.classification} is below {cfg.scanner_min_classification} threshold."]
        if scan.errors:
            reasons.append("Scanner input data is invalid or incomplete.")
        return AgentDecision(
            symbol=market.symbol,
            action="SKIP",
            scan=scan,
            wyckoff=None,
            smc=None,
            confluence=None,
            thesis=None,
            risk=None,
            execution=None,
            reasons=reasons,
            interpretation="Candidate is filtered out before deep analysis to preserve attention and avoid noisy overtrading.",
            errors=list(scan.errors),
        )

    wyckoff = analyze_wyckoff(market)
    smc = analyze_smc(market, timeframe=cfg.smc_timeframe)
    confluence = analyze_confluence(wyckoff, smc)
    thesis = build_trade_thesis(confluence, wyckoff, smc)
    risk = evaluate_risk(
        thesis,
        account_equity=account_equity,
        current_portfolio_exposure_pct=current_portfolio_exposure_pct,
        config=risk_config,
    )

    current_price = market.current_price or 0.0
    execution = build_execution_intent(
        thesis,
        risk,
        current_price,
        bars_since_thesis=bars_since_thesis,
        has_open_position=has_open_position,
        cooldown_active=cooldown_active,
        config=execution_config,
    )
    action = _final_action(execution)

    reasons: list[str] = [
        f"Scanner: {scan.classification} ({scan.score:.1f}).",
        f"Wyckoff: {wyckoff.bias} / {wyckoff.phase} ({wyckoff.confidence:.1f}% confidence).",
        f"SMC: {smc.bias} / {smc.trend_state}.",
        f"Confluence: {confluence.classification} ({confluence.confidence:.1f}% confidence).",
        f"Thesis: {thesis.state} {thesis.direction}.",
        f"Risk: {risk.decision}.",
        f"Execution: {execution.state} / {execution.action}.",
    ]
    reasons.extend(execution.blockers)
    reasons.extend(execution.notes)

    errors = []
    errors.extend(confluence.errors)
    errors.extend(thesis.errors)
    errors.extend(risk.errors)
    errors.extend(execution.errors)

    interpretation = {
        "ENTER_LONG": "All analytical, risk and execution gates pass for a long execution intent.",
        "ENTER_SHORT": "All analytical, risk and execution gates pass for a short execution intent.",
        "WAIT": "The setup survives analysis and risk controls, but price/location conditions require patience rather than chasing.",
        "BLOCKED": "The candidate reached deep analysis but a thesis, risk or execution safety gate blocks action.",
        "SKIP": "Candidate does not merit deep analysis under the scanner threshold.",
    }[action]

    return AgentDecision(
        symbol=market.symbol,
        action=action,
        scan=scan,
        wyckoff=wyckoff,
        smc=smc,
        confluence=confluence,
        thesis=thesis,
        risk=risk,
        execution=execution,
        reasons=reasons,
        interpretation=interpretation,
        errors=errors,
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Agent orchestrator ready; no exchange orders are sent by this module.")
