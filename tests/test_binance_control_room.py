from copy import deepcopy
from pathlib import Path

from src.binance_paper_host import (
    BinancePaperHostConfig,
    create_binance_paper_host,
    render_binance_control_room_output,
    run_binance_control_room_cycle,
)
from src.binance_watchlist_acquisition import BinanceWatchlistAcquisitionConfig
from src.paper_runtime import PaperRuntimeConfig


HOUR = 3_600_000
DAY = 86_400_000
CAPTURED_AT = 100 * DAY + 37 * 60_000
DECISION_TIME = 100 * DAY


def _klines(interval: str, limit: int, end_time: int, *, stale: bool = False):
    step = {"1d": DAY, "4h": 4 * HOUR, "1h": HOUR, "15m": HOUR // 4}[interval]
    final_open = end_time - (2 * step if stale else 0)
    start = final_open - step * (limit - 1)
    return [
        [start + i * step, "100", "101", "99", "100", "10"]
        for i in range(limit)
    ]


class ControlRoomToolCall:
    def __init__(self, *, fail_price: bool = False, stale_one_hour: bool = False):
        self.fail_price = fail_price
        self.stale_one_hour = stale_one_hour
        self.calls = []

    def __call__(self, tool_name, arguments):
        self.calls.append((tool_name, dict(arguments)))
        if tool_name == "get_price":
            if self.fail_price and arguments["symbol"] == "BTCUSDT":
                return {"error": "invalid response"}
            return {"symbol": arguments["symbol"], "price": "9999"}
        interval = arguments["interval"]
        return {
            "data": _klines(
                interval,
                arguments["limit"],
                arguments["end_time"],
                stale=self.stale_one_hour and interval == "1h",
            )
        }


def _host(tmp_path: Path, tool_call: ControlRoomToolCall, symbols=("BTCUSDT",)):
    checkpoint = tmp_path / "control-room.json"
    config = BinancePaperHostConfig(
        runtime=PaperRuntimeConfig(
            checkpoint_path=str(checkpoint),
            auto_recover=False,
            checkpoint_after_cycle=True,
            require_all_symbols=True,
        )
    )
    return create_binance_paper_host(tool_call, symbols=symbols, config=config), checkpoint


def _state(host):
    return deepcopy(host.runtime.session.to_dict()), deepcopy(host.runtime.runner_state.to_dict())


def test_incomplete_acquisition_cannot_mutate_paper_state_or_checkpoint(tmp_path: Path):
    host, checkpoint = _host(tmp_path, ControlRoomToolCall(fail_price=True))
    before = _state(host)

    output = run_binance_control_room_cycle(
        host,
        captured_at=CAPTURED_AT,
        acquisition_config=BinanceWatchlistAcquisitionConfig(max_attempts=1),
        sleep_fn=lambda _: None,
    )

    assert output.status == "INCOMPLETE"
    assert output.result is None and output.report is None
    assert _state(host) == before
    assert checkpoint.exists() is False


def test_blocked_preflight_cannot_mutate_paper_state_or_checkpoint(tmp_path: Path):
    host, checkpoint = _host(tmp_path, ControlRoomToolCall(stale_one_hour=True))
    before = _state(host)

    output = run_binance_control_room_cycle(host, captured_at=CAPTURED_AT, sleep_fn=lambda _: None)

    assert output.status == "BLOCKED"
    assert output.pipeline.validation is not None
    assert any("REFERENCE_CANDLE_NOT_FRESH" in blocker for blocker in output.pipeline.validation.blockers)
    assert output.result is None and output.report is None
    assert _state(host) == before
    assert checkpoint.exists() is False


def test_ready_snapshot_runs_once_without_refetch_and_uses_closed_price(tmp_path: Path, monkeypatch):
    tool_call = ControlRoomToolCall()
    host, checkpoint = _host(tmp_path, tool_call, symbols=("BTCUSDT", "ETHUSDT"))
    received_prices = []
    from src import binance_paper_host

    original = binance_paper_host.run_runtime_cycle_with_markets

    def capture_markets(runtime, markets, **kwargs):
        received_prices.extend(market.current_price for market in markets)
        return original(runtime, markets, **kwargs)

    monkeypatch.setattr(binance_paper_host, "run_runtime_cycle_with_markets", capture_markets)

    output = run_binance_control_room_cycle(host, captured_at=CAPTURED_AT, sleep_fn=lambda _: None)

    assert output.status == "PAPER_CYCLE_COMPLETE"
    assert output.result is not None and output.result.processed is True
    assert output.report is not None and output.report.processed_symbols == 2
    assert output.decision_time == DECISION_TIME
    assert output.pipeline.acquisition.observed_prices == {"BTCUSDT": 9999.0, "ETHUSDT": 9999.0}
    assert len(tool_call.calls) == 10  # price + four timeframe requests, once per symbol
    assert received_prices == [100.0, 100.0]
    assert checkpoint.exists() is True
    rendered = render_binance_control_room_output(output)
    assert "PAPER_CYCLE_COMPLETE" in rendered
    assert "Mode: PAPER ONLY" in rendered
    assert "checkpoint=YES" in rendered


def test_control_room_rejects_runtime_symbol_outside_enabled_watchlist(tmp_path: Path):
    host, checkpoint = _host(tmp_path, ControlRoomToolCall(), symbols=("FAKEUSDT",))
    before = _state(host)

    try:
        run_binance_control_room_cycle(host, captured_at=CAPTURED_AT, sleep_fn=lambda _: None)
    except ValueError as exc:
        assert "not enabled" in str(exc)
    else:
        raise AssertionError("expected ValueError")

    assert _state(host) == before
    assert checkpoint.exists() is False
