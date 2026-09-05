"""
Wyckoff Analysis Engine
Wyckoff + SMC Spot Swing Agent

The engine identifies a recent trading range, detects simplified Wyckoff
signatures, and infers a directional bias/phase with an explicit confidence
score. It is intentionally heuristic: it prepares structured evidence for
later SMC confluence and agent reasoning rather than claiming certainty.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable

try:
    from .market_data import Candle, MarketData, validate_market_data
except ImportError:  # Allows: python src/wyckoff.py
    from market_data import Candle, MarketData, validate_market_data


@dataclass
class TradingRange:
    support: float
    resistance: float
    midpoint: float
    width_pct: float
    start_index: int
    end_index: int


@dataclass
class WyckoffEvent:
    code: str
    index: int
    price: float
    confidence: float
    note: str


@dataclass
class WyckoffAnalysis:
    symbol: str
    bias: str
    phase: str
    confidence: float
    trading_range: TradingRange | None
    events: list[WyckoffEvent]
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _mean(values: Iterable[float]) -> float:
    values = list(values)
    return sum(values) / len(values) if values else 0.0


def _range(candle: Candle) -> float:
    return max(candle.high - candle.low, 0.0)


def _body(candle: Candle) -> float:
    return abs(candle.close - candle.open)


def _volume_baseline(candles: list[Candle], index: int, lookback: int = 10) -> float:
    start = max(0, index - lookback)
    previous = candles[start:index]
    return _mean(c.volume for c in previous) if previous else candles[index].volume


def detect_trading_range(candles: list[Candle], lookback: int = 30) -> TradingRange | None:
    """Detect a recent broad 4H trading range using robust inner extremes."""

    if len(candles) < 12:
        return None

    window = candles[-lookback:]
    lows = sorted(c.low for c in window)
    highs = sorted(c.high for c in window)

    trim = max(1, int(len(window) * 0.10))
    support_pool = lows[trim : max(trim + 1, trim * 3)]
    resistance_pool = highs[max(0, len(highs) - trim * 3) : len(highs) - trim]

    support = _mean(support_pool) if support_pool else min(lows)
    resistance = _mean(resistance_pool) if resistance_pool else max(highs)

    if resistance <= support:
        return None

    midpoint = (support + resistance) / 2
    width_pct = ((resistance - support) / midpoint) * 100 if midpoint else 0.0

    return TradingRange(
        support=round(support, 8),
        resistance=round(resistance, 8),
        midpoint=round(midpoint, 8),
        width_pct=round(width_pct, 2),
        start_index=max(0, len(candles) - len(window)),
        end_index=len(candles) - 1,
    )


def _detect_climaxes(candles: list[Candle], trading_range: TradingRange) -> list[WyckoffEvent]:
    events: list[WyckoffEvent] = []
    avg_range = _mean(_range(c) for c in candles[-20:]) or 1.0

    for index, candle in enumerate(candles):
        baseline_volume = _volume_baseline(candles, index)
        volume_ratio = candle.volume / baseline_volume if baseline_volume else 1.0
        spread_ratio = _range(candle) / avg_range if avg_range else 1.0

        near_support = candle.low <= trading_range.support * 1.015
        near_resistance = candle.high >= trading_range.resistance * 0.985

        if near_support and volume_ratio >= 1.35 and spread_ratio >= 1.20 and candle.close > candle.low:
            confidence = min(95.0, 55 + (volume_ratio - 1.35) * 20 + (spread_ratio - 1.2) * 15)
            events.append(
                WyckoffEvent(
                    code="SC",
                    index=index,
                    price=candle.low,
                    confidence=round(confidence, 1),
                    note="High-volume downside climax near range support.",
                )
            )

        if near_resistance and volume_ratio >= 1.35 and spread_ratio >= 1.20 and candle.close < candle.high:
            confidence = min(95.0, 55 + (volume_ratio - 1.35) * 20 + (spread_ratio - 1.2) * 15)
            events.append(
                WyckoffEvent(
                    code="BC",
                    index=index,
                    price=candle.high,
                    confidence=round(confidence, 1),
                    note="High-volume upside climax near range resistance.",
                )
            )

    return events


def _detect_range_tests(candles: list[Candle], trading_range: TradingRange) -> list[WyckoffEvent]:
    events: list[WyckoffEvent] = []
    width = trading_range.resistance - trading_range.support
    if width <= 0:
        return events

    for index, candle in enumerate(candles):
        lower_zone = trading_range.support + width * 0.18
        upper_zone = trading_range.resistance - width * 0.18
        baseline_volume = _volume_baseline(candles, index)
        volume_ratio = candle.volume / baseline_volume if baseline_volume else 1.0

        if candle.low <= lower_zone and candle.close > candle.low and volume_ratio <= 1.15:
            events.append(
                WyckoffEvent(
                    code="ST",
                    index=index,
                    price=candle.low,
                    confidence=65.0,
                    note="Secondary-test style revisit of lower range on controlled volume.",
                )
            )

        if candle.high >= upper_zone and candle.close < candle.high and volume_ratio <= 1.15:
            events.append(
                WyckoffEvent(
                    code="UT_TEST",
                    index=index,
                    price=candle.high,
                    confidence=60.0,
                    note="Upper-range test on controlled volume.",
                )
            )

    return events


def _detect_spring_upthrust(candles: list[Candle], trading_range: TradingRange) -> list[WyckoffEvent]:
    events: list[WyckoffEvent] = []
    width = trading_range.resistance - trading_range.support
    if width <= 0:
        return events

    spring_threshold = trading_range.support - width * 0.08
    upthrust_threshold = trading_range.resistance + width * 0.08

    for index, candle in enumerate(candles):
        if candle.low < spring_threshold and candle.close > trading_range.support:
            reclaim = (candle.close - trading_range.support) / width
            confidence = min(95.0, 70 + reclaim * 100)
            events.append(
                WyckoffEvent(
                    code="SPRING",
                    index=index,
                    price=candle.low,
                    confidence=round(confidence, 1),
                    note="Liquidity sweep below support followed by range reclaim.",
                )
            )

        if candle.high > upthrust_threshold and candle.close < trading_range.resistance:
            rejection = (trading_range.resistance - candle.close) / width
            confidence = min(95.0, 70 + rejection * 100)
            events.append(
                WyckoffEvent(
                    code="UTAD",
                    index=index,
                    price=candle.high,
                    confidence=round(confidence, 1),
                    note="Liquidity sweep above resistance followed by rejection into range.",
                )
            )

    return events


def _detect_sos_sow(candles: list[Candle], trading_range: TradingRange) -> list[WyckoffEvent]:
    events: list[WyckoffEvent] = []
    if len(candles) < 2:
        return events

    recent = candles[-8:]
    offset = len(candles) - len(recent)
    baseline_volume = _mean(c.volume for c in candles[-20:-8]) or _mean(c.volume for c in recent)

    for local_index, candle in enumerate(recent):
        index = offset + local_index
        volume_ratio = candle.volume / baseline_volume if baseline_volume else 1.0

        if candle.close > trading_range.resistance and volume_ratio >= 1.10 and candle.close > candle.open:
            events.append(
                WyckoffEvent(
                    code="SOS",
                    index=index,
                    price=candle.close,
                    confidence=min(95.0, round(70 + (volume_ratio - 1.1) * 25, 1)),
                    note="Bullish expansion above range resistance with supportive volume.",
                )
            )

        if candle.close < trading_range.support and volume_ratio >= 1.10 and candle.close < candle.open:
            events.append(
                WyckoffEvent(
                    code="SOW",
                    index=index,
                    price=candle.close,
                    confidence=min(95.0, round(70 + (volume_ratio - 1.1) * 25, 1)),
                    note="Bearish expansion below range support with supportive volume.",
                )
            )

    return events


def _dedupe_events(events: list[WyckoffEvent]) -> list[WyckoffEvent]:
    """Keep the strongest event for each code/index pair."""

    best: dict[tuple[str, int], WyckoffEvent] = {}
    for event in events:
        key = (event.code, event.index)
        existing = best.get(key)
        if existing is None or event.confidence > existing.confidence:
            best[key] = event
    return sorted(best.values(), key=lambda event: event.index)


def _infer_bias_phase(events: list[WyckoffEvent], candles: list[Candle], trading_range: TradingRange) -> tuple[str, str, float, str]:
    codes = [event.code for event in events]
    latest_close = candles[-1].close

    bullish_evidence = 0
    bearish_evidence = 0

    if "SC" in codes:
        bullish_evidence += 1
    if "ST" in codes:
        bullish_evidence += 1
    if "SPRING" in codes:
        bullish_evidence += 3
    if "SOS" in codes:
        bullish_evidence += 3

    if "BC" in codes:
        bearish_evidence += 1
    if "UT_TEST" in codes:
        bearish_evidence += 1
    if "UTAD" in codes:
        bearish_evidence += 3
    if "SOW" in codes:
        bearish_evidence += 3

    if latest_close > trading_range.resistance:
        bullish_evidence += 1
    elif latest_close < trading_range.support:
        bearish_evidence += 1

    if bullish_evidence >= bearish_evidence + 2:
        bias = "ACCUMULATION"
        if "SOS" in codes:
            phase = "D_TO_E"
            interpretation = "Potential accumulation with strength emerging above the trading range."
        elif "SPRING" in codes:
            phase = "C_TO_D"
            interpretation = "Potential accumulation after a spring-style liquidity sweep and reclaim."
        elif "SC" in codes and "ST" in codes:
            phase = "B_TO_C"
            interpretation = "Potential accumulation range with selling climax and secondary-test behavior."
        else:
            phase = "B"
            interpretation = "Potential accumulation range, but confirmation remains limited."
    elif bearish_evidence >= bullish_evidence + 2:
        bias = "DISTRIBUTION"
        if "SOW" in codes:
            phase = "D_TO_E"
            interpretation = "Potential distribution with weakness expanding below the trading range."
        elif "UTAD" in codes:
            phase = "C_TO_D"
            interpretation = "Potential distribution after an upthrust-style liquidity sweep and rejection."
        elif "BC" in codes and "UT_TEST" in codes:
            phase = "B_TO_C"
            interpretation = "Potential distribution range with buying climax and upper-range test behavior."
        else:
            phase = "B"
            interpretation = "Potential distribution range, but confirmation remains limited."
    else:
        bias = "NEUTRAL"
        phase = "UNCONFIRMED"
        interpretation = "Trading range detected, but Wyckoff evidence is mixed or insufficient."

    edge = abs(bullish_evidence - bearish_evidence)
    event_confidence = _mean(event.confidence for event in events[-5:]) if events else 35.0
    confidence = min(95.0, 35.0 + edge * 9.0 + max(0.0, event_confidence - 50.0) * 0.35)

    if bias == "NEUTRAL":
        confidence = min(confidence, 55.0)

    return bias, phase, round(confidence, 1), interpretation


def analyze_wyckoff(market: MarketData, lookback: int = 30) -> WyckoffAnalysis:
    """Run heuristic Wyckoff analysis on the 4H structure of one market."""

    is_valid, errors = validate_market_data(market)
    if not is_valid:
        return WyckoffAnalysis(
            symbol=market.symbol,
            bias="UNKNOWN",
            phase="INVALID_DATA",
            confidence=0.0,
            trading_range=None,
            events=[],
            interpretation="Required market data is unavailable.",
            errors=errors,
        )

    candles = market.four_hour
    trading_range = detect_trading_range(candles, lookback=lookback)
    if trading_range is None:
        return WyckoffAnalysis(
            symbol=market.symbol,
            bias="NEUTRAL",
            phase="NO_RANGE",
            confidence=20.0,
            trading_range=None,
            events=[],
            interpretation="No sufficiently stable 4H trading range was detected.",
            errors=[],
        )

    events = _dedupe_events(
        _detect_climaxes(candles, trading_range)
        + _detect_range_tests(candles, trading_range)
        + _detect_spring_upthrust(candles, trading_range)
        + _detect_sos_sow(candles, trading_range)
    )

    bias, phase, confidence, interpretation = _infer_bias_phase(events, candles, trading_range)

    return WyckoffAnalysis(
        symbol=market.symbol,
        bias=bias,
        phase=phase,
        confidence=confidence,
        trading_range=trading_range,
        events=events,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("Wyckoff analysis engine ready.")
