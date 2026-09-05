from src.binance_watchlist_acquisition import (
    BinanceWatchlistAcquisitionConfig,
    acquire_and_validate_watchlist,
    acquire_binance_watchlist,
    aligned_hour_decision_time,
)
from src.scanner import WatchlistSymbol


HOUR = 3_600_000
DAY = 86_400_000
CAPTURED_AT = 100 * DAY + 37 * 60_000


class RemoteError(RuntimeError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def _klines(step, count, decision_time, close=100.0):
    start = decision_time - step * (count - 1)
    return [
        [start + i * step, str(close), str(close + 1), str(close - 1), str(close), "10"]
        for i in range(count)
    ]


class FakeClient:
    def __init__(self, failures=None):
        self.failures = dict(failures or {})
        self.calls = []

    def _maybe_fail(self, key):
        self.calls.append(key)
        queued = self.failures.get(key, [])
        if queued:
            raise queued.pop(0)

    def get_price(self, symbol):
        self._maybe_fail((symbol, "price"))
        return {"symbol": symbol, "price": "100.0"}

    def get_klines(self, symbol, interval, *, limit, end_time):
        self._maybe_fail((symbol, interval))
        step = {"1d": DAY, "4h": 4 * HOUR, "1h": HOUR, "15m": 900_000}[interval]
        # Final raw candle opens exactly at decision time and is intentionally
        # left for the downstream closed-candle gate to remove.
        return _klines(step, limit, end_time)


def _watchlist():
    return [WatchlistSymbol("BTCUSDT", "HIGH"), WatchlistSymbol("ETHUSDT", "HIGH")]


def test_decision_time_is_aligned_to_last_complete_hour_boundary():
    assert aligned_hour_decision_time(CAPTURED_AT) == 100 * DAY


def test_transient_rate_limit_retries_only_failed_request_and_preserves_successes():
    client = FakeClient({
        ("BTCUSDT", "1d"): [RemoteError("UNAVAILABLE", "-1003 too much request weight")],
    })
    sleeps = []
    result = acquire_binance_watchlist(
        client,
        _watchlist(),
        captured_at=CAPTURED_AT,
        config=BinanceWatchlistAcquisitionConfig(max_attempts=3, initial_backoff_seconds=0.5),
        sleep_fn=sleeps.append,
    )

    assert result.complete is True
    assert result.failures == []
    assert result.attempts["BTCUSDT:1D"] == 2
    assert result.attempts["BTCUSDT:4H"] == 1
    assert client.calls.count(("BTCUSDT", "1d")) == 2
    assert client.calls.count(("BTCUSDT", "4h")) == 1
    assert sleeps == [0.5]


def test_permanent_malformed_response_is_not_retried():
    class Malformed(FakeClient):
        def get_klines(self, symbol, interval, *, limit, end_time):
            if symbol == "BTCUSDT" and interval == "4h":
                self.calls.append((symbol, interval))
                return {"not": "klines"}
            return super().get_klines(symbol, interval, limit=limit, end_time=end_time)

    client = Malformed()
    result = acquire_binance_watchlist(client, _watchlist(), captured_at=CAPTURED_AT, sleep_fn=lambda _: None)

    assert result.complete is False
    assert result.incomplete_symbols == ["BTCUSDT"]
    assert result.completed_symbols == ["ETHUSDT"]
    assert result.attempts["BTCUSDT:4H"] == 1
    assert result.failures[0].retryable is False


def test_retry_exhaustion_emits_incomplete_and_never_runs_validation(monkeypatch):
    client = FakeClient({
        ("BTCUSDT", "price"): [
            TimeoutError("timeout"), TimeoutError("timeout"), TimeoutError("timeout")
        ],
    })
    monkeypatch.setattr(
        "src.binance_watchlist_acquisition.validate_watchlist_batch",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not validate incomplete batch")),
    )
    result = acquire_and_validate_watchlist(
        client,
        _watchlist(),
        captured_at=CAPTURED_AT,
        acquisition_config=BinanceWatchlistAcquisitionConfig(max_attempts=3, initial_backoff_seconds=0),
        sleep_fn=lambda _: None,
    )

    assert result.status == "INCOMPLETE"
    assert result.validation is None
    assert result.acquisition.incomplete_symbols == ["BTCUSDT"]
    assert result.acquisition.completed_symbols == ["ETHUSDT"]
    assert result.acquisition.attempts["BTCUSDT:price"] == 3


def test_symbol_groups_are_processed_in_watchlist_order_with_optional_pause():
    client = FakeClient()
    sleeps = []
    result = acquire_binance_watchlist(
        client,
        _watchlist(),
        captured_at=CAPTURED_AT,
        config=BinanceWatchlistAcquisitionConfig(
            symbols_per_group=1,
            group_pause_seconds=2.0,
        ),
        sleep_fn=sleeps.append,
    )

    assert result.complete is True
    assert result.completed_symbols == ["BTCUSDT", "ETHUSDT"]
    assert sleeps == [2.0]
    assert client.calls[:5] == [
        ("BTCUSDT", "price"),
        ("BTCUSDT", "1d"),
        ("BTCUSDT", "4h"),
        ("BTCUSDT", "1h"),
        ("BTCUSDT", "15m"),
    ]


def test_complete_acquisition_flows_into_paper_only_batch_validation():
    result = acquire_and_validate_watchlist(
        FakeClient(),
        _watchlist(),
        captured_at=CAPTURED_AT,
        acquisition_config=BinanceWatchlistAcquisitionConfig(
            symbols_per_group=1,
            group_pause_seconds=0,
        ),
        sleep_fn=lambda _: None,
    )

    assert result.status == "READY"
    assert result.acquisition.complete is True
    assert result.validation is not None
    assert result.validation.ready is True
    assert result.validation.paper_only is True
    assert result.validation.expected_symbols == ["BTCUSDT", "ETHUSDT"]
    assert all(item.decision is None for item in result.validation.symbols)
