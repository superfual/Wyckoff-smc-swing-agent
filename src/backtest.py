"""
Trade Simulation Backtest Engine
Wyckoff + SMC Spot Swing Agent

Consumes a time-correct ReplayResult and simulates one position at a time on
future reference-timeframe candles only. This layer does not alter historical
agent decisions and never sends exchange orders.

V1 assumptions:
- entries use the execution intent planned_entry generated at bar close
- only ENTER_LONG / ENTER_SHORT replay actions can open positions
- no overlapping positions for the same symbol
- stop/target checks start on the next bar (strict no-lookahead)
- if stop and target are both touched in one bar, stop wins conservatively
- fixed slippage and fees are modeled in basis points
- unresolved positions are marked-to-market on the final available close
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from math import inf
from typing import Literal

try:
    from .market_data import Candle, MarketData
    from .replay import ReplayResult
except ImportError:  # Allows: python src/backtest.py
    from market_data import Candle, MarketData
    from replay import ReplayResult


TradeDirection = Literal["LONG", "SHORT"]
TradeOutcome = Literal["WIN", "LOSS", "OPEN_END"]
ExitReason = Literal["TARGET", "STOP", "END_OF_DATA"]

_TIMEFRAME_FIELD = {
    "1d": "daily",
    "4h": "four_hour",
    "1h": "one_hour",
    "15m": "fifteen_minute",
}


@dataclass(frozen=True)
class BacktestConfig:
    fee_bps_per_side: float = 10.0
    slippage_bps_per_side: float = 2.0
    conservative_same_bar: bool = True


@dataclass
class SimulatedTrade:
    symbol: str
    direction: TradeDirection
    entry_bar_index: int
    exit_bar_index: int
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
    gross_r: float
    net_r: float
    outcome: TradeOutcome
    exit_reason: ExitReason
    confluence_classification: str | None
    confluence_confidence: float | None
    wyckoff_phase: str | None
    scanner_score: float

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class EquityPoint:
    bar_index: int
    timestamp: int
    equity: float


@dataclass
class BacktestResult:
    symbol: str
    initial_equity: float
    final_equity: float
    trades: list[SimulatedTrade]
    equity_curve: list[EquityPoint]
    total_trades: int
    wins: int
    losses: int
    open_end: int
    win_rate_pct: float
    expectancy_r: float
    profit_factor: float | None
    total_net_pnl: float
    total_return_pct: float
    max_drawdown_pct: float
    ignored_overlapping_entries: int
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _reference_candles(market: MarketData, timeframe: str) -> list[Candle]:
    field = _TIMEFRAME_FIELD.get(timeframe)
    if field is None:
        raise ValueError(f"Unsupported backtest timeframe: {timeframe}")
    return getattr(market, field)


def _entry_fill(direction: str, planned: float, slippage_bps: float) -> float:
    slip = slippage_bps / 10_000
    return planned * (1 + slip) if direction == "LONG" else planned * (1 - slip)


def _exit_fill(direction: str, planned: float, slippage_bps: float) -> float:
    slip = slippage_bps / 10_000
    return planned * (1 - slip) if direction == "LONG" else planned * (1 + slip)


def _pnl(direction: str, units: float, entry: float, exit_price: float) -> float:
    if direction == "LONG":
        return units * (exit_price - entry)
    return units * (entry - exit_price)


def _risk_per_unit(direction: str, entry: float, stop: float) -> float:
    return entry - stop if direction == "LONG" else stop - entry


def _bar_exit(direction: str, candle: Candle, stop: float, target: float, conservative: bool) -> tuple[float, ExitReason] | None:
    if direction == "LONG":
        stop_hit = candle.low <= stop
        target_hit = candle.high >= target
    else:
        stop_hit = candle.high >= stop
        target_hit = candle.low <= target

    if stop_hit and target_hit:
        return (stop, "STOP") if conservative else (target, "TARGET")
    if stop_hit:
        return stop, "STOP"
    if target_hit:
        return target, "TARGET"
    return None


def _max_drawdown_pct(curve: list[EquityPoint]) -> float:
    peak = 0.0
    max_dd = 0.0
    for point in curve:
        peak = max(peak, point.equity)
        if peak > 0:
            max_dd = max(max_dd, (peak - point.equity) / peak * 100)
    return max_dd


def run_backtest(
    replay: ReplayResult,
    market: MarketData,
    *,
    initial_equity: float,
    config: BacktestConfig | None = None,
) -> BacktestResult:
    """Simulate replay ENTER intents using future candles only."""

    cfg = config or BacktestConfig()
    errors: list[str] = []
    if replay.symbol != market.symbol:
        errors.append("SYMBOL_MISMATCH")
    if initial_equity <= 0:
        errors.append("INVALID_INITIAL_EQUITY")
    if cfg.fee_bps_per_side < 0 or cfg.slippage_bps_per_side < 0:
        errors.append("INVALID_BACKTEST_CONFIG")
    if replay.errors:
        errors.append("REPLAY_INVALID")

    if errors:
        return BacktestResult(replay.symbol, initial_equity, initial_equity, [], [], 0, 0, 0, 0, 0.0, 0.0, None, 0.0, 0.0, 0.0, 0, errors)

    candles = _reference_candles(market, replay.reference_timeframe)
    equity = initial_equity
    trades: list[SimulatedTrade] = []
    curve = [EquityPoint(-1, replay.first_decision_time or 0, equity)]
    ignored = 0
    occupied_until = -1

    for step in replay.steps:
        if step.action not in {"ENTER_LONG", "ENTER_SHORT"}:
            continue
        if step.bar_index <= occupied_until:
            ignored += 1
            continue

        execution = step.decision.execution
        if execution is None or not execution.allowed or execution.planned_entry is None:
            continue
        if execution.stop_price is None or execution.target_price is None:
            continue
        if execution.position_size_quote <= 0:
            continue

        direction: TradeDirection = "LONG" if step.action == "ENTER_LONG" else "SHORT"
        entry = _entry_fill(direction, execution.planned_entry, cfg.slippage_bps_per_side)
        stop = execution.stop_price
        target = execution.target_price
        risk_per_unit = _risk_per_unit(direction, entry, stop)
        if risk_per_unit <= 0:
            continue

        position_quote = min(execution.position_size_quote, equity)
        units = position_quote / entry
        entry_fee = position_quote * cfg.fee_bps_per_side / 10_000

        exit_price: float | None = None
        exit_reason: ExitReason | None = None
        exit_index: int | None = None

        # Strict no-lookahead: do not inspect the entry bar's high/low after a
        # decision formed at its close. Outcome checks start next bar.
        for index in range(step.bar_index + 1, len(candles)):
            hit = _bar_exit(direction, candles[index], stop, target, cfg.conservative_same_bar)
            if hit is None:
                continue
            planned_exit, exit_reason = hit
            exit_price = _exit_fill(direction, planned_exit, cfg.slippage_bps_per_side)
            exit_index = index
            break

        if exit_price is None:
            exit_index = len(candles) - 1
            if exit_index < step.bar_index:
                continue
            exit_reason = "END_OF_DATA"
            exit_price = _exit_fill(direction, candles[exit_index].close, cfg.slippage_bps_per_side)

        exit_notional = units * exit_price
        exit_fee = exit_notional * cfg.fee_bps_per_side / 10_000
        gross_pnl = _pnl(direction, units, entry, exit_price)
        fees = entry_fee + exit_fee
        net_pnl = gross_pnl - fees
        risk_quote = units * risk_per_unit
        gross_r = gross_pnl / risk_quote if risk_quote > 0 else 0.0
        net_r = net_pnl / risk_quote if risk_quote > 0 else 0.0
        equity += net_pnl

        outcome: TradeOutcome
        if exit_reason == "TARGET":
            outcome = "WIN"
        elif exit_reason == "STOP":
            outcome = "LOSS"
        else:
            outcome = "OPEN_END"

        confluence = step.decision.confluence
        wyckoff = step.decision.wyckoff
        trade = SimulatedTrade(
            symbol=replay.symbol,
            direction=direction,
            entry_bar_index=step.bar_index,
            exit_bar_index=exit_index,
            entry_time=step.decision_time,
            exit_time=candles[exit_index].timestamp,
            entry_price=round(entry, 8),
            exit_price=round(exit_price, 8),
            stop_price=round(stop, 8),
            target_price=round(target, 8),
            position_size_quote=round(position_quote, 8),
            gross_pnl_quote=round(gross_pnl, 8),
            fees_quote=round(fees, 8),
            net_pnl_quote=round(net_pnl, 8),
            gross_r=round(gross_r, 4),
            net_r=round(net_r, 4),
            outcome=outcome,
            exit_reason=exit_reason,
            confluence_classification=confluence.classification if confluence else None,
            confluence_confidence=confluence.confidence if confluence else None,
            wyckoff_phase=wyckoff.phase if wyckoff else None,
            scanner_score=step.decision.scan.score,
        )
        trades.append(trade)
        occupied_until = exit_index
        curve.append(EquityPoint(exit_index, candles[exit_index].timestamp, round(equity, 8)))

    wins = sum(t.outcome == "WIN" for t in trades)
    losses = sum(t.outcome == "LOSS" for t in trades)
    open_end = sum(t.outcome == "OPEN_END" for t in trades)
    total = len(trades)
    resolved = wins + losses
    win_rate = wins / resolved * 100 if resolved else 0.0
    expectancy = sum(t.net_r for t in trades) / total if total else 0.0
    gross_profit = sum(max(t.net_pnl_quote, 0.0) for t in trades)
    gross_loss = abs(sum(min(t.net_pnl_quote, 0.0) for t in trades))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else (inf if gross_profit > 0 else None)
    total_pnl = equity - initial_equity
    total_return = total_pnl / initial_equity * 100 if initial_equity else 0.0

    return BacktestResult(
        symbol=replay.symbol,
        initial_equity=round(initial_equity, 8),
        final_equity=round(equity, 8),
        trades=trades,
        equity_curve=curve,
        total_trades=total,
        wins=wins,
        losses=losses,
        open_end=open_end,
        win_rate_pct=round(win_rate, 4),
        expectancy_r=round(expectancy, 4),
        profit_factor=None if profit_factor is None else (profit_factor if profit_factor == inf else round(profit_factor, 4)),
        total_net_pnl=round(total_pnl, 8),
        total_return_pct=round(total_return, 4),
        max_drawdown_pct=round(_max_drawdown_pct(curve), 4),
        ignored_overlapping_entries=ignored,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Trade simulation backtest engine ready; no exchange orders are sent.")
