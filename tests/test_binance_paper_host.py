from pathlib import Path

from src.binance_paper_host import (
    BinancePaperHostConfig,
    CallableMCPInvoker,
    create_binance_paper_host,
    run_binance_paper_cycle,
    run_binance_paper_cycle_with_report,
)
from src.paper_report import render_paper_cycle_report
from src.paper_runtime import PaperRuntimeConfig


HOUR = 3_600_000
DAY = 86_400_000


def _klines(interval: str, count: int = 80):
    duration = {"1d": DAY, "4h": 4 * HOUR, "1h": HOUR, "15m": HOUR // 4}[interval]
    rows = []
    for i in range(count):
        ts = i * duration
        price = 100.0 + i * 0.1
        rows.append([ts, str(price), str(price + 1), str(price - 1), str(price + 0.2), "1000"])
    return rows


class FakeHostToolCall:
    def __init__(self):
        self.calls = []

    def __call__(self, tool_name, arguments):
        self.calls.append((tool_name, dict(arguments)))
        return {"data": _klines(arguments["interval"])}


def test_callable_invoker_wraps_host_function():
    calls = []

    def tool_call(name, arguments):
        calls.append((name, arguments))
        return {"ok": True}

    invoker = CallableMCPInvoker(tool_call)
    assert invoker.invoke_tool("x", {"a": 1}) == {"ok": True}
    assert calls == [("x", {"a": 1})]


def test_callable_invoker_rejects_non_callable():
    try:
        CallableMCPInvoker(None)  # type: ignore[arg-type]
    except TypeError as exc:
        assert "tool_call must be callable" in str(exc)
    else:
        raise AssertionError("expected TypeError")


def test_host_runs_end_to_end_paper_cycle_and_saves_checkpoint(tmp_path: Path):
    checkpoint = tmp_path / "paper.json"
    tool_call = FakeHostToolCall()
    config = BinancePaperHostConfig(
        runtime=PaperRuntimeConfig(
            checkpoint_path=str(checkpoint),
            auto_recover=False,
            checkpoint_after_cycle=True,
        )
    )
    host = create_binance_paper_host(
        tool_call,
        symbols=["BTCUSDT", "ETHUSDT"],
        config=config,
    )

    decision_time = 80 * DAY
    result = run_binance_paper_cycle(host, decision_time=decision_time)

    assert result.cycle is not None
    assert result.cycle.processed_symbols == 2
    assert result.checkpoint_saved is True
    assert checkpoint.exists()
    assert host.runtime.runner_state.last_cycle_time == decision_time
    assert len(tool_call.calls) == 8
    assert {args["symbol"] for _, args in tool_call.calls} == {"BTCUSDT", "ETHUSDT"}
    assert {args["interval"] for _, args in tool_call.calls} == {"1d", "4h", "1h", "15m"}


def test_host_can_return_operator_report_with_cycle_result(tmp_path: Path):
    checkpoint = tmp_path / "paper.json"
    tool_call = FakeHostToolCall()
    config = BinancePaperHostConfig(
        runtime=PaperRuntimeConfig(
            checkpoint_path=str(checkpoint),
            auto_recover=False,
            checkpoint_after_cycle=True,
        )
    )
    host = create_binance_paper_host(tool_call, symbols=["BTCUSDT"], config=config)

    output = run_binance_paper_cycle_with_report(host, decision_time=80 * DAY)

    assert output.result.checkpoint_saved is True
    assert output.report.decision_time == 80 * DAY
    assert output.report.processed_symbols == 1
    assert output.report.symbols[0].symbol == "BTCUSDT"
    text = render_paper_cycle_report(output.report)
    assert "PAPER CYCLE" in text
    assert "BTCUSDT" in text
    assert "Scanner:" in text
    assert "Wyckoff:" in text
    assert "SMC:" in text
    assert "Confluence:" in text
    assert "Thesis:" in text
    assert "Risk:" in text
    assert "Execution:" in text


def test_host_recovery_blocks_replaying_same_cycle(tmp_path: Path):
    checkpoint = tmp_path / "paper.json"
    tool_call = FakeHostToolCall()
    config = BinancePaperHostConfig(
        runtime=PaperRuntimeConfig(
            checkpoint_path=str(checkpoint),
            auto_recover=True,
            checkpoint_after_cycle=True,
        )
    )

    decision_time = 80 * DAY
    first = create_binance_paper_host(tool_call, symbols=["BTCUSDT"], config=config)
    first_result = run_binance_paper_cycle(first, decision_time=decision_time)
    assert first_result.checkpoint_saved is True

    recovered = create_binance_paper_host(tool_call, symbols=["BTCUSDT"], config=config)
    assert recovered.runtime.recovered is True

    replay = run_binance_paper_cycle(recovered, decision_time=decision_time)
    assert replay.cycle is not None
    assert "NON_MONOTONIC_CYCLE_TIME" in replay.cycle.errors
    assert replay.checkpoint_saved is False


def test_host_config_remains_spot_and_paper_only_by_default():
    cfg = BinancePaperHostConfig()
    assert cfg.agent.trading_mode == "SPOT"
    assert cfg.risk.trading_mode == "SPOT"
    assert cfg.execution.trading_mode == "SPOT"
