"""
Binance MCP / Agent OS Market-Data Adapter
Wyckoff + SMC Spot Swing Agent

Read-only adapter that translates a Binance-capable client into the normalized
MarketDataProvider contract consumed by PaperRuntime. The client is injected so
this repository is not coupled to one MCP/Agent OS transport implementation.

This module exposes no order-placement methods, stores no credentials and sends
no exchange orders. PaperRuntime still applies its own closed-candle filtering,
so adapter time-bounding is defense-in-depth rather than the only timing guard.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, Sequence

try:
    from .market_data import MarketData, build_market_data, validate_market_data
except ImportError:
    from market_data import MarketData, build_market_data, validate_market_data


class BinanceMarketDataClient(Protocol):
    """Minimal read-only client contract for Binance market data."""

    def get_klines(
        self,
        symbol: str,
        interval: str,
        *,
        limit: int,
        end_time: int,
    ) -> list[list[Any]]:
        ...


@dataclass(frozen=True)
class BinanceAdapterConfig:
    daily_limit: int = 120
    four_hour_limit: int = 240
    one_hour_limit: int = 300
    fifteen_minute_limit: int = 300
    require_all_timeframes: bool = True


class BinanceAdapterError(RuntimeError):
    """Deterministic adapter failure with a machine-readable code."""

    def __init__(self, code: str, symbol: str | None = None, detail: str | None = None):
        self.code = code
        self.symbol = symbol
        self.detail = detail
        parts = [code]
        if symbol:
            parts.append(symbol)
        if detail:
            parts.append(detail)
        super().__init__(":".join(parts))


def _validate_config(cfg: BinanceAdapterConfig) -> None:
    limits = [
        cfg.daily_limit,
        cfg.four_hour_limit,
        cfg.one_hour_limit,
        cfg.fifteen_minute_limit,
    ]
    if any(limit <= 0 or limit > 1000 for limit in limits):
        raise BinanceAdapterError("INVALID_BINANCE_ADAPTER_CONFIG")


def _validate_symbol(symbol: str) -> str:
    normalized = str(symbol).upper().strip()
    if not normalized or not normalized.endswith("USDT"):
        raise BinanceAdapterError("INVALID_BINANCE_SYMBOL", normalized or None)
    return normalized


def _fetch_klines(
    client: BinanceMarketDataClient,
    symbol: str,
    interval: str,
    limit: int,
    decision_time: int,
) -> list[list[Any]]:
    try:
        result = client.get_klines(
            symbol,
            interval,
            limit=limit,
            end_time=decision_time,
        )
    except Exception as exc:
        raise BinanceAdapterError(
            "BINANCE_KLINE_FETCH_FAILED",
            symbol,
            f"{interval}:{type(exc).__name__}",
        ) from exc

    if not isinstance(result, list):
        raise BinanceAdapterError("INVALID_BINANCE_KLINE_RESPONSE", symbol, interval)
    return result


def _strictly_increasing_timestamps(market: MarketData) -> bool:
    for candles in (market.daily, market.four_hour, market.one_hour, market.fifteen_minute):
        timestamps = [candle.timestamp for candle in candles]
        if any(current <= previous for previous, current in zip(timestamps, timestamps[1:])):
            return False
    return True


class BinanceMarketDataProvider:
    """PaperRuntime-compatible provider backed by an injected Binance client."""

    def __init__(
        self,
        client: BinanceMarketDataClient,
        config: BinanceAdapterConfig | None = None,
    ) -> None:
        self.client = client
        self.config = config or BinanceAdapterConfig()
        _validate_config(self.config)

    def fetch_market(self, symbol: str, *, decision_time: int) -> MarketData:
        if decision_time < 0:
            raise BinanceAdapterError("INVALID_DECISION_TIME", str(symbol).upper().strip() or None)

        normalized = _validate_symbol(symbol)
        cfg = self.config
        daily = _fetch_klines(self.client, normalized, "1d", cfg.daily_limit, decision_time)
        four_hour = _fetch_klines(self.client, normalized, "4h", cfg.four_hour_limit, decision_time)
        one_hour = _fetch_klines(self.client, normalized, "1h", cfg.one_hour_limit, decision_time)
        fifteen_minute = _fetch_klines(self.client, normalized, "15m", cfg.fifteen_minute_limit, decision_time)

        try:
            market = build_market_data(
                normalized,
                None,
                daily,
                four_hour,
                one_hour,
                fifteen_minute,
            )
        except (TypeError, ValueError, IndexError) as exc:
            raise BinanceAdapterError(
                "BINANCE_MARKET_NORMALIZATION_FAILED",
                normalized,
                type(exc).__name__,
            ) from exc

        required = ["1D", "4H", "1H", "15M"] if cfg.require_all_timeframes else []
        if required:
            valid, errors = validate_market_data(
                market,
                required_timeframes=required,
                require_current_price=False,
            )
            if not valid:
                raise BinanceAdapterError(
                    "BINANCE_MARKET_DATA_INCOMPLETE",
                    normalized,
                    ",".join(errors),
                )

        if not _strictly_increasing_timestamps(market):
            raise BinanceAdapterError("NON_MONOTONIC_BINANCE_KLINES", normalized)

        return market

    def fetch_markets(self, symbols: Sequence[str], *, decision_time: int) -> list[MarketData]:
        """Fetch normalized snapshots in requested-symbol order."""
        if decision_time < 0:
            raise BinanceAdapterError("INVALID_DECISION_TIME")
        return [self.fetch_market(symbol, decision_time=decision_time) for symbol in symbols]


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Binance read-only market-data adapter ready; injected client required.")
