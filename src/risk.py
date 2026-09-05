"""Risk Management Engine for the Wyckoff + SMC agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .modes import TradingMode, VALID_TRADING_MODES
    from .thesis import TradeThesis
except ImportError:
    from modes import TradingMode, VALID_TRADING_MODES
    from thesis import TradeThesis

RiskDecision = Literal["ALLOW", "REDUCE_SIZE", "NO_TRADE"]


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0
    max_portfolio_exposure_pct: float = 60.0
    min_reward_risk: float = 2.0
    max_stop_distance_pct: float = 8.0
    trading_mode: TradingMode = "SPOT"


@dataclass
class RiskAssessment:
    symbol: str
    decision: RiskDecision
    account_equity: float
    available_exposure: float
    entry_price: float | None
    stop_price: float | None
    target_price: float | None
    stop_distance_pct: float | None
    reward_risk: float | None
    risk_budget: float
    position_size_quote: float
    position_size_units: float | None
    projected_exposure_pct: float
    reasons: list[str]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _midpoint_entry(thesis: TradeThesis) -> float | None:
    return thesis.entry_zone.midpoint if thesis.entry_zone else None


def _distances(direction: str, entry: float, stop: float, target: float) -> tuple[float, float]:
    if direction == "LONG":
        return entry - stop, target - entry
    if direction == "SHORT":
        return stop - entry, entry - target
    return 0.0, 0.0


def evaluate_risk(thesis: TradeThesis, account_equity: float, current_portfolio_exposure_pct: float = 0.0, config: RiskConfig | None = None) -> RiskAssessment:
    cfg = config or RiskConfig()
    errors: list[str] = []
    reasons: list[str] = []

    if cfg.trading_mode not in VALID_TRADING_MODES:
        errors.append("INVALID_TRADING_MODE")
    if account_equity <= 0:
        errors.append("INVALID_ACCOUNT_EQUITY")
    if not 0 <= current_portfolio_exposure_pct <= 100:
        errors.append("INVALID_PORTFOLIO_EXPOSURE")
    if cfg.risk_per_trade_pct <= 0 or cfg.max_position_pct <= 0 or cfg.max_portfolio_exposure_pct <= 0 or cfg.min_reward_risk <= 0 or cfg.max_stop_distance_pct <= 0:
        errors.append("INVALID_RISK_CONFIG")

    entry = _midpoint_entry(thesis)
    stop = thesis.invalidation_level
    target = thesis.target_level

    if cfg.trading_mode == "SPOT" and thesis.direction == "SHORT":
        reasons.append("SPOT_MODE_SHORT_NOT_ALLOWED")
    if thesis.state != "READY":
        reasons.append("Trade thesis is not READY for risk evaluation.")
    if thesis.direction not in {"LONG", "SHORT"}:
        reasons.append("Trade thesis has no executable direction.")
    if entry is None:
        reasons.append("No structured entry zone is available.")
    if stop is None:
        reasons.append("No invalidation level is available.")
    if target is None:
        reasons.append("No target level is available.")

    available_exposure = max(0.0, cfg.max_portfolio_exposure_pct - current_portfolio_exposure_pct)
    if errors or reasons:
        return RiskAssessment(thesis.symbol, "NO_TRADE", account_equity, 0.0 if errors else available_exposure, entry, stop, target, None, None, 0.0, 0.0, 0.0 if not errors else None, current_portfolio_exposure_pct, reasons, "Risk engine blocks capital allocation for this thesis.", errors)

    assert entry is not None and stop is not None and target is not None
    risk_distance, reward_distance = _distances(thesis.direction, entry, stop, target)
    if risk_distance <= 0:
        reasons.append("Invalid stop placement relative to entry and direction.")
    if reward_distance <= 0:
        reasons.append("Target does not offer positive reward in the thesis direction.")
    if reasons:
        return RiskAssessment(thesis.symbol, "NO_TRADE", account_equity, available_exposure, entry, stop, target, None, None, 0.0, 0.0, 0.0, current_portfolio_exposure_pct, reasons, "Risk geometry is invalid; capital allocation is rejected.", [])

    stop_distance_pct = risk_distance / entry * 100
    reward_risk = reward_distance / risk_distance
    if stop_distance_pct > cfg.max_stop_distance_pct:
        reasons.append(f"Stop distance {stop_distance_pct:.2f}% exceeds maximum {cfg.max_stop_distance_pct:.2f}%.")
    if reward_risk < cfg.min_reward_risk:
        reasons.append(f"Reward/risk {reward_risk:.2f} is below minimum {cfg.min_reward_risk:.2f}.")

    risk_budget = account_equity * cfg.risk_per_trade_pct / 100
    raw_position_quote = risk_budget / (risk_distance / entry)
    max_position_quote = account_equity * cfg.max_position_pct / 100
    available_exposure_quote = account_equity * available_exposure / 100
    allowed_position_quote = min(raw_position_quote, max_position_quote, available_exposure_quote)
    units = allowed_position_quote / entry
    projected = current_portfolio_exposure_pct + allowed_position_quote / account_equity * 100

    if available_exposure <= 0:
        reasons.append("Portfolio exposure cap has already been reached.")
    if any(r.startswith("Stop distance") or r.startswith("Reward/risk") or r.startswith("Portfolio exposure cap") for r in reasons):
        decision: RiskDecision = "NO_TRADE"
        allowed_position_quote = 0.0
        units = 0.0
        projected = current_portfolio_exposure_pct
    elif raw_position_quote > max_position_quote or raw_position_quote > available_exposure_quote:
        decision = "REDUCE_SIZE"
        reasons.append("Position size is capped by portfolio/position exposure limits.")
    else:
        decision = "ALLOW"
        reasons.append("Risk budget, stop distance, reward/risk and exposure limits are acceptable.")

    return RiskAssessment(thesis.symbol, decision, round(account_equity, 8), round(available_exposure, 4), round(entry, 8), round(stop, 8), round(target, 8), round(stop_distance_pct, 4), round(reward_risk, 4), round(risk_budget, 8), round(allowed_position_quote, 8), round(units, 8), round(projected, 4), reasons, {"ALLOW":"Trade thesis passes risk controls at the calculated position size.","REDUCE_SIZE":"Trade thesis is valid, but position size must be reduced to respect exposure limits.","NO_TRADE":"Trade thesis is rejected by capital-preservation rules."}[decision], [])
