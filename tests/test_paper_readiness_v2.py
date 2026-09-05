from types import SimpleNamespace

import src.paper_runner as runner
import src.paper_runtime as runtime_mod
from src.market_data import Candle, MarketData
from src.paper_readiness import evaluate_live_paper_readiness
from src.paper_runtime import PaperRuntimeConfig, create_paper_runtime, run_runtime_cycle
from src.paper_session import create_paper_session
from src.portfolio_safety import PortfolioSafetyConfig
from src.paper_trading import create_paper_account

HOUR = 3_600_000


def _market(symbol="BTCUSDT", close=100.0):
    candles = [Candle(0, close, close + 1, close - 1, close, 10)]
    return MarketData(symbol, close, candles, candles, candles, candles)


def _decision(symbol, confluence, scanner, action="ENTER_LONG"):
    return SimpleNamespace(symbol=symbol, action=action, confluence=SimpleNamespace(confidence=confluence), scan=SimpleNamespace(score=scanner))


def test_immutable_allocation_plan_selects_best_candidate_not_input_order(monkeypatch):
    quality = {"BTCUSDT": (65.0, 70.0), "ETHUSDT": (85.0, 80.0), "SOLUSDT": (75.0, 75.0)}
    monkeypatch.setattr(runner, "analyze_symbol", lambda market, **kwargs: _decision(market.symbol, *quality[market.symbol]))
    monkeypatch.setattr(runner, "process_session_snapshot", lambda session, market, **kwargs: SimpleNamespace(errors=[]))
    result = runner.run_paper_cycle(
        runner.PaperRunnerState(), create_paper_session(),
        [_market("BTCUSDT"), _market("SOLUSDT"), _market("ETHUSDT")],
        decision_time=HOUR,
        portfolio_safety_config=PortfolioSafetyConfig(max_concurrent_positions=1),
    )
    selected = [item for item in result.allocation_plan if item.status == "SELECTED"]
    rejected = [item for item in result.allocation_plan if item.reason == "PORTFOLIO_SLOT_EXHAUSTED"]
    assert [item.symbol for item in selected] == ["ETHUSDT"]
    assert {item.symbol for item in rejected} == {"BTCUSDT", "SOLUSDT"}


def test_same_time_retry_is_allowed_only_for_demonstrably_partial_cycle(monkeypatch):
    calls = []

    def fake_process(session, market, *, timestamp, **kwargs):
        calls.append(market.symbol)
        account = session.accounts.get(market.symbol) or create_paper_account()
        session.accounts[market.symbol] = account
        account.last_processed_timestamp = timestamp
        return SimpleNamespace(errors=[])

    monkeypatch.setattr(runner, "process_session_snapshot", fake_process)
    monkeypatch.setattr(runner, "analyze_symbol", lambda market, **kwargs: _decision(market.symbol, 50, 50, "WAIT"))
    state = runner.PaperRunnerState(last_cycle_time=HOUR, cycles=1)
    session = create_paper_session()
    btc = create_paper_account()
    btc.last_processed_timestamp = HOUR
    session.accounts["BTCUSDT"] = btc

    retry = runner.run_paper_cycle(state, session, [_market("BTCUSDT"), _market("ETHUSDT")], decision_time=HOUR)
    assert retry.retry is True
    assert calls == ["ETHUSDT"]
    assert state.cycles == 1
    assert retry.errors == []

    replay = runner.run_paper_cycle(state, session, [_market("BTCUSDT"), _market("ETHUSDT")], decision_time=HOUR)
    assert "NON_MONOTONIC_CYCLE_TIME" in replay.errors


def test_transient_provider_failure_does_not_poison_runtime(monkeypatch, tmp_path):
    cfg = PaperRuntimeConfig(checkpoint_path=str(tmp_path / "paper.json"), auto_recover=False, checkpoint_after_cycle=False)
    runtime = create_paper_runtime(symbols=["BTCUSDT"], runtime_config=cfg)

    class Flaky:
        def __init__(self): self.calls = 0
        def fetch_markets(self, symbols, *, decision_time):
            self.calls += 1
            if self.calls == 1: raise TimeoutError("temporary")
            return [_market("BTCUSDT")]

    monkeypatch.setattr(runtime_mod, "run_paper_cycle", lambda *args, **kwargs: runner.RunnerCycleResult(HOUR, 1, 0, [], []))
    provider = Flaky()
    first = run_runtime_cycle(runtime, provider, decision_time=HOUR, runtime_config=cfg)
    second = run_runtime_cycle(runtime, provider, decision_time=2 * HOUR, runtime_config=cfg)
    assert first.errors == ["MARKET_DATA_PROVIDER_ERROR:TimeoutError"]
    assert runtime.errors == []
    assert second.cycle is not None


def test_live_paper_readiness_requires_exact_closed_candle_and_safe_runtime(tmp_path):
    runtime_cfg = PaperRuntimeConfig(checkpoint_path="state/test-paper.json", auto_recover=True, checkpoint_after_cycle=True)
    runtime = create_paper_runtime(symbols=["BTCUSDT"], runtime_config=PaperRuntimeConfig(checkpoint_path=str(tmp_path / "missing.json"), auto_recover=False))
    blocked = evaluate_live_paper_readiness(runtime, runtime_config=runtime_cfg, runner_config=runner.PaperRunnerConfig())
    ready = evaluate_live_paper_readiness(runtime, runtime_config=runtime_cfg, runner_config=runner.PaperRunnerConfig(require_exact_reference_close=True))
    assert blocked.ready is False
    assert "EXACT_CLOSED_CANDLE_REQUIRED" in blocked.blockers
    assert ready.ready is True


def test_multi_cycle_runner_remains_monotonic_over_longer_paper_sequence(monkeypatch):
    monkeypatch.setattr(runner, "analyze_symbol", lambda market, **kwargs: _decision(market.symbol, 50, 50, "WAIT"))

    def fake_process(session, market, *, timestamp, **kwargs):
        account = session.accounts.get(market.symbol) or create_paper_account()
        session.accounts[market.symbol] = account
        account.last_processed_timestamp = timestamp
        return SimpleNamespace(errors=[])

    monkeypatch.setattr(runner, "process_session_snapshot", fake_process)
    state = runner.PaperRunnerState()
    session = create_paper_session()
    for i in range(1, 25):
        result = runner.run_paper_cycle(state, session, [_market("BTCUSDT"), _market("ETHUSDT")], decision_time=i * HOUR)
        assert result.errors == []
    assert state.cycles == 24
    assert state.last_cycle_time == 24 * HOUR
