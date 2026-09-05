import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from binance_adapter import BinanceMarketDataProvider
from binance_mcp_bridge import BinanceMCPClientBridge
from paper_runtime import PaperRuntimeConfig, create_paper_runtime, run_runtime_cycle
from paper_runner import PaperRunnerConfig


TIMEFRAME_MS = {
    "1d": 86_400_000,
    "4h": 14_400_000,
    "1h": 3_600_000,
    "15m": 900_000,
}


class IntegrationInvoker:
    def __init__(self):
        self.calls = []

    def invoke_tool(self, tool_name, arguments):
        self.calls.append((tool_name, dict(arguments)))
        interval = arguments["interval"]
        end_time = arguments["end_time"]
        limit = min(arguments["limit"], 60)
        duration = TIMEFRAME_MS[interval]
        first_open = end_time - limit * duration
        rows = []
        for i in range(limit):
            timestamp = first_open + i * duration
            base = 100.0 + i * 0.25
            rows.append([
                timestamp,
                str(base),
                str(base + 1.0),
                str(base - 1.0),
                str(base + 0.4),
                str(1_000 + i),
            ])
        return {"data": rows}


def test_mcp_bridge_adapter_runtime_end_to_end_paper_cycle(tmp_path: Path):
    decision_time = 200 * TIMEFRAME_MS["1d"]
    checkpoint = tmp_path / "paper_state.json"
    runtime_cfg = PaperRuntimeConfig(
        checkpoint_path=str(checkpoint),
        auto_recover=True,
        checkpoint_after_cycle=True,
        require_all_symbols=True,
    )

    invoker = IntegrationInvoker()
    client = BinanceMCPClientBridge(invoker)
    provider = BinanceMarketDataProvider(client)
    runtime = create_paper_runtime(symbols=["BTCUSDT"], runtime_config=runtime_cfg)

    result = run_runtime_cycle(
        runtime,
        provider,
        decision_time=decision_time,
        runtime_config=runtime_cfg,
        runner_config=PaperRunnerConfig(reference_timeframe="1h", require_exact_reference_close=True),
    )

    assert result.errors == []
    assert result.cycle is not None
    assert result.cycle.processed_symbols == 1
    assert result.cycle.skipped_symbols == 0
    assert result.checkpoint_saved is True
    assert checkpoint.exists()
    assert runtime.runner_state.last_cycle_time == decision_time
    assert runtime.runner_state.cycles == 1
    assert runtime.session.decisions == 1

    # One symbol x four required timeframes. No order/account tool exists in this bridge.
    assert len(invoker.calls) == 4
    assert {call[1]["interval"] for call in invoker.calls} == {"1d", "4h", "1h", "15m"}
    assert all(call[0] == "get_klines" for call in invoker.calls)

    recovered = create_paper_runtime(symbols=["BTCUSDT"], runtime_config=runtime_cfg)
    assert recovered.recovered is True
    replay = run_runtime_cycle(
        recovered,
        provider,
        decision_time=decision_time,
        runtime_config=runtime_cfg,
        runner_config=PaperRunnerConfig(reference_timeframe="1h", require_exact_reference_close=True),
    )
    assert replay.cycle is not None
    assert "NON_MONOTONIC_CYCLE_TIME" in replay.cycle.errors
    assert replay.checkpoint_saved is False
