"""Tests for the closed-candle paper trading runner."""

from types import SimpleNamespace

import src.paper_runner as runner
from src.market_data import Candle, MarketData
from src.paper_session import create_paper_session
from src.paper_trading import PaperPosition, PaperTradingConfig, create_paper_account

HOUR = 3_600_000
DAY = 86_400_000


def c(ts: int, close: float = 100.0, high: float | None = None, low: float | None = None) -> Candle:
    return Candle(ts, close, high if high is not None else close + 1, low if low is not None else close - 1, close, 10.0)


def market(symbol: str = "BTCUSDT", *, one_hour: list[Candle] | None = None) -> MarketData:
    one = one_hour if one_hour is not None else [c(0, 100.0), c(HOUR, 101.0)]
    return MarketData(
        symbol=symbol,
        current_price=999.0,
        daily=[c(0, 100.0)],
        four_hour=[c(0, 100.0)],
        one_hour=one,
        fifteen_minute=[c(0, 100.0), c(900_000, 100.5), c(1_800_000, 100.7), c(2_700_000, 100.9), c(HOUR, 101.0)],
    )


def _pre_decision(symbol: str, *, action: str = "ENTER_LONG", confluence: float = 70.0, scan: float = 70.0):
    return SimpleNamespace(
        symbol=symbol,
        action=action,
        confluence=SimpleNamespace(confidence=confluence),
        scan=SimpleNamespace(score=scan),
    )


def test_closed_snapshot_removes_unclosed_candles_and_derives_price_from_reference_close() -> None:
    m = market(one_hour=[c(0, 100.0), c(HOUR, 101.0), c(2 * HOUR, 500.0)])
    result = runner.build_closed_snapshot(m, decision_time=2 * HOUR, reference_timeframe="1h")
    assert [x.timestamp for x in result.one_hour] == [0, HOUR]
    assert result.current_price == 101.0
    assert all(x.timestamp + 900_000 <= 2 * HOUR for x in result.fifteen_minute)


def test_cycle_processes_each_unique_symbol_once(monkeypatch) -> None:
    calls: list[tuple[str, int, float]] = []

    def fake_process(session, closed, *, timestamp, **kwargs):
        calls.append((closed.symbol, timestamp, closed.current_price))
        return SimpleNamespace(errors=[])

    monkeypatch.setattr(runner, "process_session_snapshot", fake_process)
    monkeypatch.setattr(runner, "analyze_symbol", lambda m, **k: _pre_decision(m.symbol, action="WAIT"))
    state = runner.PaperRunnerState()
    session = create_paper_session()
    result = runner.run_paper_cycle(
        state,
        session,
        [market("BTCUSDT"), market("ETHUSDT")],
        decision_time=2 * HOUR,
    )
    assert result.processed_symbols == 2
    assert result.skipped_symbols == 0
    assert calls == [("BTCUSDT", 2 * HOUR, 101.0), ("ETHUSDT", 2 * HOUR, 101.0)]
    assert state.cycles == 1
    assert state.last_cycle_time == 2 * HOUR


def test_fair_allocation_ranks_best_fresh_candidate_before_watchlist_order(monkeypatch) -> None:
    calls: list[str] = []
    quality = {
        "BTCUSDT": (65.0, 70.0),
        "ETHUSDT": (82.0, 75.0),
        "SOLUSDT": (74.0, 90.0),
    }

    def fake_analyze(m, **kwargs):
        conf, scan = quality[m.symbol]
        return _pre_decision(m.symbol, confluence=conf, scan=scan)

    def fake_process(session, closed, *, timestamp, **kwargs):
        calls.append(closed.symbol)
        return SimpleNamespace(errors=[])

    monkeypatch.setattr(runner, "analyze_symbol", fake_analyze)
    monkeypatch.setattr(runner, "process_session_snapshot", fake_process)

    runner.run_paper_cycle(
        runner.PaperRunnerState(),
        create_paper_session(),
        [market("BTCUSDT"), market("SOLUSDT"), market("ETHUSDT")],
        decision_time=2 * HOUR,
    )

    assert calls == ["ETHUSDT", "SOLUSDT", "BTCUSDT"]


def test_fair_allocation_is_invariant_to_input_order(monkeypatch) -> None:
    quality = {"BTCUSDT": 65.0, "ETHUSDT": 85.0, "SOLUSDT": 75.0}

    def fake_analyze(m, **kwargs):
        return _pre_decision(m.symbol, confluence=quality[m.symbol], scan=70.0)

    monkeypatch.setattr(runner, "analyze_symbol", fake_analyze)

    def run_order(markets):
        calls: list[str] = []
        monkeypatch.setattr(runner, "process_session_snapshot", lambda session, closed, *, timestamp, **kwargs: (calls.append(closed.symbol) or SimpleNamespace(errors=[])))
        runner.run_paper_cycle(runner.PaperRunnerState(), create_paper_session(), markets, decision_time=2 * HOUR)
        return calls

    forward = run_order([market("BTCUSDT"), market("ETHUSDT"), market("SOLUSDT")])
    reverse = run_order([market("SOLUSDT"), market("BTCUSDT"), market("ETHUSDT")])
    assert forward == reverse == ["ETHUSDT", "SOLUSDT", "BTCUSDT"]


