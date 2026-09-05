"""
Market Data Normalization Layer
Wyckoff + SMC Spot Swing Agent

Binance market data is retrieved by the AI agent through
Binance Agent OS / Binance MCP.

This module does NOT store Binance credentials and does not
directly authenticate with Binance.

Its responsibility is to normalize raw Binance market data
into structures used by the scanner and strategy engine.
"""

from dataclasses import dataclass
from typing import Any, Iterable


@dataclass
class Candle:
    timestamp: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class MarketData:
    symbol: str
    current_price: float | None
    daily: list[Candle]
    four_hour: list[Candle]
    one_hour: list[Candle]
    fifteen_minute: list[Candle]


_TIMEFRAME_FIELDS = {
    "1D": "daily",
    "4H": "four_hour",
    "1H": "one_hour",
    "15M": "fifteen_minute",
}


def normalize_kline(raw_kline: list[Any]) -> Candle:
    """Convert one Binance Spot kline into a Candle."""

    if len(raw_kline) < 6:
        raise ValueError("Invalid Binance kline: expected at least 6 fields")

    return Candle(
        timestamp=int(raw_kline[0]),
        open=float(raw_kline[1]),
        high=float(raw_kline[2]),
        low=float(raw_kline[3]),
        close=float(raw_kline[4]),
        volume=float(raw_kline[5]),
    )


def normalize_klines(raw_klines: list[list[Any]]) -> list[Candle]:
    """Normalize a Binance kline response."""

    return [normalize_kline(kline) for kline in raw_klines]


def normalize_price(raw_price: Any) -> float | None:
    """Normalize a Binance ticker-price response into a float."""

    if raw_price is None:
        return None

    if isinstance(raw_price, dict):
        value = raw_price.get("price")
        if value is None:
            return None
        return float(value)

    try:
        return float(raw_price)
    except (TypeError, ValueError):
        return None


def build_market_data(
    symbol: str,
    current_price: Any,
    daily_klines: list[list[Any]],
    four_hour_klines: list[list[Any]],
    one_hour_klines: list[list[Any]],
    fifteen_minute_klines: list[list[Any]],
) -> MarketData:
    """Build the normalized multi-timeframe object consumed by strategy modules."""

    return MarketData(
        symbol=symbol.upper(),
        current_price=normalize_price(current_price),
        daily=normalize_klines(daily_klines),
        four_hour=normalize_klines(four_hour_klines),
        one_hour=normalize_klines(one_hour_klines),
        fifteen_minute=normalize_klines(fifteen_minute_klines),
    )


def candle_to_dict(candle: Candle) -> dict:
    """Convert a Candle object into a serializable dictionary."""

    return {
        "timestamp": candle.timestamp,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


def market_data_to_dict(market: MarketData) -> dict:
    """Convert normalized MarketData into JSON-friendly output."""

    return {
        "symbol": market.symbol,
        "current_price": market.current_price,
        "timeframes": {
            "1d": [candle_to_dict(c) for c in market.daily],
            "4h": [candle_to_dict(c) for c in market.four_hour],
            "1h": [candle_to_dict(c) for c in market.one_hour],
            "15m": [candle_to_dict(c) for c in market.fifteen_minute],
        },
    }


def validate_market_data(
    market: MarketData,
    required_timeframes: Iterable[str] | None = None,
    require_current_price: bool = True,
) -> tuple[bool, list[str]]:
    """
    Validate only the data required by the calling engine.

    By default all supported timeframes and current price are required,
    preserving the scanner's original strict behavior. Strategy modules can
    request a smaller subset, for example Wyckoff can require only ``4H``.
    """

    errors: list[str] = []

    if require_current_price and market.current_price is None:
        errors.append("CURRENT_PRICE_UNAVAILABLE")

    requested = (
        list(_TIMEFRAME_FIELDS)
        if required_timeframes is None
        else [str(timeframe).upper() for timeframe in required_timeframes]
    )

    unknown = [timeframe for timeframe in requested if timeframe not in _TIMEFRAME_FIELDS]
    if unknown:
        raise ValueError(f"Unsupported timeframe(s): {', '.join(unknown)}")

    for timeframe in requested:
        field_name = _TIMEFRAME_FIELDS[timeframe]
        if not getattr(market, field_name):
            errors.append(f"{timeframe}_DATA_UNAVAILABLE")

    return len(errors) == 0, errors


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Market data normalization module ready.")
