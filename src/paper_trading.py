"""
Paper Trading Engine
Wyckoff + SMC Spot Swing Agent

Processes one newly closed market snapshot at a time, runs the unchanged agent,
and manages a virtual position using only information available at that moment.
No exchange orders are sent and no future candles are inspected.

V1 is intentionally Spot-first: only ENTER_LONG can open a virtual position.
V1.1 books entry fees immediately and marks open positions to the latest closed
reference price so paper equity reflects unrealized PnL.
V1.2 accepts explicit portfolio-level entry blockers while continuing management
of already-open positions.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal, Sequence

try:
    from .execution import ExecutionConfig
    from .market_data import Candle, MarketData
    from .orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from .risk import RiskConfig
except ImportError:
    from execution import ExecutionConfig
    from market_data import Candle, MarketData
    from orchestrator import AgentConfig, AgentDecision, analyze_symbol
    from risk import RiskConfig

PaperEventKind = Literal["DECISION", "OPEN", "CLOSE", "BLOCK"]
PaperExitReason = Literal["STOP", "TARGET"]
PaperReferenceTimeframe = Literal["1d", "4h", "1h", "15m"]

_TIMEFRAME_FIELD = {
    "1d": "daily",
    "4h": "four_hour",
    "1h": "one_hour",
    "15m": "fifteen_minute",
}


@dataclass(frozen=True)
class PaperTradingConfig:
    initial_equity: float = 10_000.0
    fee_bps_per_side: float = 10.0
    slippage_bps_per_side: float = 2.0
    cooldown_bars_after_exit: int = 1
    conservative_same_bar: bool = True
    reference_timeframe: PaperReferenceTimeframe = "1h"


@dataclass
class PaperPosition:
    symbol: str
    direction: str
    entry_time: int
    entry_price: float
    stop_price: float
    target_price: float
    position_size_quote: float
    units: float
    entry_fee_quote: float


@dataclass
class PaperTrade:
    symbol: str
    direction: str
    entry_time: int
    exit_time: int
    entry_price: float
    exit_price: float
    stop_price: float
    target_price: float
    position_size_quote: float
    gross_pnl_quote: float
    fees_quote: float
    net_pnl_quote: float
    net_r: float
    outcome: str
    exit_reason: PaperExitReason


@dataclass
class PaperEvent:
    timestamp: int
    kind: PaperEventKind
    action: str
    note: str


@dataclass
class PaperAccount:
    initial_equity: float
    equity: float
    realized_pnl: float = 0.0
    open_position: PaperPosition | None = None
    trades: list[PaperTrade] = field(default_factory=list)
    events: list[PaperEvent] = field(default_factory=list)
    last_processed_timestamp: int | None = None
    cooldown_bars_remaining: int = 0
    unrealized_pnl: float = 0.0
    mark_price: float | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PaperStepResult:
    symbol: str
    timestamp: int
    decision: AgentDecision | None
    account: PaperAccount
    events: list[PaperEvent]
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def create_paper_account(config: PaperTradingConfig | None = None) -> PaperAccount:
    cfg = config or PaperTradingConfig()
    if cfg.initial_equity <= 0:
        raise ValueError("initial_equity must be > 0")
    return PaperAccount(initial_equity=cfg.initial_equity, equity=cfg.initial_equity)


def _entry_fill(price: float, slippage_bps: float) -> float:
    return price * (1 + slippage_bps / 10_000)


def _exit_fill(price: float, slippage_bps: float) -> float:
    return price * (1 - slippage_bps / 10_000)


def _reference_candle(market: MarketData, timeframe: str) -> Candle | None:
    field = _TIMEFRAME_FIELD.get(timeframe)
    if field is None:
        return None
    candles = getattr(market, field)
    return candles[-1] if candles else None


def _mark_to_market(account: PaperAccount, price: float) -> None:
    previous = account.unrealized_pnl
    position = account.open_position
    if position is None:
        current = 0.0
        account.mark_price = None
    else:
        current = position.units * (price - position.entry_price)
        account.mark_price = price
    account.unrealized_pnl = current
    account.equity += current - previous


def _close_position(account: PaperAccount, timestamp: int, planned_exit: float, reason: PaperExitReason, cfg: PaperTradingConfig) -> PaperTrade:
    position = account.open_position
    assert position is not None

    account.equity -= account.unrealized_pnl
    account.unrealized_pnl = 0.0
    account.mark_price = None

    exit_price = _exit_fill(planned_exit, cfg.slippage_bps_per_side)
    gross_pnl = position.units * (exit_price - position.entry_price)
    exit_fee = position.units * exit_price * cfg.fee_bps_per_side / 10_000
    total_fees = position.entry_fee_quote + exit_fee
    lifecycle_net_pnl = gross_pnl - total_fees
    close_realized_delta = gross_pnl - exit_fee
    risk_quote = position.units * (position.entry_price - position.stop_price)
    net_r = lifecycle_net_pnl / risk_quote if risk_quote > 0 else 0.0

    trade = PaperTrade(
        symbol=position.symbol,
        direction=position.direction,
        entry_time=position.entry_time,
        exit_time=timestamp,
        entry_price=round(position.entry_price, 8),
        exit_price=round(exit_price, 8),
        stop_price=round(position.stop_price, 8),
        target_price=round(position.target_price, 8),
        position_size_quote=round(position.position_size_quote, 8),
        gross_pnl_quote=round(gross_pnl, 8),
        fees_quote=round(total_fees, 8),
        net_pnl_quote=round(lifecycle_net_pnl, 8),
        net_r=round(net_r, 4),
        outcome="WIN" if reason == "TARGET" else "LOSS",
        exit_reason=reason,
    )
    account.realized_pnl += close_realized_delta
    account.equity += close_realized_delta
    account.trades.append(trade)
    account.open_position = None
    account.cooldown_bars_remaining = cfg.cooldown_bars_after_exit
    return trade


def _apply_entry_blockers(decision: AgentDecision, blockers: Sequence[str]) -> None:
    """Convert an otherwise executable fresh entry into an explicit portfolio block."""
    if not blockers or decision.action not in {"ENTER_LONG", "ENTER_SHORT"}:
        return
    unique = list(dict.fromkeys(str(item) for item in blockers if str(item)))
    if not unique:
        return
    execution = decision.execution
    if execution is not None:
        execution.allowed = False
        execution.state = "BLOCKED"
        execution.action = "BLOCKED"
        execution.position_size_quote = 0.0
        execution.position_size_units = 0.0
        execution.blockers.extend(item for item in unique if item not in execution.blockers)
        execution.interpretation = "Portfolio safety blocks a new entry even though symbol-level analysis passed."
    decision.action = "BLOCKED"
    decision.reasons.extend(f"Portfolio safety: {item}." for item in unique)
    decision.interpretation = "Symbol-level setup passed, but portfolio-level safety blocks new exposure."


def process_paper_snapshot(
    account: PaperAccount,
    market: MarketData,
    *,
    timestamp: int,
    current_portfolio_exposure_pct: float | None = None,
    config: PaperTradingConfig | None = None,
    agent_config: AgentConfig | None = None,
    risk_config: RiskConfig | None = None,
    execution_config: ExecutionConfig | None = None,
    entry_blockers: Sequence[str] = (),
) -> PaperStepResult:
    """Process exactly one newly closed market snapshot."""
    cfg = config or PaperTradingConfig(initial_equity=account.initial_equity)
    events: list[PaperEvent] = []
    errors: list[str] = []

    if timestamp < 0 or (account.last_processed_timestamp is not None and timestamp <= account.last_processed_timestamp):
        return PaperStepResult(market.symbol, timestamp, None, account, [], ["NON_MONOTONIC_TIMESTAMP"])
    if market.current_price is None or market.current_price <= 0:
        return PaperStepResult(market.symbol, timestamp, None, account, [], ["INVALID_CURRENT_PRICE"])
    if cfg.fee_bps_per_side < 0 or cfg.slippage_bps_per_side < 0 or cfg.cooldown_bars_after_exit < 0:
        return PaperStepResult(market.symbol, timestamp, None, account, [], ["INVALID_PAPER_CONFIG"])
    if cfg.reference_timeframe not in _TIMEFRAME_FIELD:
        return PaperStepResult(market.symbol, timestamp, None, account, [], ["INVALID_REFERENCE_TIMEFRAME"])
    if current_portfolio_exposure_pct is not None and not 0 <= current_portfolio_exposure_pct <= 100:
        return PaperStepResult(market.symbol, timestamp, None, account, [], ["INVALID_PORTFOLIO_EXPOSURE"])

    closed_this_step = False
    position = account.open_position
    if position is not None:
        candle = _reference_candle(market, cfg.reference_timeframe)
        if candle is not None:
            stop_hit = candle.low <= position.stop_price
            target_hit = candle.high >= position.target_price
            if stop_hit or target_hit:
                if stop_hit and target_hit:
                    reason: PaperExitReason = "STOP" if cfg.conservative_same_bar else "TARGET"
                else:
                    reason = "STOP" if stop_hit else "TARGET"
                planned_exit = position.stop_price if reason == "STOP" else position.target_price
                trade = _close_position(account, timestamp, planned_exit, reason, cfg)
                event = PaperEvent(timestamp, "CLOSE", reason, f"Virtual position closed at {trade.exit_price:.8f}; net PnL {trade.net_pnl_quote:.2f}.")
                events.append(event)
                account.events.append(event)
                closed_this_step = True

    if account.open_position is not None:
        _mark_to_market(account, market.current_price)

    cooldown_active = account.cooldown_bars_remaining > 0 or closed_this_step
    if current_portfolio_exposure_pct is None:
        exposure_pct = (account.open_position.position_size_quote / account.equity * 100) if account.open_position and account.equity > 0 else 0.0
    else:
        exposure_pct = current_portfolio_exposure_pct

    decision = analyze_symbol(
        market,
        account_equity=account.equity,
        current_portfolio_exposure_pct=exposure_pct,
        has_open_position=account.open_position is not None,
        cooldown_active=cooldown_active,
        config=agent_config,
        risk_config=risk_config,
        execution_config=execution_config,
    )
    pre_guard_action = decision.action
    _apply_entry_blockers(decision, entry_blockers)
    if decision.action == "BLOCKED" and pre_guard_action in {"ENTER_LONG", "ENTER_SHORT"}:
        block_note = ", ".join(dict.fromkeys(str(item) for item in entry_blockers if str(item)))
        event = PaperEvent(timestamp, "BLOCK", "BLOCKED", f"Portfolio safety blocked new exposure: {block_note}.")
        events.append(event)
        account.events.append(event)

    decision_event = PaperEvent(timestamp, "DECISION", decision.action, decision.interpretation)
    events.append(decision_event)
    account.events.append(decision_event)

    if decision.action == "ENTER_LONG" and decision.execution is not None and decision.execution.allowed and account.open_position is None and not cooldown_active:
        execution = decision.execution
        if execution.planned_entry is not None and execution.stop_price is not None and execution.target_price is not None and execution.position_size_quote > 0:
            entry = _entry_fill(execution.planned_entry, cfg.slippage_bps_per_side)
            size_quote = min(execution.position_size_quote, account.equity)
            units = size_quote / entry
            entry_fee = size_quote * cfg.fee_bps_per_side / 10_000
            account.realized_pnl -= entry_fee
            account.equity -= entry_fee
            account.open_position = PaperPosition(
                symbol=market.symbol,
                direction="LONG",
                entry_time=timestamp,
                entry_price=entry,
                stop_price=execution.stop_price,
                target_price=execution.target_price,
                position_size_quote=size_quote,
                units=units,
                entry_fee_quote=entry_fee,
            )
            _mark_to_market(account, market.current_price)
            event = PaperEvent(timestamp, "OPEN", "ENTER_LONG", f"Virtual long opened at {entry:.8f} with {size_quote:.2f} quote exposure; entry fee {entry_fee:.2f} booked.")
            events.append(event)
            account.events.append(event)

    if account.cooldown_bars_remaining > 0 and not closed_this_step:
        account.cooldown_bars_remaining -= 1

    account.last_processed_timestamp = timestamp
    return PaperStepResult(market.symbol, timestamp, decision, account, events, errors)


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Paper trading engine ready; virtual positions only.")
