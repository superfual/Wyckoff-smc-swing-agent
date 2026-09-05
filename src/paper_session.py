"""
Multi-Symbol Paper Trading Session + Journal
Wyckoff + SMC Spot Swing Agent

Coordinates symbol-level PaperAccount instances under one shared virtual equity
and one shared portfolio exposure budget. Each market snapshot is processed
sequentially, so a newly opened position immediately consumes exposure before
the next symbol is evaluated.

No exchange orders are sent.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from math import inf

try:
    from .execution import ExecutionConfig
    from .market_data import MarketData
    from .orchestrator import AgentConfig
    from .paper_trading import (
        PaperAccount,
        PaperEvent,
        PaperStepResult,
        PaperTrade,
        PaperTradingConfig,
        create_paper_account,
        process_paper_snapshot,
    )
    from .risk import RiskConfig
except ImportError:
    from execution import ExecutionConfig
    from market_data import MarketData
    from orchestrator import AgentConfig
    from paper_trading import (
        PaperAccount,
        PaperEvent,
        PaperStepResult,
        PaperTrade,
        PaperTradingConfig,
        create_paper_account,
        process_paper_snapshot,
    )
    from risk import RiskConfig


@dataclass(frozen=True)
class PaperSessionConfig:
    initial_equity: float = 10_000.0


@dataclass
class SessionEquityPoint:
    timestamp: int
    equity: float
    realized_pnl: float
    exposure_pct: float


@dataclass
class JournalEntry:
    timestamp: int
    symbol: str
    action: str
    event_kinds: list[str]
    equity: float
    exposure_pct: float
    note: str


@dataclass
class PaperSession:
    initial_equity: float
    equity: float
    realized_pnl: float = 0.0
    accounts: dict[str, PaperAccount] = field(default_factory=dict)
    journal: list[JournalEntry] = field(default_factory=list)
    equity_curve: list[SessionEquityPoint] = field(default_factory=list)
    action_counts: dict[str, int] = field(default_factory=dict)
    decisions: int = 0
    errors: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PaperSessionSummary:
    initial_equity: float
    equity: float
    realized_pnl: float
    return_pct: float
    total_decisions: int
    action_counts: dict[str, int]
    open_positions: int
    exposure_pct: float
    total_trades: int
    wins: int
    losses: int
    win_rate_pct: float
    expectancy_r: float
    profit_factor: float | None
    max_drawdown_pct: float
    symbols_seen: int
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def create_paper_session(config: PaperSessionConfig | None = None) -> PaperSession:
    cfg = config or PaperSessionConfig()
    if cfg.initial_equity <= 0:
        raise ValueError("initial_equity must be > 0")
    session = PaperSession(initial_equity=cfg.initial_equity, equity=cfg.initial_equity)
    session.equity_curve.append(SessionEquityPoint(0, cfg.initial_equity, 0.0, 0.0))
    return session


def _all_trades(session: PaperSession) -> list[PaperTrade]:
    return [trade for account in session.accounts.values() for trade in account.trades]


def _exposure_pct(session: PaperSession) -> float:
    if session.equity <= 0:
        return 0.0
    quote = sum(
        account.open_position.position_size_quote
        for account in session.accounts.values()
        if account.open_position is not None
    )
    return quote / session.equity * 100


def _sync_equity(session: PaperSession) -> None:
    for account in session.accounts.values():
        account.equity = session.equity


def process_session_snapshot(
    session: PaperSession,
    market: MarketData,
    *,
    timestamp: int,
    paper_config: PaperTradingConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
) -> PaperStepResult:
    """Process one symbol snapshot under shared session equity/exposure."""

    account = session.accounts.get(market.symbol)
    if account is None:
        cfg = paper_config or PaperTradingConfig(initial_equity=session.initial_equity)
        account = create_paper_account(cfg)
        account.equity = session.equity
        session.accounts[market.symbol] = account

    account.equity = session.equity
    before_realized = account.realized_pnl
    exposure_before = _exposure_pct(session)

    result = process_paper_snapshot(
        account,
        market,
        timestamp=timestamp,
        current_portfolio_exposure_pct=exposure_before,
        config=paper_config,
        agent_config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
    )

    if result.errors:
        session.errors.extend(f"{market.symbol}:{error}" for error in result.errors)
        return result

    realized_delta = account.realized_pnl - before_realized
    if realized_delta:
        session.realized_pnl += realized_delta
        session.equity = session.initial_equity + session.realized_pnl
        _sync_equity(session)

    if result.decision is not None:
        session.decisions += 1
        session.action_counts[result.decision.action] = session.action_counts.get(result.decision.action, 0) + 1

    exposure_after = _exposure_pct(session)
    note = "; ".join(event.note for event in result.events if event.kind in {"OPEN", "CLOSE"})
    session.journal.append(JournalEntry(
        timestamp=timestamp,
        symbol=market.symbol,
        action=result.decision.action if result.decision else "ERROR",
        event_kinds=[event.kind for event in result.events],
        equity=round(session.equity, 8),
        exposure_pct=round(exposure_after, 4),
        note=note,
    ))
    session.equity_curve.append(SessionEquityPoint(
        timestamp=timestamp,
        equity=round(session.equity, 8),
        realized_pnl=round(session.realized_pnl, 8),
        exposure_pct=round(exposure_after, 4),
    ))
    return result


def _max_drawdown_pct(curve: list[SessionEquityPoint]) -> float:
    peak = 0.0
    max_dd = 0.0
    for point in curve:
        peak = max(peak, point.equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - point.equity) / peak * 100)
    return max_dd


def summarize_paper_session(session: PaperSession) -> PaperSessionSummary:
    trades = _all_trades(session)
    wins = [trade for trade in trades if trade.outcome == "WIN"]
    losses = [trade for trade in trades if trade.outcome == "LOSS"]
    resolved = wins + losses
    win_rate = len(wins) / len(resolved) * 100 if resolved else 0.0
    expectancy = sum(trade.net_r for trade in trades) / len(trades) if trades else 0.0
    gross_profit = sum(max(trade.net_pnl_quote, 0.0) for trade in trades)
    gross_loss = abs(sum(min(trade.net_pnl_quote, 0.0) for trade in trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (inf if gross_profit > 0 else None)
    return_pct = session.realized_pnl / session.initial_equity * 100 if session.initial_equity else 0.0

    return PaperSessionSummary(
        initial_equity=round(session.initial_equity, 8),
        equity=round(session.equity, 8),
        realized_pnl=round(session.realized_pnl, 8),
        return_pct=round(return_pct, 4),
        total_decisions=session.decisions,
        action_counts=dict(session.action_counts),
        open_positions=sum(account.open_position is not None for account in session.accounts.values()),
        exposure_pct=round(_exposure_pct(session), 4),
        total_trades=len(trades),
        wins=len(wins),
        losses=len(losses),
        win_rate_pct=round(win_rate, 4),
        expectancy_r=round(expectancy, 4),
        profit_factor=None if profit_factor is None else (profit_factor if profit_factor == inf else round(profit_factor, 4)),
        max_drawdown_pct=round(_max_drawdown_pct(session.equity_curve), 4),
        symbols_seen=len(session.accounts),
        errors=list(session.errors),
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Multi-symbol paper session journal ready.")
