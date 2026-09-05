"""Tests for the provider-agnostic paper runtime boundary."""

import json
from pathlib import Path

from src.market_data import Candle, MarketData
from src.paper_runtime import PaperRuntimeConfig, create_paper_runtime, run_runtime_cycle
from src.persistence import load_checkpoint

HOUR = 3_600_000
DAY = 86_400_000
FOUR_HOUR = 14_400_000
FIFTEEN = 900_000


def _market(symbol: str, close: float = 100.0) -> MarketData:
    return MarketData(
        symbol=symbol,
        current_price=999.0,
        daily=[Candle(0, close, close + 1, close - 1, close, 10)],
        four_hour=[Candle(0, close, close + 1, close - 1, close, 10)],
        one_hour=[Candle(0, close, close + 1, close - 1, close, 10)],
        fifteen_minute=[Candle(0, close, close + 1, close - 1, close, 10)],
    )


class FakeProvider:
    def __init__(self, markets):
        self.markets = markets
        self.calls = []

    def fetch_markets(self, symbols, *, decision_time):
        self.calls.append((tuple(symbols), decision_time))
        return list(self.markets)


class BrokenProvider:
    def fetch_markets(self, symbols, *, decision_time):
        raise RuntimeError("feed unavailable")


def test_first_start_creates_fresh_runtime_when_checkpoint_missing(tmp_path: Path) -> None:
    checkpoint = tmp_path / "state.json"
    runtime = create_paper_runtime(
        symbols=["btcusdt", "ETHUSDT"],
        runtime_config=PaperRuntimeConfig(checkpoint_path=str(checkpoint)),
    )
    assert runtime.recovered is False
    assert runtime.errors == []
    assert runtime.symbols == ("BTCUSDT", "ETHUSDT")
    assert runtime.runner_state.last_cycle_time is None


def test_runtime_fetches_requested_symbols_runs_cycle_and_checkpoints(tmp_path: Path) -> None:
    checkpoint = tmp_path / "state.json"
    runtime = create_paper_runtime(
        symbols=["BTCUSDT", "ETHUSDT"],
        runtime_config=PaperRuntimeConfig(checkpoint_path=str(checkpoint)),
    )
    provider = FakeProvider([_market("BTCUSDT"), _market("ETHUSDT", 200.0)])
    result = run_runtime_cycle(
        runtime,
        provider,
        decision_time=DAY,
        runtime_config=PaperRuntimeConfig(checkpoint_path=str(checkpoint)),
    )
    assert provider.calls == [(runtime.symbols, DAY)]
    assert result.cycle is not None
    assert result.cycle.processed_symbols == 2
    assert result.checkpoint_saved is True
    assert checkpoint.exists()
    assert runtime.runner_state.last_cycle_time == DAY


def test_runtime_recovers_checkpoint_and_refuses_same_cycle_replay(tmp_path: Path) -> None:
    checkpoint = tmp_path / "state.json"
    cfg = PaperRuntimeConfig(checkpoint_path=str(checkpoint))
    runtime = create_paper_runtime(symbols=["BTCUSDT"], runtime_config=cfg)
    first = run_runtime_cycle(runtime, FakeProvider([_market("BTCUSDT")]), decision_time=DAY, runtime_config=cfg)
    assert first.checkpoint_saved is True

    recovered = create_paper_runtime(symbols=["BTCUSDT"], runtime_config=cfg)
    assert recovered.recovered is True
    assert recovered.runner_state.last_cycle_time == DAY

    replay = run_runtime_cycle(recovered, FakeProvider([_market("BTCUSDT")]), decision_time=DAY, runtime_config=cfg)
    assert replay.cycle is not None
    assert "NON_MONOTONIC_CYCLE_TIME" in replay.cycle.errors
    assert replay.checkpoint_saved is False


