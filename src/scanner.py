"""
Market Candidate Scanner
Wyckoff + SMC Spot Swing Agent

This module performs a lightweight quantitative pre-screen on normalized
Binance Spot market data. Its job is not to label a complete Wyckoff phase
or produce a trade entry. It ranks symbols so the deeper Wyckoff + SMC
analysis engine can spend attention on the most interesting candidates.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

try:
    from .market_data import Candle, MarketData, validate_market_data
except ImportError:  # Allows: python src/scanner.py
    from market_data import Candle, MarketData, validate_market_data


DEFAULT_WATCHLIST_PATH = Path(__file__).resolve().parent.parent / "config" / "watchlist.json"


@dataclass(frozen=True)
class WatchlistSymbol:
    symbol: str
    priority: str = "MEDIUM"


@dataclass
class ScoreBreakdown:
    trend: float
    structure: float
    volume: float
    compression: float
    range_location: float

    @property
    def total(self) -> float:
        return round(
            self.trend
            + self.structure
            + self.volume
            + self.compression
            + self.range_location,
            2,
        )


@dataclass
class ScanResult:
    symbol: str
    score: float
    classification: str
    priority: str
    signals: list[str]
    breakdown: ScoreBreakdown
    errors: list[str]

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["score"] = self.score
        return payload


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _closes(candles: list[Candle]) -> list[float]:
    return [c.close for c in candles]


def _safe_ratio(numerator: float, denominator: float) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def load_watchlist(path: str | Path = DEFAULT_WATCHLIST_PATH) -> list[WatchlistSymbol]:
    """Load enabled symbols from the configured Spot watchlist."""

    watchlist_path = Path(path)
    with watchlist_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    symbols = []
    for item in payload.get("symbols", []):
        if not item.get("enabled", True):
            continue

        symbol = str(item.get("symbol", "")).upper().strip()
        if not symbol:
            continue

        symbols.append(
            WatchlistSymbol(
                symbol=symbol,
                priority=str(item.get("priority", "MEDIUM")).upper(),
            )
        )

    return symbols


def _trend_score(market: MarketData, signals: list[str]) -> float:
    """Score higher-timeframe directional health. Maximum: 25."""

    score = 0.0
    daily = market.daily
    four_hour = market.four_hour

    if len(daily) >= 20:
        daily_sma20 = _mean(_closes(daily[-20:]))
        if daily[-1].close > daily_sma20:
            score += 10.0
            signals.append("1D_ABOVE_SMA20")

    if len(four_hour) >= 20:
        h4_sma20 = _mean(_closes(four_hour[-20:]))
        if four_hour[-1].close > h4_sma20:
            score += 8.0
            signals.append("4H_ABOVE_SMA20")

    if len(four_hour) >= 7 and four_hour[-1].close > four_hour[-7].close:
        score += 7.0
        signals.append("4H_POSITIVE_MOMENTUM")

    return score


def _structure_score(market: MarketData, signals: list[str]) -> float:
    """Score simple 4H higher-low / higher-high structure. Maximum: 25."""

    candles = market.four_hour
    if len(candles) < 12:
        return 0.0

    previous = candles[-12:-6]
    recent = candles[-6:]

    previous_low = min(c.low for c in previous)
    recent_low = min(c.low for c in recent)
    previous_high = max(c.high for c in previous)
    recent_high = max(c.high for c in recent)

    score = 0.0

    if recent_low > previous_low:
        score += 13.0
        signals.append("4H_HIGHER_LOW")

    if recent_high > previous_high:
        score += 8.0
        signals.append("4H_HIGHER_HIGH")

    if recent[-1].close > _mean(_closes(recent)):
        score += 4.0
        signals.append("4H_CLOSE_ABOVE_RECENT_MEAN")

    return score


def _volume_score(market: MarketData, signals: list[str]) -> float:
    """Score contraction plus constructive demand behavior. Maximum: 20."""

    candles = market.four_hour
    if len(candles) < 20:
        return 0.0

    recent = candles[-5:]
    baseline = candles[-20:-5]

    recent_volume = _mean(c.volume for c in recent)
    baseline_volume = _mean(c.volume for c in baseline)
    contraction_ratio = _safe_ratio(recent_volume, baseline_volume)

    score = 0.0

    if contraction_ratio <= 0.80:
        score += 10.0
        signals.append("4H_VOLUME_CONTRACTION")
    elif contraction_ratio <= 0.95:
        score += 6.0
        signals.append("4H_VOLUME_COOLING")

    bullish_volume = sum(c.volume for c in recent if c.close >= c.open)
    bearish_volume = sum(c.volume for c in recent if c.close < c.open)

    if bullish_volume > bearish_volume:
        score += 10.0
        signals.append("4H_BUY_VOLUME_DOMINANCE")

    return score


def _compression_score(market: MarketData, signals: list[str]) -> float:
    """Score narrowing 4H price range. Maximum: 15."""

    candles = market.four_hour
    if len(candles) < 20:
        return 0.0

    recent = candles[-5:]
    baseline = candles[-20:-5]

    recent_range = max(c.high for c in recent) - min(c.low for c in recent)
    baseline_range = max(c.high for c in baseline) - min(c.low for c in baseline)
    ratio = _safe_ratio(recent_range, baseline_range)

    if ratio <= 0.45:
        signals.append("4H_TIGHT_COMPRESSION")
        return 15.0
    if ratio <= 0.65:
        signals.append("4H_RANGE_COMPRESSION")
        return 10.0
    if ratio <= 0.85:
        signals.append("4H_MODERATE_COMPRESSION")
        return 5.0

    return 0.0


def _range_location_score(market: MarketData, signals: list[str]) -> float:
    """Favor price holding in the lower/middle part of its recent 4H range. Max: 15."""

    candles = market.four_hour
    if len(candles) < 20:
        return 0.0

    window = candles[-20:]
    range_low = min(c.low for c in window)
    range_high = max(c.high for c in window)
    width = range_high - range_low

    if width <= 0:
        return 0.0

    position = (candles[-1].close - range_low) / width

    if 0.20 <= position <= 0.50:
        signals.append("4H_ACCUMULATION_LOCATION")
        return 15.0
    if position < 0.20:
        signals.append("4H_NEAR_RANGE_LOW")
        return 10.0
    if 0.50 < position <= 0.70:
        signals.append("4H_MID_RANGE_HOLD")
        return 6.0

    return 0.0


def classify_score(score: float) -> str:
    if score >= 75:
        return "HIGH_INTEREST"
    if score >= 60:
        return "WATCH"
    if score >= 45:
        return "NEUTRAL"
    return "LOW_INTEREST"


def scan_market(market: MarketData, priority: str = "MEDIUM") -> ScanResult:
    """Score one normalized market and return a candidate-ranking result."""

    is_valid, errors = validate_market_data(market)
    if not is_valid:
        return ScanResult(
            symbol=market.symbol,
            score=0.0,
            classification="INVALID_DATA",
            priority=priority.upper(),
            signals=[],
            breakdown=ScoreBreakdown(0.0, 0.0, 0.0, 0.0, 0.0),
            errors=errors,
        )

    signals: list[str] = []
    breakdown = ScoreBreakdown(
        trend=_trend_score(market, signals),
        structure=_structure_score(market, signals),
        volume=_volume_score(market, signals),
        compression=_compression_score(market, signals),
        range_location=_range_location_score(market, signals),
    )

    score = breakdown.total

    return ScanResult(
        symbol=market.symbol,
        score=score,
        classification=classify_score(score),
        priority=priority.upper(),
        signals=signals,
        breakdown=breakdown,
        errors=[],
    )


def rank_scan_results(results: Iterable[ScanResult]) -> list[ScanResult]:
    """Rank valid candidates by score, using watchlist priority as a tie-breaker."""

    priority_weight = {"HIGH": 2, "MEDIUM": 1, "LOW": 0}

    return sorted(
        results,
        key=lambda result: (
            result.classification != "INVALID_DATA",
            result.score,
            priority_weight.get(result.priority, 0),
        ),
        reverse=True,
    )


def scan_markets(
    markets: Iterable[MarketData],
    priorities: dict[str, str] | None = None,
) -> list[ScanResult]:
    """Scan and rank multiple normalized markets."""

    priorities = priorities or {}
    results = [
        scan_market(
            market,
            priority=priorities.get(market.symbol.upper(), "MEDIUM"),
        )
        for market in markets
    ]
    return rank_scan_results(results)


def watchlist_priorities(
    path: str | Path = DEFAULT_WATCHLIST_PATH,
) -> dict[str, str]:
    return {item.symbol: item.priority for item in load_watchlist(path)}


if __name__ == "__main__":
    configured_symbols = load_watchlist()
    print("Wyckoff + SMC Spot Swing Agent")
    print(f"Scanner ready. Enabled watchlist symbols: {len(configured_symbols)}")
    for item in configured_symbols:
        print(f"- {item.symbol}: {item.priority}")
