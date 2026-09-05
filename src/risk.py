"""
Risk Management Engine
Wyckoff + SMC Spot Swing Agent

Evaluates whether a READY trade thesis deserves capital allocation.
This module does not place orders. It enforces capital-preservation rules,
position sizing, risk/reward requirements and exposure caps.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .thesis import TradeThesis
except ImportError:  # Allows: python src/risk.py
    from thesis import TradeThesis


RiskDecision = Literal["ALLOW", "REDUCE_SIZE", "NO_TRADE"]


@dataclass(frozen=True)
class RiskConfig:
    risk_per_trade_pct: float = 1.0
    max_position_pct: float = 20.0
    max_portfolio_exposure_pct: float = 60.0
    min_reward_risk: float = 2.0
    max_stop_distance_pct: float = 8.0


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
    if thesis.entry_zone is None:
        return None
    return thesis.entry_zone.midpoint


def _distances(direction: str, entry: float, stop: float, target: float) -> tuple[float, float]:
    if direction == "LONG":
        return entry - stop, target - entry
    if direction == "SHORT":
        return stop - entry, entry - target
    return 0.0, 0.0


def evaluate_risk(
    thesis: TradeThesis,
    account_equity: float,
    current_portfolio_exposure_pct: float = 0.0,
    config: RiskConfig | None = None,
) -> RiskAssessment:
    """Evaluate capital allocation for a trade thesis without executing it."""

    cfg = config or RiskConfig()
    errors: list[str] = []
    reasons: list[str] = []

    if account_equity <= 0:
        errors.append("INVALID_ACCOUNT_EQUITY")
    if not 0 <= current_portfolio_exposure_pct <= 100:
        errors.append("INVALID_PORTFOLIO_EXPOSURE")
    if cfg.risk_per_trade_pct <= 0 or cfg.max_position_pct <= 0 or cfg.max_portfolio_exposure_pct <= 0:
        errors.append("INVALID_RISK_CONFIG")
    if cfg.min_reward_risk <= 0 or cfg.max_stop_distance_pct <= 0:
        errors.append("INVALID_RISK_CONFIG")

    entry = _midpoint_entry(thesis)
    stop = thesis.invalidation_level
    target = thesis.target_level

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

    if errors:
        return RiskAssessment(
            symbol=thesis.symbol,
            decision="NO_TRADE",
            account_equity=account_equity,
            available_exposure=0.0,
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            stop_distance_pct=None,
            reward_risk=None,
            risk_budget=0.0,
            position_size_quote=0.0,
            position_size_units=None,
            projected_exposure_pct=current_portfolio_exposure_pct,
            reasons=reasons,
            interpretation="Risk assessment is invalid because account/config inputs are invalid.",
            errors=errors,
        )

    if reasons:
        return RiskAssessment(
            symbol=thesis.symbol,
            decision="NO_TRADE",
            account_equity=account_equity,
            available_exposure=max(0.0, cfg.max_portfolio_exposure_pct - current_portfolio_exposure_pct),
            entry_price=entry,
            stop_price=stop,
            target_price=target,
            stop_distance_pct=None,
            reward_risk=None,
            risk_budget=0.0,
            position_size_quote=0.0,
            position_size_units=None,
            projected_exposure_pct=current_portfolio_exposure_pct,
            reasons=reasons,
            interpretation="Risk engine blocks allocation until the thesis is fully execution-ready.",
            errors=[],
        )

    assert entry is not None and stop is not None and target is not None

    risk_distance, reward_distance = _distances(thesis.direction, entry, stop, target)
    if risk_distance <= 0:
        reasons.append("Invalid stop placement relative to entry and direction.")
    if reward_distance <= 0:
        reasons.append("Target does not offer positive reward in the thesis direction.")

    if reasons:
        return RiskAssessment(
            thesis.symbol, "NO_TRADE", account_equity,
            max(0.0, cfg.max_portfolio_exposure_pct - current_portfolio_exposure_pct),
            entry, stop, target, None, None, 0.0, 0.0, None,
            current_portfolio_exposure_pct, reasons,
            "Risk geometry is invalid; capital allocation is rejected.", [],
        )

    stop_distance_pct = risk_distance / entry * 100
    reward_risk = reward_distance / risk_distance

    if stop_distance_pct > cfg.max_stop_distance_pct:
        reasons.append(f"Stop distance {stop_distance_pct:.2f}% exceeds maximum {cfg.max_stop_distance_pct:.2f}%.")
    if reward_risk < cfg.min_reward_risk:
        reasons.append(f"Reward/risk {reward_risk:.2f} is below minimum {cfg.min_reward_risk:.2f}.")

    risk_budget = account_equity * cfg.risk_per_trade_pct / 100
    raw_position_quote = risk_budget / (risk_distance / entry)
    max_position_quote = account_equity * cfg.max_position_pct / 100

    available_exposure_pct = max(0.0, cfg.max_portfolio_exposure_pct - current_portfolio_exposure_pct)
    available_exposure_quote = account_equity * available_exposure_pct / 100

    allowed_position_quote = min(raw_position_quote, max_position_quote, available_exposure_quote)
    position_size_units = allowed_position_quote / entry if entry > 0 else None
    projected_exposure_pct = current_portfolio_exposure_pct + (allowed_position_quote / account_equity * 100)

    if available_exposure_pct <= 0:
        reasons.append("Portfolio exposure cap has already been reached.")

    if any(reason.startswith("Stop distance") or reason.startswith("Reward/risk") or reason.startswith("Portfolio exposure cap") for reason in reasons):
        decision: RiskDecision = "NO_TRADE"
        allowed_position_quote = 0.0
        position_size_units = 0.0
        projected_exposure_pct = current_portfolio_exposure_pct
    elif raw_position_quote > max_position_quote or raw_position_quote > available_exposure_quote:
        decision = "REDUCE_SIZE"
        reasons.append("Position size is capped by portfolio/position exposure limits.")
    else:
        decision = "ALLOW"
        reasons.append("Risk budget, stop distance, reward/risk and exposure limits are acceptable.")

    interpretation = {
        "ALLOW": "Trade thesis passes risk controls at the calculated position size.",
        "REDUCE_SIZE": "Trade thesis is valid, but position size must be reduced to respect exposure limits.",
        "NO_TRADE": "Trade thesis is rejected by capital-preservation rules.",
    }[decision]

    return RiskAssessment(
        symbol=thesis.symbol,
        decision=decision,
        account_equity=round(account_equity, 8),
        available_exposure=round(available_exposure_pct, 4),
        entry_price=round(entry, 8),
        stop_price=round(stop, 8),
        target_price=round(target, 8),
        stop_distance_pct=round(stop_distance_pct, 4),
        reward_risk=round(reward_risk, 4),
        risk_budget=round(risk_budget, 8),
        position_size_quote=round(allowed_position_quote, 8),
        position_size_units=round(position_size_units, 8) if position_size_units is not None else None,
        projected_exposure_pct=round(projected_exposure_pct, 4),
        reasons=reasons,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Risk management engine ready.")