def test_provider_exception_does_not_advance_timeline(tmp_path: Path) -> None:
    checkpoint = tmp_path / "state.json"
    runtime = create_paper_runtime(
        symbols=["BTCUSDT"],
        runtime_config=PaperRuntimeConfig(checkpoint_path=str(checkpoint), auto_recover=False),
    )
    result = run_runtime_cycle(runtime, BrokenProvider(), decision_time=DAY)
    assert result.cycle is None
    assert result.checkpoint_saved is False
    assert result.errors == ["MARKET_DATA_PROVIDER_ERROR:RuntimeError"]
    assert runtime.runner_state.last_cycle_time is None


def test_partial_provider_batch_is_allowed_by_default_and_missing_is_reported(tmp_path: Path) -> None:
    runtime = create_paper_runtime(
        symbols=["BTCUSDT", "ETHUSDT"],
        runtime_config=PaperRuntimeConfig(checkpoint_path=str(tmp_path / "state.json"), auto_recover=False),
    )
    result = run_runtime_cycle(runtime, FakeProvider([_market("BTCUSDT")]), decision_time=DAY)
    assert result.cycle is not None
    assert result.cycle.processed_symbols == 1
    assert result.missing_symbols == ["ETHUSDT"]
    assert any(error.startswith("MISSING_PROVIDER_SYMBOLS") for error in result.errors)


def test_require_all_symbols_blocks_partial_batch_without_mutating_state(tmp_path: Path) -> None:
    cfg = PaperRuntimeConfig(checkpoint_path=str(tmp_path / "state.json"), auto_recover=False, require_all_symbols=True)
    runtime = create_paper_runtime(symbols=["BTCUSDT", "ETHUSDT"], runtime_config=cfg)
    result = run_runtime_cycle(runtime, FakeProvider([_market("BTCUSDT")]), decision_time=DAY, runtime_config=cfg)
    assert result.cycle is None
    assert result.checkpoint_saved is False
    assert runtime.runner_state.last_cycle_time is None
    assert result.missing_symbols == ["ETHUSDT"]


def test_unexpected_provider_symbol_is_fail_closed(tmp_path: Path) -> None:
    runtime = create_paper_runtime(
        symbols=["BTCUSDT"],
        runtime_config=PaperRuntimeConfig(checkpoint_path=str(tmp_path / "state.json"), auto_recover=False),
    )
    result = run_runtime_cycle(runtime, FakeProvider([_market("SOLUSDT")]), decision_time=DAY)
    assert result.cycle is None
    assert "UNEXPECTED_PROVIDER_SYMBOLS:SOLUSDT" in result.errors
    assert runtime.runner_state.last_cycle_time is None


def test_corrupt_checkpoint_makes_runtime_fail_closed(tmp_path: Path) -> None:
    checkpoint = tmp_path / "state.json"
    checkpoint.write_text("{bad-json", encoding="utf-8")
    runtime = create_paper_runtime(
        symbols=["BTCUSDT"],
        runtime_config=PaperRuntimeConfig(checkpoint_path=str(checkpoint)),
    )
    assert runtime.recovered is False
    assert runtime.errors == ["RECOVERY_FAILED:CHECKPOINT_CORRUPT"]
    result = run_runtime_cycle(runtime, FakeProvider([_market("BTCUSDT")]), decision_time=DAY)
    assert result.cycle is None
    assert result.errors == runtime.errors


def test_checkpoint_contains_consumed_runtime_after_cycle(tmp_path: Path) -> None:
    checkpoint = tmp_path / "state.json"
    cfg = PaperRuntimeConfig(checkpoint_path=str(checkpoint), auto_recover=False)
    runtime = create_paper_runtime(symbols=["BTCUSDT"], runtime_config=cfg)
    result = run_runtime_cycle(runtime, FakeProvider([_market("BTCUSDT")]), decision_time=DAY, runtime_config=cfg)
    assert result.checkpoint_saved is True
    recovery = load_checkpoint(checkpoint)
    assert recovery.recovered is True
    assert recovery.runner_state is not None
    assert recovery.runner_state.last_cycle_time == DAY
    assert recovery.runner_state.cycles == 1
