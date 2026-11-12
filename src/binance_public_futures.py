"""Strict read-only Binance USD-M Futures public market-data collector.

Uses public market endpoints only; no API key, wallet, orders or credentials.
Every timeframe is checked for exact count, continuity, OHLCV integrity,
closed bars and a fresh most-recent expected bar. Fail closed on errors.
"""
from __future__ import annotations

import json
import math
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .market_data import MarketData, build_market_data

BASE_URL = "https://fapi.binance.com"
INTERVAL_MS = {"1d": 86_400_000, "4h": 14_400_000, "1h": 3_600_000, "15m": 900_000}
LIMITS = {"1d": 120, "4h": 240, "1h": 300, "15m": 300}
OVERFETCH = 5


class FuturesDataError(RuntimeError):
    """A malformed, stale or unreachable data feed must block the signal."""


def _read_public_json(url: str) -> object:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "wyckoff-smc-data/1.0"})
    try:
        with urlopen(request, timeout=18) as response:
            return json.load(response)
    except HTTPError as exc:
        raise FuturesDataError(f"BINANCE_PUBLIC_HTTP_{exc.code}") from exc
    except (URLError, TimeoutError, ValueError) as exc:
        raise FuturesDataError("BINANCE_PUBLIC_API_UNAVAILABLE:" + type(exc).__name__) from exc


def fetch_closed_klines(
    symbol: str,
    interval: str,
    count: int,
    *,
    now_ms: int | None = None,
    request_json=None,
) -> list[list]:
    """Get exactly count most recent *closed* consecutive native Binance klines.

    Symbol/interval are fixed validation inputs, not arbitrary URLs.
    request_json is dependency injection for offline tests.
    """
    symbol = str(symbol).upper().strip()
    if not re.fullmatch(r"[A-Z0-9]{2,24}USDT", symbol):
        raise FuturesDataError("INVALID_FUTURES_SYMBOL")
    if interval not in INTERVAL_MS:
        raise FuturesDataError("INVALID_INTERVAL")
    if not isinstance(count, int) or not (1 <= count <= 990):
        raise FuturesDataError("INVALID_CANDLE_COUNT")
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    if now_ms <= 0:
        raise FuturesDataError("INVALID_CLOCK")
    query = urlencode({"symbol": symbol, "interval": interval, "limit": count + OVERFETCH})
    url = BASE_URL + "/fapi/v1/klines?" + query
    payload = (request_json or _read_public_json)(url)
    if not isinstance(payload, list):
        raise FuturesDataError("INVALID_KLINES_PAYLOAD")
    delta = INTERVAL_MS[interval]
    valid = []
    previous_open = None
    for row in payload:
        if not isinstance(row, list) or len(row) < 7:
            raise FuturesDataError("MALFORMED_CANDLE")
        try:
            opened = int(row[0])
            closed = int(row[6])
            o, h, l, c, v = map(float, row[1:6])
        except (ValueError, TypeError, OverflowError) as exc:
            raise FuturesDataError("MALFORMED_OHLCV") from exc
        if previous_open is not None and opened <= previous_open:
            raise FuturesDataError("UNORDERED_OR_DUPLICATE_CANDLES")
        previous_open = opened
        if opened % delta or closed != opened + delta - 1:
            raise FuturesDataError("INCORRECT_CANDLE_INTERVAL")
        if not all(map(math.isfinite, (o, h, l, c, v))) or l <= 0 or v < 0 or h < max(o, c, l) or l > min(o, c):
            raise FuturesDataError("INVALID_OHLCV")
        if closed < now_ms:
            valid.append(row)
    selected = valid[-count:]
    if len(selected) != count:
        raise FuturesDataError("INSUFFICIENT_CLOSED_CANDLES")
    opens = [int(row[0]) for row in selected]
    if any(b - a != delta for a, b in zip(opens, opens[1:])):
        raise FuturesDataError("GAP_IN_CLOSED_CANDLES")
    expected_latest_open = (now_ms // delta - 1) * delta
    if opens[-1] != expected_latest_open:
        raise FuturesDataError("STALE_OR_FUTURE_LAST_CANDLE")
    return selected


def collect_futures_market(symbol: str, *, now_ms: int | None = None, request_json=None) -> MarketData:
    """Return a normalized, four-timeframe, fully verified Futures snapshot."""
    now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    bars = {
        interval: fetch_closed_klines(symbol, interval, count, now_ms=now_ms, request_json=request_json)
        for interval, count in LIMITS.items()
    }
    # Closed 15m close is an observed reference, NOT a claimed live ticker.
    reference_price = float(bars["15m"][-1][4])
    return build_market_data(symbol, reference_price, bars["1d"], bars["4h"], bars["1h"], bars["15m"])
