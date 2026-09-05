"""
Smart Money Concepts (SMC) Market Structure Engine
Wyckoff + SMC Spot Swing Agent

V1 focuses on deterministic market-structure primitives:
- Swing High / Swing Low detection
- Break of Structure (BOS)
- Change of Character (CHoCH)

It intentionally does not infer institutional intent. The engine converts
price structure into explicit, testable evidence for later liquidity,
imbalance, order-block and confluence layers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal

try:
    from .market_data import Candle, MarketData, validate_market_data
except ImportError:  # Allows: python src/smc.py
    from market_data import Candle, MarketData, validate_market_data


SwingKind = Literal["HIGH", "LOW"]
StructureEventKind = Literal["BOS", "CHOCH"]
Direction = Literal["BULLISH", "BEARISH"]


@dataclass(frozen=True)
class SwingPoint:
    kind: SwingKind
    index: int
    timestamp: int
    price: float
    strength: int


@dataclass(frozen=True)
class StructureEvent:
    kind: StructureEventKind
    direction: Direction
    index: int
    timestamp: int
    break_price: float
    broken_swing_index: int
    broken_swing_price: float
    confirmation: str


@dataclass
class SMCAnalysis:
    symbol: str
    timeframe: str
    bias: str
    trend_state: str
    swings: list[SwingPoint]
    events: list[StructureEvent]
    latest_swing_high: SwingPoint | None
    latest_swing_low: SwingPoint | None
    interpretation: str
    errors: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _timeframe_candles(market: MarketData, timeframe: str) -> list[Candle]:
    mapping = {
        "1d": market.daily,
        "4h": market.four_hour,
        "1h": market.one_hour,
        "15m": market.fifteen_minute,
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    return mapping[timeframe]


def detect_swings(
    candles: list[Candle],
    left: int = 2,
    right: int = 2,
) -> list[SwingPoint]:
    """Detect confirmed pivot highs/lows using symmetric neighboring candles.

    A swing is confirmed only after `right` candles have printed, which avoids
    using future-unconfirmed pivots in downstream structure analysis.
    """

    if left < 1 or right < 1:
        raise ValueError("left and right must both be >= 1")

    if len(candles) < left + right + 1:
        return []

    swings: list[SwingPoint] = []

    for index in range(left, len(candles) - right):
        candle = candles[index]
        left_window = candles[index - left : index]
        right_window = candles[index + 1 : index + right + 1]

        is_high = all(candle.high > other.high for other in left_window) and all(
            candle.high >= other.high for other in right_window
        )
        is_low = all(candle.low < other.low for other in left_window) and all(
            candle.low <= other.low for other in right_window
        )

        if is_high:
            swings.append(
                SwingPoint(
                    kind="HIGH",
                    index=index,
                    timestamp=candle.timestamp,
                    price=candle.high,
                    strength=min(left, right),
                )
            )

        if is_low:
            swings.append(
                SwingPoint(
                    kind="LOW",
                    index=index,
                    timestamp=candle.timestamp,
                    price=candle.low,
                    strength=min(left, right),
                )
            )

    return sorted(swings, key=lambda swing: (swing.index, swing.kind))


def _compress_same_kind_swings(swings: list[SwingPoint]) -> list[SwingPoint]:
    """Collapse consecutive same-kind pivots to the more extreme pivot."""

    if not swings:
        return []

    compressed: list[SwingPoint] = []

    for swing in swings:
        if not compressed or compressed[-1].kind != swing.kind:
            compressed.append(swing)
            continue

        previous = compressed[-1]
        if swing.kind == "HIGH" and swing.price >= previous.price:
            compressed[-1] = swing
        elif swing.kind == "LOW" and swing.price <= previous.price:
            compressed[-1] = swing

    return compressed


def classify_swing_structure(swings: list[SwingPoint]) -> str:
    """Classify the most recent confirmed swing structure."""

    highs = [s for s in swings if s.kind == "HIGH"]
    lows = [s for s in swings if s.kind == "LOW"]

    if len(highs) < 2 or len(lows) < 2:
        return "UNCONFIRMED"

    higher_high = highs[-1].price > highs[-2].price
    lower_high = highs[-1].price < highs[-2].price
    higher_low = lows[-1].price > lows[-2].price
    lower_low = lows[-1].price < lows[-2].price

    if higher_high and higher_low:
        return "BULLISH"
    if lower_high and lower_low:
        return "BEARISH"
    return "RANGE_OR_TRANSITION"


def detect_structure_events(
    candles: list[Candle],
    swings: list[SwingPoint],
    use_close_confirmation: bool = True,
) -> list[StructureEvent]:
    """Detect BOS and CHoCH from confirmed swing breaks.

    BOS continues the currently established structural direction.
    CHoCH is the first confirmed break against that established direction.
    Each swing level can be consumed only once, preventing duplicate events
    from repeated closes beyond the same level.
    """

    swings = _compress_same_kind_swings(swings)
    if len(swings) < 3:
        return []

    events: list[StructureEvent] = []
    consumed: set[tuple[str, int]] = set()
    active_bias: str | None = None

    for candle_index, candle in enumerate(candles):
        prior_highs = [
            swing
            for swing in swings
            if swing.kind == "HIGH" and swing.index < candle_index
        ]
        prior_lows = [
            swing
            for swing in swings
            if swing.kind == "LOW" and swing.index < candle_index
        ]

        if not prior_highs or not prior_lows:
            continue

        last_high = prior_highs[-1]
        last_low = prior_lows[-1]

        bullish_value = candle.close if use_close_confirmation else candle.high
        bearish_value = candle.close if use_close_confirmation else candle.low

        breaks_high = (
            bullish_value > last_high.price
            and ("HIGH", last_high.index) not in consumed
        )
        breaks_low = (
            bearish_value < last_low.price
            and ("LOW", last_low.index) not in consumed
        )

        # Outside bars can technically break both sides. Ignore ambiguous dual
        # breaks unless the close clearly resolves on one side of structure.
        if breaks_high and breaks_low:
            if candle.close > last_high.price:
                breaks_low = False
            elif candle.close < last_low.price:
                breaks_high = False
            else:
                continue

        if breaks_high:
            event_kind: StructureEventKind = (
                "CHOCH" if active_bias == "BEARISH" else "BOS"
            )
            events.append(
                StructureEvent(
                    kind=event_kind,
                    direction="BULLISH",
                    index=candle_index,
                    timestamp=candle.timestamp,
                    break_price=bullish_value,
                    broken_swing_index=last_high.index,
                    broken_swing_price=last_high.price,
                    confirmation="CLOSE" if use_close_confirmation else "WICK",
                )
            )
            consumed.add(("HIGH", last_high.index))
            active_bias = "BULLISH"

        elif breaks_low:
            event_kind = "CHOCH" if active_bias == "BULLISH" else "BOS"
            events.append(
                StructureEvent(
                    kind=event_kind,
                    direction="BEARISH",
                    index=candle_index,
                    timestamp=candle.timestamp,
                    break_price=bearish_value,
                    broken_swing_index=last_low.index,
                    broken_swing_price=last_low.price,
                    confirmation="CLOSE" if use_close_confirmation else "WICK",
                )
            )
            consumed.add(("LOW", last_low.index))
            active_bias = "BEARISH"

    return events


def _analysis_bias(events: list[StructureEvent], swing_state: str) -> tuple[str, str]:
    if events:
        latest = events[-1]
        if latest.kind == "CHOCH":
            return latest.direction, f"{latest.direction}_TRANSITION"
        return latest.direction, f"{latest.direction}_CONTINUATION"

    if swing_state in {"BULLISH", "BEARISH"}:
        return swing_state, f"{swing_state}_STRUCTURE"

    return "NEUTRAL", swing_state


def analyze_smc(
    market: MarketData,
    timeframe: str = "1h",
    swing_left: int = 2,
    swing_right: int = 2,
    use_close_confirmation: bool = True,
) -> SMCAnalysis:
    """Analyze SMC market structure on one selected timeframe."""

    timeframe = timeframe.lower()
    if timeframe not in {"1d", "4h", "1h", "15m"}:
        raise ValueError(f"Unsupported timeframe: {timeframe}")

    is_valid, errors = validate_market_data(
        market,
        required_timeframes=[timeframe],
        require_current_price=False,
    )
    if not is_valid:
        return SMCAnalysis(
            symbol=market.symbol,
            timeframe=timeframe,
            bias="UNKNOWN",
            trend_state="INVALID_DATA",
            swings=[],
            events=[],
            latest_swing_high=None,
            latest_swing_low=None,
            interpretation="Required market structure data is unavailable.",
            errors=errors,
        )

    candles = _timeframe_candles(market, timeframe)
    swings = _compress_same_kind_swings(
        detect_swings(candles, left=swing_left, right=swing_right)
    )
    swing_state = classify_swing_structure(swings)
    events = detect_structure_events(
        candles,
        swings,
        use_close_confirmation=use_close_confirmation,
    )

    latest_high = next((s for s in reversed(swings) if s.kind == "HIGH"), None)
    latest_low = next((s for s in reversed(swings) if s.kind == "LOW"), None)
    bias, trend_state = _analysis_bias(events, swing_state)

    if events:
        latest = events[-1]
        if latest.kind == "CHOCH":
            interpretation = (
                f"{latest.direction.title()} CHoCH detected: structure has broken "
                "against the prior active direction."
            )
        else:
            interpretation = (
                f"{latest.direction.title()} BOS detected: structure currently "
                "supports continuation in that direction."
            )
    elif swing_state == "BULLISH":
        interpretation = "Confirmed higher-high / higher-low swing structure."
    elif swing_state == "BEARISH":
        interpretation = "Confirmed lower-high / lower-low swing structure."
    else:
        interpretation = "Market structure is mixed or not yet sufficiently confirmed."

    return SMCAnalysis(
        symbol=market.symbol,
        timeframe=timeframe,
        bias=bias,
        trend_state=trend_state,
        swings=swings,
        events=events,
        latest_swing_high=latest_high,
        latest_swing_low=latest_low,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("SMC market structure engine ready.")