def test_active_position_lifecycle_is_serviced_before_fresh_candidates(monkeypatch) -> None:
    calls: list[str] = []
    session = create_paper_session()
    btc = create_paper_account()
    btc.open_position = PaperPosition("BTCUSDT", "LONG", 0, 100, 90, 120, 1000, 10, 1)
    session.accounts["BTCUSDT"] = btc

    monkeypatch.setattr(runner, "analyze_symbol", lambda m, **k: _pre_decision(m.symbol, confluence=99.0))
    monkeypatch.setattr(runner, "process_session_snapshot", lambda session, closed, *, timestamp, **kwargs: (calls.append(closed.symbol) or SimpleNamespace(errors=[])))

    runner.run_paper_cycle(
        runner.PaperRunnerState(),
        session,
        [market("ETHUSDT"), market("BTCUSDT")],
        decision_time=2 * HOUR,
    )
    assert calls[0] == "BTCUSDT"


def test_fair_allocation_can_be_disabled_for_research_comparison(monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(runner, "analyze_symbol", lambda m, **k: _pre_decision(m.symbol, confluence=99.0))
    monkeypatch.setattr(runner, "process_session_snapshot", lambda session, closed, *, timestamp, **kwargs: (calls.append(closed.symbol) or SimpleNamespace(errors=[])))

    runner.run_paper_cycle(
        runner.PaperRunnerState(),
        create_paper_session(),
        [market("SOLUSDT"), market("BTCUSDT")],
        decision_time=2 * HOUR,
        config=runner.PaperRunnerConfig(fair_same_cycle_allocation=False),
    )
    assert calls == ["SOLUSDT", "BTCUSDT"]


def test_duplicate_symbol_in_same_cycle_is_rejected(monkeypatch) -> None:
    calls: list[str] = []

    def fake_process(session, closed, *, timestamp, **kwargs):
        calls.append(closed.symbol)
        return SimpleNamespace(errors=[])

    monkeypatch.setattr(runner, "process_session_snapshot", fake_process)
    result = runner.run_paper_cycle(
        runner.PaperRunnerState(),
        create_paper_session(),
        [market("BTCUSDT"), market("BTCUSDT")],
        decision_time=2 * HOUR,
    )
    assert calls == ["BTCUSDT"]
    assert result.processed_symbols == 1
    assert result.skipped_symbols == 1
    assert "DUPLICATE_SYMBOL_IN_CYCLE" in result.symbol_results[0].errors


def test_non_monotonic_cycle_time_is_rejected_without_processing(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("should not process a repeated cycle")

    monkeypatch.setattr(runner, "process_session_snapshot", fail_if_called)
    state = runner.PaperRunnerState(last_cycle_time=2 * HOUR, cycles=1)
    result = runner.run_paper_cycle(state, create_paper_session(), [market()], decision_time=2 * HOUR)
    assert result.processed_symbols == 0
    assert "NON_MONOTONIC_CYCLE_TIME" in result.errors
    assert state.cycles == 1


def test_exact_reference_close_rejects_stale_snapshot(monkeypatch) -> None:
    def fail_if_called(*args, **kwargs):
        raise AssertionError("stale reference must not be processed")

    monkeypatch.setattr(runner, "process_session_snapshot", fail_if_called)
    cfg = runner.PaperRunnerConfig(require_exact_reference_close=True)
    result = runner.run_paper_cycle(
        runner.PaperRunnerState(), create_paper_session(), [market()], decision_time=3 * HOUR, config=cfg
    )
    assert result.skipped_symbols == 1
    assert "REFERENCE_CANDLE_NOT_FRESH" in result.symbol_results[0].errors


def test_missing_reference_candle_is_rejected() -> None:
    m = market(one_hour=[])
    result = runner.run_paper_cycle(
        runner.PaperRunnerState(), create_paper_session(), [m], decision_time=2 * HOUR
    )
    assert result.processed_symbols == 0
    assert "REFERENCE_CANDLE_UNAVAILABLE" in result.symbol_results[0].errors


def test_runner_and_paper_reference_timeframe_must_match() -> None:
    result = runner.run_paper_cycle(
        runner.PaperRunnerState(),
        create_paper_session(),
        [market()],
        decision_time=2 * HOUR,
        config=runner.PaperRunnerConfig(reference_timeframe="1h"),
        paper_config=PaperTradingConfig(reference_timeframe="15m"),
    )
    assert result.processed_symbols == 0
    assert "RUNNER_PAPER_TIMEFRAME_MISMATCH" in result.errors


def test_future_price_is_never_used_as_current_price() -> None:
    m = market(one_hour=[c(0, 100.0), c(HOUR, 101.0), c(2 * HOUR, 9999.0)])
    result = runner.build_closed_snapshot(m, decision_time=2 * HOUR)
    assert result.current_price == 101.0
    assert result.current_price != m.current_price
