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
from typing import Any


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


def normalize_kline(raw_kline: list[Any]) -> Candle:
    """
    Convert one Binance Spot kline into a Candle.

    Expected Binance kline format:

    [
        open_time,
        open,
        high,
        low,
        close,
        volume,
        close_time,
        quote_asset_volume,
        number_of_trades,
        taker_buy_base_volume,
        taker_buy_quote_volume,
        ignore
    ]
    """

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
    """
    Normalize a Binance kline response.
    """

    return [normalize_kline(kline) for kline in raw_klines]


def normalize_price(raw_price: Any) -> float | None:
    """
    Normalize the Binance ticker price response.

    Supported examples:

    {"symbol": "BTCUSDT", "price": "79636.90"}

    or:

    "79636.90"
    """

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
    """
    Build the normalized multi-timeframe market object
    consumed by the strategy engine.
    """

    return MarketData(
        symbol=symbol.upper(),
        current_price=normalize_price(current_price),
        daily=normalize_klines(daily_klines),
        four_hour=normalize_klines(four_hour_klines),
        one_hour=normalize_klines(one_hour_klines),
        fifteen_minute=normalize_klines(fifteen_minute_klines),
    )


def candle_to_dict(candle: Candle) -> dict:
    """
    Convert a Candle object into a serializable dictionary.
    """

    return {
        "timestamp": candle.timestamp,
        "open": candle.open,
        "high": candle.high,
        "low": candle.low,
        "close": candle.close,
        "volume": candle.volume,
    }


def market_data_to_dict(market: MarketData) -> dict:
    """
    Convert normalized MarketData into a dictionary suitable
    for JSON output or downstream agent reasoning.
    """

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


def validate_market_data(market: MarketData) -> tuple[bool, list[str]]:
    """
    Validate whether the required market data is available.

    Returns:
        (is_valid, errors)
    """

    errors = []

    if market.current_price is None:
        errors.append("CURRENT_PRICE_UNAVAILABLE")

    if not market.daily:
        errors.append("1D_DATA_UNAVAILABLE")

    if not market.four_hour:
        errors.append("4H_DATA_UNAVAILABLE")

    if not market.one_hour:
        errors.append("1H_DATA_UNAVAILABLE")

    if not market.fifteen_minute:
        errors.append("15M_DATA_UNAVAILABLE")

    return len(errors) == 0, errors


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Market data normalization module ready.")
