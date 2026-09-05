"""
Smart Money Concepts (SMC) Structure + Liquidity Engine
Wyckoff + SMC Spot Swing Agent

Current deterministic primitives:
- Swing High / Swing Low detection
- Break of Structure (BOS)
- Change of Character (CHoCH)
- Equal High / Equal Low liquidity pools
- Buy-side / Sell-side liquidity sweeps

The engine does not infer institutional intent. It converts observable price
structure into explicit, testable evidence for later imbalance, order-block
and Wyckoff + SMC confluence layers.
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
LiquiditySide = Literal["BUY_SIDE", "SELL_SIDE"]
LiquidityPoolKind = Literal["EQUAL_HIGHS", "EQUAL_LOWS"]


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


@dataclass(frozen=True)
class LiquidityPool:
    kind: LiquidityPoolKind
    side: LiquiditySide
    level: float
    tolerance_pct: float
    swing_indices: tuple[int, ...]
    first_index: int
    last_index: int
    touches: int


@dataclass(frozen=True)
class LiquiditySweep:
    side: LiquiditySide
    direction: Direction
    index: int
    timestamp: int
    pool_level: float
    extreme_price: float
    close_price: float
    penetration_pct: float
    pool_kind: LiquidityPoolKind
    pool_last_index: int


@dataclass
class SMCAnalysis:
    symbol: str
    timeframe: str
    bias: str
    trend_state: str
    swings: list[SwingPoint]
    events: list[StructureEvent]
    liquidity_pools: list[LiquidityPool]
    liquidity_sweeps: list[LiquiditySweep]
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
    """Detect confirmed pivot highs/lows using symmetric neighboring candles."""

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
    """Detect BOS and CHoCH from confirmed swing breaks."""

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


def detect_liquidity_pools(
    swings: list[SwingPoint],
    tolerance_pct: float = 0.25,
    min_touches: int = 2,
) -> list[LiquidityPool]:
    """Group nearby confirmed swing highs/lows into liquidity pools.

    `tolerance_pct` is the maximum percentage distance from the running pool
    level. Equal highs map to buy-side liquidity; equal lows map to sell-side.
    """

    if tolerance_pct <= 0:
        raise ValueError("tolerance_pct must be > 0")
    if min_touches < 2:
        raise ValueError("min_touches must be >= 2")

    pools: list[LiquidityPool] = []

    for kind in ("HIGH", "LOW"):
        candidates = sorted(
            (s for s in swings if s.kind == kind),
            key=lambda s: s.index,
        )
        groups: list[list[SwingPoint]] = []

        for swing in candidates:
            matched_group: list[SwingPoint] | None = None
            best_distance = float("inf")

            for group in groups:
                level = sum(item.price for item in group) / len(group)
                distance_pct = abs(swing.price - level) / level * 100 if level else 0.0
                if distance_pct <= tolerance_pct and distance_pct < best_distance:
                    matched_group = group
                    best_distance = distance_pct

            if matched_group is None:
                groups.append([swing])
            else:
                matched_group.append(swing)

        for group in groups:
            if len(group) < min_touches:
                continue

            level = sum(item.price for item in group) / len(group)
            pools.append(
                LiquidityPool(
                    kind="EQUAL_HIGHS" if kind == "HIGH" else "EQUAL_LOWS",
                    side="BUY_SIDE" if kind == "HIGH" else "SELL_SIDE",
                    level=round(level, 8),
                    tolerance_pct=tolerance_pct,
                    swing_indices=tuple(item.index for item in group),
                    first_index=group[0].index,
                    last_index=group[-1].index,
                    touches=len(group),
                )
            )

    return sorted(pools, key=lambda pool: (pool.last_index, pool.side))


def detect_liquidity_sweeps(
    candles: list[Candle],
    pools: list[LiquidityPool],
    min_penetration_pct: float = 0.01,
) -> list[LiquiditySweep]:
    """Detect wick-through + close-reclaim sweeps of established pools.

    A buy-side sweep trades above equal highs but closes back at/below the pool.
    A sell-side sweep trades below equal lows but closes back at/above the pool.
    A close that accepts beyond the pool is deliberately not classified as a
    sweep; downstream structure logic can treat it as a potential break instead.
    """

    if min_penetration_pct < 0:
        raise ValueError("min_penetration_pct must be >= 0")

    sweeps: list[LiquiditySweep] = []
    consumed: set[tuple[LiquiditySide, int]] = set()

    for pool in pools:
        if pool.level <= 0:
            continue

        for index in range(pool.last_index + 1, len(candles)):
            candle = candles[index]
            key = (pool.side, pool.last_index)
            if key in consumed:
                break

            if pool.side == "BUY_SIDE":
                penetration_pct = (candle.high - pool.level) / pool.level * 100
                swept = (
                    candle.high > pool.level
                    and penetration_pct >= min_penetration_pct
                    and candle.close <= pool.level
                )
                if swept:
                    sweeps.append(
                        LiquiditySweep(
                            side="BUY_SIDE",
                            direction="BEARISH",
                            index=index,
                            timestamp=candle.timestamp,
                            pool_level=pool.level,
                            extreme_price=candle.high,
                            close_price=candle.close,
                            penetration_pct=round(penetration_pct, 4),
                            pool_kind=pool.kind,
                            pool_last_index=pool.last_index,
                        )
                    )
                    consumed.add(key)

            else:
                penetration_pct = (pool.level - candle.low) / pool.level * 100
                swept = (
                    candle.low < pool.level
                    and penetration_pct >= min_penetration_pct
                    and candle.close >= pool.level
                )
                if swept:
                    sweeps.append(
                        LiquiditySweep(
                            side="SELL_SIDE",
                            direction="BULLISH",
                            index=index,
                            timestamp=candle.timestamp,
                            pool_level=pool.level,
                            extreme_price=candle.low,
                            close_price=candle.close,
                            penetration_pct=round(penetration_pct, 4),
                            pool_kind=pool.kind,
                            pool_last_index=pool.last_index,
                        )
                    )
                    consumed.add(key)

    return sorted(sweeps, key=lambda sweep: sweep.index)


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
    liquidity_tolerance_pct: float = 0.25,
) -> SMCAnalysis:
    """Analyze SMC structure and liquidity on one selected timeframe."""

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
            liquidity_pools=[],
            liquidity_sweeps=[],
            latest_swing_high=None,
            latest_swing_low=None,
            interpretation="Required SMC data is unavailable.",
            errors=errors,
        )

    candles = _timeframe_candles(market, timeframe)

    # Preserve every confirmed pivot for liquidity analysis. Equal highs/lows
    # are evidence precisely because multiple nearby pivots exist. Structure
    # analysis, by contrast, benefits from compressing consecutive same-kind
    # pivots to the more extreme one so BOS/CHoCH does not become noisy.
    raw_swings = detect_swings(candles, left=swing_left, right=swing_right)
    structure_swings = _compress_same_kind_swings(raw_swings)

    swing_state = classify_swing_structure(structure_swings)
    events = detect_structure_events(
        candles,
        structure_swings,
        use_close_confirmation=use_close_confirmation,
    )
    liquidity_pools = detect_liquidity_pools(
        raw_swings,
        tolerance_pct=liquidity_tolerance_pct,
    )
    liquidity_sweeps = detect_liquidity_sweeps(candles, liquidity_pools)

    latest_high = next(
        (s for s in reversed(structure_swings) if s.kind == "HIGH"),
        None,
    )
    latest_low = next(
        (s for s in reversed(structure_swings) if s.kind == "LOW"),
        None,
    )
    bias, trend_state = _analysis_bias(events, swing_state)

    if liquidity_sweeps:
        latest_sweep = liquidity_sweeps[-1]
        interpretation = (
            f"{latest_sweep.side.replace('_', '-').title()} liquidity sweep detected "
            f"with {latest_sweep.direction.lower()} rejection."
        )
        if events:
            latest_event = events[-1]
            interpretation += (
                f" Latest structure event: {latest_event.direction.title()} "
                f"{latest_event.kind}."
            )
    elif events:
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
        swings=structure_swings,
        events=events,
        liquidity_pools=liquidity_pools,
        liquidity_sweeps=liquidity_sweeps,
        latest_swing_high=latest_high,
        latest_swing_low=latest_low,
        interpretation=interpretation,
        errors=[],
    )


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("SMC structure + liquidity engine ready.")
