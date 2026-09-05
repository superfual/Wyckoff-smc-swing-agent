"""Portfolio-level safety guards for paper trading.

Guards new entries using portfolio state rather than symbol-local setup state.
Existing positions are never force-closed by this module; their stop/target
management continues in the paper engine. No exchange orders are sent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

DAY_MS = 86_400_000


@dataclass(frozen=True)
class PortfolioSafetyConfig:
    max_concurrent_positions: int = 3
    max_daily_loss_pct: float = 3.0


@dataclass
class PortfolioSafetyState:
    kill_switch_active: bool = False
    current_day_index: int | None = None
    day_start_equity: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioSafetyAssessment:
    allow_new_entries: bool
    open_positions: int
    daily_pnl_pct: float
    blockers: tuple[str, ...]

    def to_dict(self) -> dict:
        return asdict(self)


def _validate_config(config: PortfolioSafetyConfig) -> None:
    if config.max_concurrent_positions <= 0:
        raise ValueError("max_concurrent_positions must be > 0")
    if config.max_daily_loss_pct <= 0 or config.max_daily_loss_pct > 100:
        raise ValueError("max_daily_loss_pct must be in (0, 100]")


def set_kill_switch(state: PortfolioSafetyState, active: bool) -> None:
    """Explicitly enable/disable the persistent portfolio entry kill switch."""
    state.kill_switch_active = bool(active)


def assess_portfolio_safety(
    *,
    state: PortfolioSafetyState,
    timestamp: int,
    equity: float,
    open_positions: int,
    config: PortfolioSafetyConfig | None = None,
) -> PortfolioSafetyAssessment:
    """Evaluate whether the portfolio may open another position."""
    cfg = config or PortfolioSafetyConfig()
    _validate_config(cfg)
    if timestamp < 0:
        raise ValueError("timestamp must be >= 0")
    if equity <= 0:
        raise ValueError("equity must be > 0")
    if open_positions < 0:
        raise ValueError("open_positions must be >= 0")

    day_index = timestamp // DAY_MS
    if state.current_day_index != day_index or state.day_start_equity is None:
        state.current_day_index = day_index
        state.day_start_equity = equity

    baseline = state.day_start_equity
    daily_pnl_pct = (equity - baseline) / baseline * 100 if baseline > 0 else 0.0
    blockers: list[str] = []

    if state.kill_switch_active:
        blockers.append("PORTFOLIO_KILL_SWITCH_ACTIVE")
    if open_positions >= cfg.max_concurrent_positions:
        blockers.append("MAX_CONCURRENT_POSITIONS_REACHED")
    if daily_pnl_pct <= -cfg.max_daily_loss_pct:
        blockers.append("DAILY_LOSS_LIMIT_REACHED")

    return PortfolioSafetyAssessment(
        allow_new_entries=not blockers,
        open_positions=open_positions,
        daily_pnl_pct=round(daily_pnl_pct, 4),
        blockers=tuple(blockers),
    )


if __name__ == "__main__":
    print("Portfolio safety guards ready; paper entries only.")
