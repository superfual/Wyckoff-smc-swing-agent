import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from binance_mcp_bridge import (
    BinanceMCPBridgeConfig,
    BinanceMCPBridgeError,
    BinanceMCPClientBridge,
)


class FakeInvoker:
    def __init__(self, payload=None, error: Exception | None = None):
        self.payload = payload
        self.error = error
        self.calls = []

    def invoke_tool(self, tool_name, arguments):
        self.calls.append((tool_name, arguments))
        if self.error is not None:
            raise self.error
        return self.payload


def _rows():
    return [
        [1_000, "100", "110", "90", "105", "123"],
        [2_000, "105", "115", "95", "110", "150"],
    ]


def test_bridge_invokes_configured_tool_with_exact_arguments():
    invoker = FakeInvoker(_rows())
    bridge = BinanceMCPClientBridge(invoker)
    result = bridge.get_klines("btcusdt", "1h", limit=100, end_time=9_999)
    assert result == _rows()
    assert invoker.calls == [(
        "get_klines",
        {"symbol": "BTCUSDT", "interval": "1h", "limit": 100, "end_time": 9_999},
    )]


def test_bridge_accepts_known_dict_envelopes():
    for payload in ({"data": _rows()}, {"result": _rows()}, {"klines": _rows()}, {"data": {"klines": _rows()}}):
        bridge = BinanceMCPClientBridge(FakeInvoker(payload))
        assert bridge.get_klines("BTCUSDT", "4h", limit=50, end_time=5_000) == _rows()


def test_bridge_accepts_mcp_text_content_json():
    payload = {"content": [{"type": "text", "text": '[[1000,"1","2","0.5","1.5","10"]]'}]}
    bridge = BinanceMCPClientBridge(FakeInvoker(payload))
    result = bridge.get_klines("ETHUSDT", "15m", limit=10, end_time=2_000)
    assert result == [[1000, "1", "2", "0.5", "1.5", "10"]]


def test_bridge_rejects_unknown_response_shape():
    bridge = BinanceMCPClientBridge(FakeInvoker({"message": "ok"}))
    try:
        bridge.get_klines("BTCUSDT", "1h", limit=10, end_time=2_000)
        assert False, "expected BinanceMCPBridgeError"
    except BinanceMCPBridgeError as exc:
        assert exc.code == "INVALID_MCP_KLINE_RESPONSE"


def test_bridge_rejects_ambiguous_text_candidates():
    payload = {
        "content": [
            {"type": "text", "text": '[[1000,"1","2","0.5","1.5","10"]]'},
            {"type": "text", "text": '[[2000,"2","3","1.5","2.5","20"]]'},
        ]
    }
    bridge = BinanceMCPClientBridge(FakeInvoker(payload))
    try:
        bridge.get_klines("BTCUSDT", "1h", limit=10, end_time=2_000)
        assert False, "expected BinanceMCPBridgeError"
    except BinanceMCPBridgeError as exc:
        assert exc.code == "AMBIGUOUS_MCP_KLINE_RESPONSE"


def test_bridge_wraps_transport_error_without_leaking_message():
    bridge = BinanceMCPClientBridge(FakeInvoker(error=ConnectionError("secret transport detail")))
    try:
        bridge.get_klines("BTCUSDT", "1h", limit=10, end_time=2_000)
        assert False, "expected BinanceMCPBridgeError"
    except BinanceMCPBridgeError as exc:
        assert exc.code == "MCP_TOOL_TRANSIENT_FAILURE"
        assert exc.detail == "ConnectionError"
        assert "secret transport detail" not in str(exc)


def test_custom_tool_and_argument_names_are_supported():
    invoker = FakeInvoker(_rows())
    cfg = BinanceMCPBridgeConfig(
        kline_tool_name="market_klines",
        symbol_argument="pair",
        interval_argument="tf",
        limit_argument="count",
        end_time_argument="endTime",
    )
    bridge = BinanceMCPClientBridge(invoker, cfg)
    bridge.get_klines("BNBUSDT", "1d", limit=20, end_time=3_000)
    assert invoker.calls[0] == (
        "market_klines",
        {"pair": "BNBUSDT", "tf": "1d", "count": 20, "endTime": 3_000},
    )


def test_invalid_bridge_config_is_rejected():
    try:
        BinanceMCPClientBridge(FakeInvoker(_rows()), BinanceMCPBridgeConfig(symbol_argument="interval"))
        assert False, "expected BinanceMCPBridgeError"
    except BinanceMCPBridgeError as exc:
        assert exc.code == "DUPLICATE_MCP_ARGUMENT_NAMES"


def test_invalid_request_is_rejected_before_transport_call():
    invoker = FakeInvoker(_rows())
    bridge = BinanceMCPClientBridge(invoker)
    try:
        bridge.get_klines("", "1h", limit=10, end_time=2_000)
        assert False, "expected BinanceMCPBridgeError"
    except BinanceMCPBridgeError as exc:
        assert exc.code == "INVALID_MCP_SYMBOL"
    assert invoker.calls == []


def test_bridge_fetches_and_parses_spot_price_without_order_surface():
    invoker = FakeInvoker({"symbol": "BTCUSDT", "price": "80123.45"})
    bridge = BinanceMCPClientBridge(invoker)

    assert bridge.get_price("btcusdt") == 80123.45
    assert invoker.calls == [("get_price", {"symbol": "BTCUSDT"})]
    assert not hasattr(bridge, "new_order")


def test_bridge_marks_returned_rate_limit_error_as_transient():
    payload = {"error": "McpServerError: -1003 too much request weight", "error_code": "UNAVAILABLE"}
    bridge = BinanceMCPClientBridge(FakeInvoker(payload))

    try:
        bridge.get_price("BTCUSDT")
        assert False, "expected BinanceMCPBridgeError"
    except BinanceMCPBridgeError as exc:
        assert exc.code == "MCP_TOOL_TRANSIENT_FAILURE"
