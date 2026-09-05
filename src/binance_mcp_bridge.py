"""
Concrete Binance MCP Client Bridge
Wyckoff + SMC Spot Swing Agent

Adapts a generic MCP/Agent-OS tool invoker to the read-only
BinanceMarketDataClient contract used by ``BinanceMarketDataProvider``.

The bridge deliberately exposes market-data retrieval only. It contains no
order-placement, account, transfer or credential methods. Response parsing is
fail-closed: only explicit, known envelopes are accepted.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol


class MCPToolInvoker(Protocol):
    """Minimal transport boundary implemented by the host MCP/Agent OS layer."""

    def invoke_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        ...


@dataclass(frozen=True)
class BinanceMCPBridgeConfig:
    kline_tool_name: str = "get_klines"
    price_tool_name: str = "get_price"
    symbol_argument: str = "symbol"
    interval_argument: str = "interval"
    limit_argument: str = "limit"
    end_time_argument: str = "end_time"


class BinanceMCPBridgeError(RuntimeError):
    def __init__(self, code: str, detail: str | None = None):
        self.code = code
        self.detail = detail
        super().__init__(code if detail is None else f"{code}:{detail}")


def _validate_config(cfg: BinanceMCPBridgeConfig) -> None:
    values = [
        cfg.kline_tool_name,
        cfg.price_tool_name,
        cfg.symbol_argument,
        cfg.interval_argument,
        cfg.limit_argument,
        cfg.end_time_argument,
    ]
    if any(not isinstance(value, str) or not value.strip() for value in values):
        raise BinanceMCPBridgeError("INVALID_MCP_BRIDGE_CONFIG")
    argument_names = values[2:]
    if len(set(argument_names)) != len(argument_names):
        raise BinanceMCPBridgeError("DUPLICATE_MCP_ARGUMENT_NAMES")


def _looks_like_klines(value: Any) -> bool:
    if not isinstance(value, list):
        return False
    if not value:
        return True
    return all(isinstance(row, (list, tuple)) and len(row) >= 6 for row in value)


def _parse_text_payload(text: str) -> list[list[Any]] | None:
    try:
        decoded = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    return _extract_klines(decoded)


def _extract_klines(payload: Any) -> list[list[Any]] | None:
    """Extract klines from supported MCP response envelopes only."""
    if _looks_like_klines(payload):
        return [list(row) for row in payload]

    if isinstance(payload, dict):
        for key in ("klines", "data", "result"):
            if key not in payload:
                continue
            candidate = payload[key]
            if _looks_like_klines(candidate):
                return [list(row) for row in candidate]
            if isinstance(candidate, dict):
                nested = _extract_klines(candidate)
                if nested is not None:
                    return nested

        content = payload.get("content")
        if isinstance(content, list):
            parsed_candidates: list[list[list[Any]]] = []
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                text = item.get("text")
                if not isinstance(text, str):
                    continue
                parsed = _parse_text_payload(text)
                if parsed is not None:
                    parsed_candidates.append(parsed)
            if len(parsed_candidates) == 1:
                return parsed_candidates[0]
            if len(parsed_candidates) > 1:
                first = parsed_candidates[0]
                if all(candidate == first for candidate in parsed_candidates[1:]):
                    return first
                raise BinanceMCPBridgeError("AMBIGUOUS_MCP_KLINE_RESPONSE")

    return None


def _extract_price(payload: Any) -> float | None:
    if isinstance(payload, (int, float, str)):
        try:
            return float(payload)
        except (TypeError, ValueError):
            return None
    if isinstance(payload, dict):
        if "price" in payload:
            return _extract_price(payload["price"])
        for key in ("data", "result"):
            if key in payload:
                candidate = _extract_price(payload[key])
                if candidate is not None:
                    return candidate
        content = payload.get("content")
        if isinstance(content, list):
            candidates: list[float] = []
            for item in content:
                if not isinstance(item, dict) or item.get("type") != "text":
                    continue
                try:
                    decoded = json.loads(item.get("text", ""))
                except (TypeError, json.JSONDecodeError):
                    continue
                candidate = _extract_price(decoded)
                if candidate is not None:
                    candidates.append(candidate)
            if candidates and all(candidate == candidates[0] for candidate in candidates):
                return candidates[0]
    return None


def _is_transient_failure(value: Any) -> bool:
    text = f"{type(value).__name__} {value}".upper()
    return any(token in text for token in (
        "-1003", "429", "RATE LIMIT", "REQUEST WEIGHT", "TIMEOUT",
        "TIMED OUT", "UNAVAILABLE", "CONNECTION",
    ))


def _invoke(invoker: MCPToolInvoker, tool_name: str, arguments: dict[str, Any]) -> Any:
    try:
        payload = invoker.invoke_tool(tool_name, arguments)
    except Exception as exc:
        code = "MCP_TOOL_TRANSIENT_FAILURE" if _is_transient_failure(exc) else "MCP_TOOL_INVOCATION_FAILED"
        raise BinanceMCPBridgeError(code, type(exc).__name__) from exc
    if isinstance(payload, dict) and ("error" in payload or "error_code" in payload):
        code = "MCP_TOOL_TRANSIENT_FAILURE" if _is_transient_failure(payload) else "MCP_REMOTE_ERROR"
        raise BinanceMCPBridgeError(code)
    return payload


class BinanceMCPClientBridge:
    """Concrete read-only Binance client implemented through MCP tool invocation."""

    def __init__(self, invoker: MCPToolInvoker, config: BinanceMCPBridgeConfig | None = None) -> None:
        self.invoker = invoker
        self.config = config or BinanceMCPBridgeConfig()
        _validate_config(self.config)

    def get_price(self, symbol: str) -> float:
        if not isinstance(symbol, str) or not symbol.strip():
            raise BinanceMCPBridgeError("INVALID_MCP_SYMBOL")
        cfg = self.config
        payload = _invoke(
            self.invoker,
            cfg.price_tool_name,
            {cfg.symbol_argument: symbol.upper().strip()},
        )
        price = _extract_price(payload)
        if price is None or price <= 0:
            raise BinanceMCPBridgeError("INVALID_MCP_PRICE_RESPONSE")
        return price

    def get_klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int,
        end_time: int,
    ) -> list[list[Any]]:
        if not isinstance(symbol, str) or not symbol.strip():
            raise BinanceMCPBridgeError("INVALID_MCP_SYMBOL")
        if not isinstance(interval, str) or not interval.strip():
            raise BinanceMCPBridgeError("INVALID_MCP_INTERVAL")
        if not isinstance(limit, int) or limit <= 0:
            raise BinanceMCPBridgeError("INVALID_MCP_LIMIT")
        if not isinstance(end_time, int) or end_time < 0:
            raise BinanceMCPBridgeError("INVALID_MCP_END_TIME")

        cfg = self.config
        arguments = {
            cfg.symbol_argument: symbol.upper().strip(),
            cfg.interval_argument: interval,
            cfg.limit_argument: limit,
            cfg.end_time_argument: end_time,
        }
        payload = _invoke(self.invoker, cfg.kline_tool_name, arguments)

        try:
            klines = _extract_klines(payload)
        except BinanceMCPBridgeError:
            raise
        except Exception as exc:
            raise BinanceMCPBridgeError(
                "INVALID_MCP_KLINE_RESPONSE",
                type(exc).__name__,
            ) from exc

        if klines is None:
            raise BinanceMCPBridgeError("INVALID_MCP_KLINE_RESPONSE")
        return klines


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Concrete Binance MCP read-only bridge ready; MCP invoker required.")
