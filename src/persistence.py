"""
Paper Runner Persistence + Recovery
Wyckoff + SMC Spot Swing Agent

Serializes PaperSession + PaperRunnerState into a versioned JSON checkpoint and
restores them after restart. Writes use an atomic temp-file replace so a process
interruption is less likely to leave a partially written checkpoint.

Legacy checkpoints are migrated additively for MTM equity, portfolio safety,
and pending-entry state. This module stores no exchange credentials and sends no orders.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

try:
    from .paper_runner import PaperRunnerState
    from .paper_session import JournalEntry, PaperSession, SessionEquityPoint
    from .paper_trading import PaperAccount, PaperEvent, PaperPosition, PaperTrade
    from .portfolio_safety import PortfolioSafetyState
except ImportError:
    from paper_runner import PaperRunnerState
    from paper_session import JournalEntry, PaperSession, SessionEquityPoint
    from paper_trading import PaperAccount, PaperEvent, PaperPosition, PaperTrade
    from portfolio_safety import PortfolioSafetyState

CHECKPOINT_SCHEMA = "wyckoff-smc-paper-runner"
CHECKPOINT_VERSION = 1


@dataclass(frozen=True)
class CheckpointMetadata:
    schema: str = CHECKPOINT_SCHEMA
    version: int = CHECKPOINT_VERSION


@dataclass
class RecoveryResult:
    session: PaperSession | None
    runner_state: PaperRunnerState | None
    errors: list[str]

    @property
    def recovered(self) -> bool:
        return self.session is not None and self.runner_state is not None and not self.errors


def checkpoint_payload(session: PaperSession, runner_state: PaperRunnerState) -> dict[str, Any]:
    return {
        "metadata": asdict(CheckpointMetadata()),
        "runner_state": runner_state.to_dict(),
        "paper_session": session.to_dict(),
    }


def save_checkpoint(path: str | Path, session: PaperSession, runner_state: PaperRunnerState) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(target.name + ".tmp")
    payload = checkpoint_payload(session, runner_state)
    data = json.dumps(payload, indent=2, sort_keys=True, allow_nan=False)

    try:
        with temp.open("w", encoding="utf-8") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, target)
    finally:
        if temp.exists():
            temp.unlink()
    return target


def _position(raw: dict[str, Any] | None) -> PaperPosition | None:
    return None if raw is None else PaperPosition(**raw)


def _trade(raw: dict[str, Any]) -> PaperTrade:
    return PaperTrade(**raw)


def _event(raw: dict[str, Any]) -> PaperEvent:
    return PaperEvent(**raw)


def _legacy_open_entry_fee(raw: dict[str, Any]) -> float:
    if "unrealized_pnl" in raw:
        return 0.0
    position = raw.get("open_position")
    if not isinstance(position, dict):
        return 0.0
    return float(position.get("entry_fee_quote", 0.0) or 0.0)


def _account(raw: dict[str, Any]) -> PaperAccount:
    legacy_fee = _legacy_open_entry_fee(raw)
    return PaperAccount(
        initial_equity=raw["initial_equity"],
        equity=raw["equity"] - legacy_fee,
        realized_pnl=raw.get("realized_pnl", 0.0) - legacy_fee,
        open_position=_position(raw.get("open_position")),
        trades=[_trade(item) for item in raw.get("trades", [])],
        events=[_event(item) for item in raw.get("events", [])],
        last_processed_timestamp=raw.get("last_processed_timestamp"),
        cooldown_bars_remaining=raw.get("cooldown_bars_remaining", 0),
        unrealized_pnl=raw.get("unrealized_pnl", 0.0),
        mark_price=raw.get("mark_price"),
        pending_entry_price=raw.get("pending_entry_price"),
        pending_stop_price=raw.get("pending_stop_price"),
        pending_target_price=raw.get("pending_target_price"),
        pending_size_quote=raw.get("pending_size_quote", 0.0),
        pending_created_timestamp=raw.get("pending_created_timestamp"),
        pending_age_bars=raw.get("pending_age_bars", 0),
    )


def _portfolio_safety(raw: Any) -> PortfolioSafetyState:
    if not isinstance(raw, dict):
        return PortfolioSafetyState()
    return PortfolioSafetyState(
        kill_switch_active=bool(raw.get("kill_switch_active", False)),
        current_day_index=raw.get("current_day_index"),
        day_start_equity=raw.get("day_start_equity"),
    )


def _session(raw: dict[str, Any]) -> PaperSession:
    raw_accounts = raw.get("accounts", {})
    accounts = {symbol: _account(account) for symbol, account in raw_accounts.items()}
    legacy_fee = 0.0 if "unrealized_pnl" in raw else sum(_legacy_open_entry_fee(account) for account in raw_accounts.values())
    realized = raw.get("realized_pnl", 0.0) - legacy_fee
    unrealized = raw.get("unrealized_pnl", 0.0)
    equity = raw["equity"] if "unrealized_pnl" in raw else raw["initial_equity"] + realized + unrealized
    session = PaperSession(
        initial_equity=raw["initial_equity"],
        equity=equity,
        realized_pnl=realized,
        accounts=accounts,
        journal=[JournalEntry(**item) for item in raw.get("journal", [])],
        equity_curve=[SessionEquityPoint(**item) for item in raw.get("equity_curve", [])],
        action_counts=dict(raw.get("action_counts", {})),
        decisions=raw.get("decisions", 0),
        errors=list(raw.get("errors", [])),
        unrealized_pnl=unrealized,
        portfolio_safety=_portfolio_safety(raw.get("portfolio_safety")),
    )
    for account in session.accounts.values():
        account.equity = session.equity
    return session


def _runner_state(raw: dict[str, Any]) -> PaperRunnerState:
    return PaperRunnerState(
        last_cycle_time=raw.get("last_cycle_time"),
        cycles=raw.get("cycles", 0),
        errors=list(raw.get("errors", [])),
    )


def _validate_recovered(session: PaperSession, runner_state: PaperRunnerState) -> list[str]:
    errors: list[str] = []
    if session.initial_equity <= 0 or session.equity <= 0:
        errors.append("INVALID_CHECKPOINT_EQUITY")
    if runner_state.cycles < 0:
        errors.append("INVALID_CHECKPOINT_CYCLE_COUNT")
    if runner_state.last_cycle_time is not None and runner_state.last_cycle_time < 0:
        errors.append("INVALID_CHECKPOINT_CYCLE_TIME")

    safety = session.portfolio_safety
    if safety.current_day_index is not None and safety.current_day_index < 0:
        errors.append("INVALID_PORTFOLIO_SAFETY_DAY")
    if safety.day_start_equity is not None and safety.day_start_equity <= 0:
        errors.append("INVALID_PORTFOLIO_SAFETY_BASELINE")

    for symbol, account in session.accounts.items():
        if account.initial_equity <= 0 or account.equity <= 0:
            errors.append(f"INVALID_ACCOUNT_EQUITY:{symbol}")
        if account.last_processed_timestamp is not None and account.last_processed_timestamp < 0:
            errors.append(f"INVALID_ACCOUNT_TIMESTAMP:{symbol}")
        if account.cooldown_bars_remaining < 0:
            errors.append(f"INVALID_ACCOUNT_COOLDOWN:{symbol}")
        if account.pending_age_bars < 0 or account.pending_size_quote < 0:
            errors.append(f"INVALID_PENDING_ENTRY_STATE:{symbol}")
        pending_values = (account.pending_entry_price, account.pending_stop_price, account.pending_target_price)
        if any(value is not None and value <= 0 for value in pending_values):
            errors.append(f"INVALID_PENDING_ENTRY_PRICE:{symbol}")
        if account.pending_created_timestamp is not None and account.pending_created_timestamp < 0:
            errors.append(f"INVALID_PENDING_ENTRY_TIMESTAMP:{symbol}")
        if account.open_position is not None and account.pending_entry_price is not None:
            errors.append(f"POSITION_AND_PENDING_ENTRY_CONFLICT:{symbol}")
        if runner_state.last_cycle_time is not None and account.last_processed_timestamp is not None:
            if account.last_processed_timestamp > runner_state.last_cycle_time:
                errors.append(f"ACCOUNT_AHEAD_OF_RUNNER:{symbol}")
    return errors


def load_checkpoint(path: str | Path) -> RecoveryResult:
    target = Path(path)
    if not target.exists():
        return RecoveryResult(None, None, ["CHECKPOINT_NOT_FOUND"])

    try:
        with target.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return RecoveryResult(None, None, ["CHECKPOINT_CORRUPT"])

    try:
        metadata = payload["metadata"]
        if metadata.get("schema") != CHECKPOINT_SCHEMA:
            return RecoveryResult(None, None, ["CHECKPOINT_SCHEMA_MISMATCH"])
        if metadata.get("version") != CHECKPOINT_VERSION:
            return RecoveryResult(None, None, ["CHECKPOINT_VERSION_UNSUPPORTED"])
        session = _session(payload["paper_session"])
        runner_state = _runner_state(payload["runner_state"])
    except (KeyError, TypeError, ValueError):
        return RecoveryResult(None, None, ["CHECKPOINT_INVALID_SHAPE"])

    errors = _validate_recovered(session, runner_state)
    if errors:
        return RecoveryResult(None, None, errors)
    return RecoveryResult(session, runner_state, [])


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Paper runner persistence ready; versioned JSON checkpoints only.")
