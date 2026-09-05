"""Tests for paper runner persistence and recovery."""

import json

from src.paper_runner import PaperRunnerState
from src.paper_session import JournalEntry, SessionEquityPoint, create_paper_session
from src.paper_trading import PaperEvent, PaperPosition, PaperTrade, create_paper_account
from src.persistence import CHECKPOINT_SCHEMA, CHECKPOINT_VERSION, load_checkpoint, save_checkpoint


def _rich_state():
    session = create_paper_session()
    account = create_paper_account()
    account.equity = 10125.0
    account.realized_pnl = 125.0
    account.unrealized_pnl = 20.0
    account.mark_price = 101.0
    account.last_processed_timestamp = 7_200_000
    account.cooldown_bars_remaining = 2
    account.open_position = PaperPosition(
        symbol="BTCUSDT", direction="LONG", entry_time=7_200_000,
        entry_price=100.0, stop_price=96.0, target_price=112.0,
        position_size_quote=2000.0, units=20.0, entry_fee_quote=2.0,
    )
    account.trades.append(PaperTrade(
        symbol="BTCUSDT", direction="LONG", entry_time=3_600_000, exit_time=7_200_000,
        entry_price=90.0, exit_price=96.0, stop_price=86.0, target_price=96.0,
        position_size_quote=1800.0, gross_pnl_quote=120.0, fees_quote=5.0,
        net_pnl_quote=115.0, net_r=1.4375, outcome="WIN", exit_reason="TARGET",
    ))
    account.events.append(PaperEvent(7_200_000, "OPEN", "ENTER_LONG", "Opened"))
    session.accounts["BTCUSDT"] = account
    session.equity = 10125.0
    session.realized_pnl = 105.0
    session.unrealized_pnl = 20.0
    session.decisions = 12
    session.action_counts = {"ENTER_LONG": 2, "WAIT": 10}
    session.journal.append(JournalEntry(7_200_000, "BTCUSDT", "ENTER_LONG", ["DECISION", "OPEN"], 10125.0, 19.75, "Opened"))
    session.equity_curve.append(SessionEquityPoint(7_200_000, 10125.0, 105.0, 19.75, 20.0))
    runner = PaperRunnerState(last_cycle_time=7_200_000, cycles=2, errors=["ETHUSDT:REFERENCE_CANDLE_NOT_FRESH"])
    return session, runner


def test_round_trip_restores_complete_state(tmp_path) -> None:
    session, runner = _rich_state()
    path = tmp_path / "paper-checkpoint.json"
    save_checkpoint(path, session, runner)
    recovered = load_checkpoint(path)

    assert recovered.recovered is True
    assert recovered.runner_state.last_cycle_time == 7_200_000
    assert recovered.runner_state.cycles == 2
    assert recovered.session.equity == 10125.0
    assert recovered.session.realized_pnl == 105.0
    assert recovered.session.unrealized_pnl == 20.0
    assert recovered.session.decisions == 12
    account = recovered.session.accounts["BTCUSDT"]
    assert account.last_processed_timestamp == 7_200_000
    assert account.cooldown_bars_remaining == 2
    assert account.open_position is not None
    assert account.open_position.entry_price == 100.0
    assert account.unrealized_pnl == 20.0
    assert account.mark_price == 101.0
    assert len(account.trades) == 1
    assert account.trades[0].exit_reason == "TARGET"
    assert recovered.session.journal[-1].action == "ENTER_LONG"


def test_checkpoint_has_versioned_schema(tmp_path) -> None:
    session, runner = _rich_state()
    path = save_checkpoint(tmp_path / "checkpoint.json", session, runner)
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload["metadata"] == {"schema": CHECKPOINT_SCHEMA, "version": CHECKPOINT_VERSION}


def test_legacy_open_position_migrates_unbooked_entry_fee(tmp_path) -> None:
    session, runner = _rich_state()
    path = save_checkpoint(tmp_path / "legacy.json", session, runner)
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw_session = payload["paper_session"]
    raw_session.pop("unrealized_pnl", None)
    raw_session["realized_pnl"] = 125.0
    raw_session["equity"] = 10125.0
    raw_account = raw_session["accounts"]["BTCUSDT"]
    raw_account.pop("unrealized_pnl", None)
    raw_account.pop("mark_price", None)
    raw_account["realized_pnl"] = 125.0
    raw_account["equity"] = 10125.0
    path.write_text(json.dumps(payload), encoding="utf-8")

    recovered = load_checkpoint(path)

    assert recovered.recovered is True
    assert recovered.session.realized_pnl == 123.0
    assert recovered.session.unrealized_pnl == 0.0
    assert recovered.session.equity == 10123.0
    account = recovered.session.accounts["BTCUSDT"]
    assert account.realized_pnl == 123.0
    assert account.unrealized_pnl == 0.0
    assert account.mark_price is None


def test_corrupt_json_is_rejected(tmp_path) -> None:
    path = tmp_path / "bad.json"
    path.write_text('{"metadata": ', encoding="utf-8")
    result = load_checkpoint(path)
    assert result.recovered is False
    assert result.errors == ["CHECKPOINT_CORRUPT"]


def test_wrong_schema_is_rejected(tmp_path) -> None:
    session, runner = _rich_state()
    path = save_checkpoint(tmp_path / "checkpoint.json", session, runner)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metadata"]["schema"] = "other-system"
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = load_checkpoint(path)
    assert result.errors == ["CHECKPOINT_SCHEMA_MISMATCH"]


def test_unknown_version_is_rejected(tmp_path) -> None:
    session, runner = _rich_state()
    path = save_checkpoint(tmp_path / "checkpoint.json", session, runner)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["metadata"]["version"] = 999
    path.write_text(json.dumps(payload), encoding="utf-8")
    result = load_checkpoint(path)
    assert result.errors == ["CHECKPOINT_VERSION_UNSUPPORTED"]


def test_account_cannot_be_ahead_of_runner(tmp_path) -> None:
    session, runner = _rich_state()
    runner.last_cycle_time = 3_600_000
    path = save_checkpoint(tmp_path / "checkpoint.json", session, runner)
    result = load_checkpoint(path)
    assert result.recovered is False
    assert "ACCOUNT_AHEAD_OF_RUNNER:BTCUSDT" in result.errors


def test_missing_checkpoint_is_reported(tmp_path) -> None:
    result = load_checkpoint(tmp_path / "missing.json")
    assert result.recovered is False
    assert result.errors == ["CHECKPOINT_NOT_FOUND"]


def test_atomic_save_leaves_no_temp_file(tmp_path) -> None:
    session, runner = _rich_state()
    target = tmp_path / "checkpoint.json"
    save_checkpoint(target, session, runner)
    assert target.exists()
    assert not (tmp_path / "checkpoint.json.tmp").exists()
