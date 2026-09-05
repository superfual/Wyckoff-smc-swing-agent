from src.binance_adapter import (
    BinanceAdapterConfig,
    BinanceAdapterError,
    BinanceMarketDataProvider,
)

DAY = 86_400_000
H4 = 14_400_000
H1 = 3_600_000
M15 = 900_000


def _klines(step: int, count: int, base: float = 100.0):
    rows = []
    for i in range(count):
        price = base + i
        rows.append([i * step, str(price), str(price + 2), str(price - 2), str(price + 1), "10"])
    return rows


class FakeClient:
    def __init__(self):
        self.calls = []
        self.data = {
            "1d": _klines(DAY, 25),
            "4h": _klines(H4, 40),
            "1h": _klines(H1, 60),
            "15m": _klines(M15, 80),
        }

    def get_klines(self, symbol, interval, *, limit, end_time):
        self.calls.append((symbol, interval, limit, end_time))
        return self.data[interval][-limit:]


def test_provider_fetches_all_required_timeframes_and_normalizes_symbol():
    client = FakeClient()
    provider = BinanceMarketDataProvider(client)
    market = provider.fetch_market("btcusdt", decision_time=10 * DAY)

    assert market.symbol == "BTCUSDT"
    assert market.current_price is None
    assert len(market.daily) == 25
    assert len(market.four_hour) == 40
    assert len(market.one_hour) == 60
    assert len(market.fifteen_minute) == 80
    assert [call[1] for call in client.calls] == ["1d", "4h", "1h", "15m"]
    assert all(call[3] == 10 * DAY for call in client.calls)


def test_fetch_markets_preserves_requested_order():
    client = FakeClient()
    provider = BinanceMarketDataProvider(client)
    markets = provider.fetch_markets(["ETHUSDT", "BTCUSDT"], decision_time=DAY)
    assert [market.symbol for market in markets] == ["ETHUSDT", "BTCUSDT"]


def test_invalid_symbol_is_rejected():
    provider = BinanceMarketDataProvider(FakeClient())
    try:
        provider.fetch_market("BTCUSD", decision_time=DAY)
    except BinanceAdapterError as exc:
        assert exc.code == "INVALID_BINANCE_SYMBOL"
    else:
        raise AssertionError("Expected invalid symbol to be rejected")


def test_incomplete_timeframe_is_rejected():
    client = FakeClient()
    client.data["4h"] = []
    provider = BinanceMarketDataProvider(client)
    try:
        provider.fetch_market("BTCUSDT", decision_time=DAY)
    except BinanceAdapterError as exc:
        assert exc.code == "BINANCE_MARKET_DATA_INCOMPLETE"
        assert "4H_DATA_UNAVAILABLE" in str(exc)
    else:
        raise AssertionError("Expected incomplete data to be rejected")


def test_client_failure_is_wrapped_without_exposing_transport_details():
    class BrokenClient(FakeClient):
        def get_klines(self, symbol, interval, *, limit, end_time):
            if interval == "1h":
                raise ConnectionError("secret transport details")
            return super().get_klines(symbol, interval, limit=limit, end_time=end_time)

    provider = BinanceMarketDataProvider(BrokenClient())
    try:
        provider.fetch_market("BTCUSDT", decision_time=DAY)
    except BinanceAdapterError as exc:
        assert exc.code == "BINANCE_KLINE_FETCH_FAILED"
        assert "ConnectionError" in str(exc)
        assert "secret transport details" not in str(exc)
    else:
        raise AssertionError("Expected client failure")


def test_non_monotonic_kline_timestamps_are_rejected():
    client = FakeClient()
    client.data["1h"][10][0] = client.data["1h"][9][0]
    provider = BinanceMarketDataProvider(client)
    try:
        provider.fetch_market("BTCUSDT", decision_time=DAY)
    except BinanceAdapterError as exc:
        assert exc.code == "NON_MONOTONIC_BINANCE_KLINES"
    else:
        raise AssertionError("Expected non-monotonic klines to be rejected")


def test_invalid_adapter_limit_is_rejected_at_construction():
    try:
        BinanceMarketDataProvider(FakeClient(), BinanceAdapterConfig(one_hour_limit=0))
    except BinanceAdapterError as exc:
        assert exc.code == "INVALID_BINANCE_ADAPTER_CONFIG"
    else:
        raise AssertionError("Expected invalid adapter config")


def test_current_price_is_deliberately_left_for_closed_candle_runner():
    provider = BinanceMarketDataProvider(FakeClient())
    market = provider.fetch_market("BTCUSDT", decision_time=DAY)
    assert market.current_price is None
