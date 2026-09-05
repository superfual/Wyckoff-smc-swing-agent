"""Agent Orchestration Pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Literal

try:
    from .confluence import ConfluenceAnalysis, analyze_confluence
    from .execution import ExecutionConfig, ExecutionIntent, build_execution_intent
    from .market_data import MarketData
    from .modes import TradingMode, VALID_TRADING_MODES
    from .risk import RiskAssessment, RiskConfig, evaluate_risk
    from .scanner import ScanResult, scan_market
    from .smc import SMCAnalysis, analyze_smc
    from .thesis import TradeThesis, build_trade_thesis
    from .wyckoff import WyckoffAnalysis, analyze_wyckoff
except ImportError:
    from confluence import ConfluenceAnalysis, analyze_confluence
    from execution import ExecutionConfig, ExecutionIntent, build_execution_intent
    from market_data import MarketData
    from modes import TradingMode, VALID_TRADING_MODES
    from risk import RiskAssessment, RiskConfig, evaluate_risk
    from scanner import ScanResult, scan_market
    from smc import SMCAnalysis, analyze_smc
    from thesis import TradeThesis, build_trade_thesis
    from wyckoff import WyckoffAnalysis, analyze_wyckoff

AgentAction = Literal["ENTER_LONG", "ENTER_SHORT", "AVOID_BUY", "WAIT", "BLOCKED", "SKIP"]


@dataclass(frozen=True)
class AgentConfig:
    scanner_min_classification: str = "WATCH"
    smc_timeframe: str = "1h"
    watchlist_priority: str = "MEDIUM"
    trading_mode: TradingMode = "SPOT"


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
    def to_dict(self) -> dict: return asdict(self)

_SCAN_RANK = {"INVALID_DATA":-1,"LOW_INTEREST":0,"NEUTRAL":1,"WATCH":2,"HIGH_INTEREST":3}


def _scanner_passes(scan: ScanResult, minimum: str) -> bool:
    if minimum not in _SCAN_RANK:
        raise ValueError(f"Unsupported scanner minimum classification: {minimum}")
    return _SCAN_RANK.get(scan.classification,-1) >= _SCAN_RANK[minimum]


def _final_action(execution: ExecutionIntent) -> AgentAction:
    if execution.allowed and execution.action == "ENTER_LONG": return "ENTER_LONG"
    if execution.allowed and execution.action == "ENTER_SHORT": return "ENTER_SHORT"
    if execution.action == "AVOID_BUY": return "AVOID_BUY"
    if execution.state == "WAITING": return "WAIT"
    return "BLOCKED"


def analyze_symbol(market: MarketData, *, account_equity: float, current_portfolio_exposure_pct: float = 0.0, bars_since_thesis: int = 0, has_open_position: bool = False, cooldown_active: bool = False, config: AgentConfig | None = None, risk_config: RiskConfig | None = None, execution_config: ExecutionConfig | None = None) -> AgentDecision:
    cfg = config or AgentConfig()
    if cfg.trading_mode not in VALID_TRADING_MODES:
        raise ValueError(f"Unsupported trading mode: {cfg.trading_mode}")

    scan = scan_market(market, priority=cfg.watchlist_priority)
    if not _scanner_passes(scan,cfg.scanner_min_classification):
        reasons=[f"Scanner classification {scan.classification} is below {cfg.scanner_min_classification} threshold."]
        if scan.errors: reasons.append("Scanner input data is invalid or incomplete.")
        return AgentDecision(market.symbol,"SKIP",scan,None,None,None,None,None,None,reasons,"Candidate is filtered out before deep analysis to preserve attention and avoid noisy overtrading.",list(scan.errors))

    wyckoff=analyze_wyckoff(market)
    smc=analyze_smc(market,timeframe=cfg.smc_timeframe)
    confluence=analyze_confluence(wyckoff,smc)
    thesis=build_trade_thesis(confluence,wyckoff,smc)

    risk_cfg=replace(risk_config or RiskConfig(), trading_mode=cfg.trading_mode)
    execution_cfg=replace(execution_config or ExecutionConfig(), trading_mode=cfg.trading_mode)
    risk=evaluate_risk(thesis,account_equity,current_portfolio_exposure_pct,config=risk_cfg)
    execution=build_execution_intent(thesis,risk,market.current_price or 0.0,bars_since_thesis=bars_since_thesis,has_open_position=has_open_position,cooldown_active=cooldown_active,config=execution_cfg)
    action=_final_action(execution)

    reasons=[
        f"Mode: {cfg.trading_mode}.",
        f"Scanner: {scan.classification} ({scan.score:.1f}).",
        f"Wyckoff: {wyckoff.bias} / {wyckoff.phase} ({wyckoff.confidence:.1f}% confidence).",
        f"SMC: {smc.bias} / {smc.trend_state}.",
        f"Confluence: {confluence.classification} ({confluence.confidence:.1f}% confidence).",
        f"Thesis: {thesis.state} {thesis.direction}.",
        f"Risk: {risk.decision}.",
        f"Execution: {execution.state} / {execution.action}.",
    ] + execution.blockers + execution.notes
    errors=list(confluence.errors)+list(thesis.errors)+list(risk.errors)+list(execution.errors)
    interpretation={
        "ENTER_LONG":"All analytical, risk and execution gates pass for a long execution intent.",
        "ENTER_SHORT":"Futures mode explicitly permits this short execution intent.",
        "AVOID_BUY":"Bearish evidence is actionable defensively in Spot mode, but short execution is prohibited.",
        "WAIT":"The setup survives analysis and risk controls, but price/location conditions require patience rather than chasing.",
        "BLOCKED":"The candidate reached deep analysis but a thesis, risk or execution safety gate blocks action.",
        "SKIP":"Candidate does not merit deep analysis under the scanner threshold.",
    }[action]
    return AgentDecision(market.symbol,action,scan,wyckoff,smc,confluence,thesis,risk,execution,reasons,interpretation,errors)
