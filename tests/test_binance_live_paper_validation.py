from src.binance_live_paper_validation import validate_binance_live_paper_feed
from src.binance_paper_host import live_binance_paper_host_config
from src.market_data import Candle, MarketData
from src.paper_runner import PaperRunnerConfig
from src.paper_runtime import PaperRuntimeConfig, create_paper_runtime

HOUR = 3_600_000
DAY = 86_400_000


def _series(step: int, count: int, end_time: int, close: float = 100.0):
    start = end_time - step * count
    return [Candle(start + i * step, close, close + 1, close - 1, close, 10.0) for i in range(count)]


def _market(symbol: str, decision_time: int, *, stale_reference: bool = False):
    reference_end = decision_time - HOUR if stale_reference else decision_time
    return MarketData(
        symbol,
        None,
        _series(DAY, 2, decision_time),
        _series(4 * HOUR, 3, decision_time),
        _series(HOUR, 4, reference_end),
        _series(15 * 60_000, 8, decision_time),
    )


class Provider:
    def __init__(self, markets):
        self.markets = markets

    def fetch_markets(self, symbols, *, decision_time):
        return self.markets


def _runtime(tmp_path, symbols=("BTCUSDT",)):
    return create_paper_runtime(
        symbols=list(symbols),
        runtime_config=PaperRuntimeConfig(
            checkpoint_path="state/live-test.json",
            auto_recover=False,
            checkpoint_after_cycle=True,
            require_all_symbols=True,
        ),
    )


def test_live_safe_host_config_is_exact_closed_candle_spot():
    cfg = live_binance_paper_host_config()
    assert cfg.agent.trading_mode == "SPOT"
    assert cfg.execution.trading_mode == "SPOT"
    assert cfg.runner.require_exact_reference_close is True
    assert cfg.runner.fair_same_cycle_allocation is True
    assert cfg.runtime.require_all_symbols is True
    assert cfg.runtime.checkpoint_path.startswith("state/")


def test_preflight_passes_fresh_complete_feed_without_mutating_runtime(tmp_path):
    decision_time = 10 * DAY
    runtime = _runtime(tmp_path)
    before_session = runtime.session.to_dict()
    before_state = runtime.runner_state.to_dict()

    result = validate_binance_live_paper_feed(
        runtime,
        Provider([_market("BTCUSDT", decision_time)]),
        decision_time=decision_time,
        runtime_config=PaperRuntimeConfig(
            checkpoint_path="state/live-test.json",
            auto_recover=True,
            checkpoint_after_cycle=True,
            require_all_symbols=True,
        ),
        runner_config=PaperRunnerConfig(require_exact_reference_close=True),
    )

    assert result.ready is True
    assert result.blockers == ()
    assert result.symbols[0].valid is True
    assert runtime.session.to_dict() == before_session
    assert runtime.runner_state.to_dict() == before_state


def test_preflight_blocks_stale_reference_candle(tmp_path):
    decision_time = 10 * DAY
    runtime = _runtime(tmp_path)
    result = validate_binance_live_paper_feed(
        runtime,
        Provider([_market("BTCUSDT", decision_time, stale_reference=True)]),
        decision_time=decision_time,
        runtime_config=PaperRuntimeConfig(
            checkpoint_path="state/live-test.json",
            auto_recover=True,
            checkpoint_after_cycle=True,
        ),
        runner_config=PaperRunnerConfig(require_exact_reference_close=True),
    )

    assert result.ready is False
    assert "BTCUSDT:REFERENCE_CANDLE_NOT_FRESH" in result.blockers


def test_preflight_blocks_missing_symbol(tmp_path):
    decision_time = 10 * DAY
    runtime = _runtime(tmp_path, symbols=("BTCUSDT", "ETHUSDT"))
    result = validate_binance_live_paper_feed(
        runtime,
        Provider([_market("BTCUSDT", decision_time)]),
        decision_time=decision_time,
        runtime_config=PaperRuntimeConfig(
            checkpoint_path="state/live-test.json",
            auto_recover=True,
            checkpoint_after_cycle=True,
            require_all_symbols=True,
        ),
        runner_config=PaperRunnerConfig(require_exact_reference_close=True),
    )

    assert result.ready is False
    assert result.missing_symbols == ("ETHUSDT",)
    assert "MISSING_PROVIDER_SYMBOLS:ETHUSDT" in result.blockers


def test_preflight_provider_error_is_non_mutating_and_explicit(tmp_path):
    class Broken:
        def fetch_markets(self, symbols, *, decision_time):
            raise TimeoutError("temporary")

    runtime = _runtime(tmp_path)
    result = validate_binance_live_paper_feed(
        runtime,
        Broken(),
        decision_time=10 * DAY,
        runtime_config=PaperRuntimeConfig(
            checkpoint_path="state/live-test.json",
            auto_recover=True,
            checkpoint_after_cycle=True,
        ),
        runner_config=PaperRunnerConfig(require_exact_reference_close=True),
    )

    assert result.ready is False
    assert "MARKET_DATA_PROVIDER_ERROR:TimeoutError" in result.blockers
    assert runtime.runner_state.cycles == 0
    assert runtime.errors == []
