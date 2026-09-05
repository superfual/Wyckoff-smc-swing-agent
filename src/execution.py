"""Execution Guard Engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .modes import TradingMode, VALID_TRADING_MODES
    from .risk import RiskAssessment
    from .thesis import TradeThesis
except ImportError:
    from modes import TradingMode, VALID_TRADING_MODES
    from risk import RiskAssessment
    from thesis import TradeThesis

ExecutionAction = Literal["ENTER_LONG", "ENTER_SHORT", "WAIT_RETRACE", "AVOID_BUY", "BLOCKED"]
ExecutionState = Literal["READY_TO_EXECUTE", "WAITING", "BLOCKED"]


@dataclass(frozen=True)
class ExecutionConfig:
    max_chase_pct: float = 1.5
    max_thesis_age_bars: int = 6
    trading_mode: TradingMode = "SPOT"


@dataclass
class ExecutionIntent:
    symbol: str
    state: ExecutionState
    action: ExecutionAction
    allowed: bool
    direction: str
    current_price: float
    entry_lower: float | None
    entry_upper: float | None
    planned_entry: float | None
    stop_price: float | None
    target_price: float | None
    position_size_quote: float
    position_size_units: float | None
    risk_decision: str
    blockers: list[str]
    notes: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _invalidated(thesis: TradeThesis, current_price: float) -> bool:
    stop = thesis.invalidation_level
    if stop is None:
        return True
    if thesis.direction == "LONG":
        return current_price <= stop
    if thesis.direction == "SHORT":
        return current_price >= stop
    return True


def _in_entry_zone(thesis: TradeThesis, current_price: float) -> bool:
    return bool(thesis.entry_zone and thesis.entry_zone.lower <= current_price <= thesis.entry_zone.upper)


def _chase_distance_pct(thesis: TradeThesis, current_price: float) -> float:
    zone = thesis.entry_zone
    if zone is None:
        return float("inf")
    if thesis.direction == "LONG" and current_price > zone.upper:
        return (current_price - zone.upper) / zone.upper * 100
    if thesis.direction == "SHORT" and current_price < zone.lower:
        return (zone.lower - current_price) / zone.lower * 100
    return 0.0


def build_execution_intent(thesis: TradeThesis, risk: RiskAssessment, current_price: float, *, bars_since_thesis: int = 0, has_open_position: bool = False, cooldown_active: bool = False, config: ExecutionConfig | None = None) -> ExecutionIntent:
    cfg = config or ExecutionConfig()
    blockers: list[str] = []
    notes: list[str] = []
    errors: list[str] = []
    zone = thesis.entry_zone
    lower = zone.lower if zone else None
    upper = zone.upper if zone else None

    if cfg.trading_mode not in VALID_TRADING_MODES:
        errors.append("INVALID_TRADING_MODE")
    if current_price <= 0:
        errors.append("INVALID_CURRENT_PRICE")
    if bars_since_thesis < 0 or cfg.max_chase_pct < 0 or cfg.max_thesis_age_bars < 0:
        errors.append("INVALID_EXECUTION_CONFIG")
    if thesis.symbol != risk.symbol:
        errors.append("SYMBOL_MISMATCH")
    if errors:
        return ExecutionIntent(thesis.symbol,"BLOCKED","BLOCKED",False,thesis.direction,current_price,lower,upper,None,thesis.invalidation_level,thesis.target_level,0.0,None,risk.decision,[],[],"Execution intent is invalid because guard inputs are malformed or mismatched.",errors)

    if cfg.trading_mode == "SPOT" and thesis.direction == "SHORT":
        return ExecutionIntent(thesis.symbol,"WAITING","AVOID_BUY",False,thesis.direction,round(current_price,8),lower,upper,None,thesis.invalidation_level,thesis.target_level,0.0,0.0,risk.decision,["SPOT_MODE_SHORT_NOT_ALLOWED"],["Bearish thesis remains useful as a defensive spot signal."],"Spot mode forbids short execution; avoid new long exposure instead.",[])

    if thesis.state != "READY": blockers.append("Trade thesis is not READY.")
    if thesis.direction not in {"LONG","SHORT"}: blockers.append("Trade thesis has no executable direction.")
    if zone is None: blockers.append("No structured entry zone is available.")
    if thesis.invalidation_level is None or thesis.target_level is None: blockers.append("Stop/target geometry is incomplete.")
    if risk.decision == "NO_TRADE": blockers.append("Risk engine rejected the trade.")
    if risk.errors: blockers.append("Risk assessment contains errors.")
    if risk.position_size_quote <= 0: blockers.append("Risk-approved position size is zero.")
    if bars_since_thesis > cfg.max_thesis_age_bars: blockers.append("Trade thesis is stale and must be re-evaluated.")
    if has_open_position: blockers.append("An open position already exists for this setup/symbol.")
    if cooldown_active: blockers.append("Execution cooldown is active.")
    if _invalidated(thesis,current_price): blockers.append("Current price has breached the thesis invalidation level.")
    if blockers:
        return ExecutionIntent(thesis.symbol,"BLOCKED","BLOCKED",False,thesis.direction,round(current_price,8),lower,upper,None,thesis.invalidation_level,thesis.target_level,0.0,0.0,risk.decision,blockers,notes,"Execution is blocked until all final safety conditions are valid again.",[])

    assert zone is not None
    if _in_entry_zone(thesis,current_price):
        action: ExecutionAction = "ENTER_LONG" if thesis.direction == "LONG" else "ENTER_SHORT"
        notes.append("Current price is inside the structured entry zone.")
        if risk.decision == "REDUCE_SIZE": notes.append("Use the reduced position size approved by the risk engine.")
        return ExecutionIntent(thesis.symbol,"READY_TO_EXECUTE",action,True,thesis.direction,round(current_price,8),zone.lower,zone.upper,round(current_price,8),thesis.invalidation_level,thesis.target_level,risk.position_size_quote,risk.position_size_quote/current_price,risk.decision,[],notes,"All final guards pass and price is inside the planned entry zone.",[])

    chase = _chase_distance_pct(thesis,current_price)
    if chase > cfg.max_chase_pct:
        blockers.append(f"Price has moved {chase:.2f}% beyond the entry zone; chasing is prohibited.")
        return ExecutionIntent(thesis.symbol,"BLOCKED","BLOCKED",False,thesis.direction,round(current_price,8),zone.lower,zone.upper,None,thesis.invalidation_level,thesis.target_level,0.0,0.0,risk.decision,blockers,notes,"Setup remains directionally valid, but price has run too far from the planned entry zone.",[])
    notes.append("Setup remains valid, but price is outside the structured entry zone.")
    return ExecutionIntent(thesis.symbol,"WAITING","WAIT_RETRACE",False,thesis.direction,round(current_price,8),zone.lower,zone.upper,None,thesis.invalidation_level,thesis.target_level,risk.position_size_quote,risk.position_size_units,risk.decision,[],notes,"Final guards pass, but execution must wait for price to retrace into the structured entry zone.",[])
