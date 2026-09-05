"""
Smart Money Concepts (SMC) Structure + Liquidity + Imbalance Engine
Wyckoff + SMC Spot Swing Agent

Current deterministic primitives:
- Swing High / Swing Low detection
- Break of Structure (BOS)
- Change of Character (CHoCH)
- Equal High / Equal Low liquidity pools
- Buy-side / Sell-side liquidity sweeps
- Bullish / Bearish Fair Value Gaps (FVG)

The engine does not infer institutional intent. It converts observable price
structure into explicit, testable evidence for later order-block and
Wyckoff + SMC confluence layers.
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
FVGKind = Literal["BULLISH_FVG", "BEARISH_FVG"]
FVGStatus = Literal["OPEN", "PARTIALLY_MITIGATED", "MITIGATED"]


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


@dataclass(frozen=True)
class FairValueGap:
    kind: FVGKind
    direction: Direction
    index: int
    timestamp: int
    lower: float
    upper: float
    midpoint: float
    gap_pct: float
    displacement_ratio: float
    status: FVGStatus
    mitigation_index: int | None


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
    fair_value_gaps: list[FairValueGap]
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


def detect_swings(candles: list[Candle], left: int = 2, right: int = 2) -> list[SwingPoint]:
    """Detect confirmed pivot highs/lows using symmetric neighboring candles."""
    if left < 1 or right < 1:
        raise ValueError("left and right must both be >= 1")
    if len(candles) < left + right + 1:
        return []

    swings: list[SwingPoint] = []
    for index in range(left, len(candles) - right):
        candle = candles[index]
        left_window = candles[index - left:index]
        right_window = candles[index + 1:index + right + 1]
        is_high = all(candle.high > other.high for other in left_window) and all(candle.high >= other.high for other in right_window)
        is_low = all(candle.low < other.low for other in left_window) and all(candle.low <= other.low for other in right_window)
        if is_high:
            swings.append(SwingPoint("HIGH", index, candle.timestamp, candle.high, min(left, right)))
        if is_low:
            swings.append(SwingPoint("LOW", index, candle.timestamp, candle.low, min(left, right)))
    return sorted(swings, key=lambda swing: (swing.index, swing.kind))


def _compress_same_kind_swings(swings: list[SwingPoint]) -> list[SwingPoint]:
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


def detect_structure_events(candles: list[Candle], swings: list[SwingPoint], use_close_confirmation: bool = True) -> list[StructureEvent]:
    """Detect BOS and CHoCH from confirmed swing breaks."""
    swings = _compress_same_kind_swings(swings)
    if len(swings) < 3:
        return []
    events: list[StructureEvent] = []
    consumed: set[tuple[str, int]] = set()
    active_bias: str | None = None
    for candle_index, candle in enumerate(candles):
        prior_highs = [s for s in swings if s.kind == "HIGH" and s.index < candle_index]
        prior_lows = [s for s in swings if s.kind == "LOW" and s.index < candle_index]
        if not prior_highs or not prior_lows:
            continue
        last_high, last_low = prior_highs[-1], prior_lows[-1]
        bullish_value = candle.close if use_close_confirmation else candle.high
        bearish_value = candle.close if use_close_confirmation else candle.low
        breaks_high = bullish_value > last_high.price and ("HIGH", last_high.index) not in consumed
        breaks_low = bearish_value < last_low.price and ("LOW", last_low.index) not in consumed
        if breaks_high and breaks_low:
            if candle.close > last_high.price:
                breaks_low = False
            elif candle.close < last_low.price:
                breaks_high = False
            else:
                continue
        if breaks_high:
            event_kind: StructureEventKind = "CHOCH" if active_bias == "BEARISH" else "BOS"
            events.append(StructureEvent(event_kind, "BULLISH", candle_index, candle.timestamp, bullish_value, last_high.index, last_high.price, "CLOSE" if use_close_confirmation else "WICK"))
            consumed.add(("HIGH", last_high.index))
            active_bias = "BULLISH"
        elif breaks_low:
            event_kind = "CHOCH" if active_bias == "BULLISH" else "BOS"
            events.append(StructureEvent(event_kind, "BEARISH", candle_index, candle.timestamp, bearish_value, last_low.index, last_low.price, "CLOSE" if use_close_confirmation else "WICK"))
            consumed.add(("LOW", last_low.index))
            active_bias = "BEARISH"
    return events


def detect_liquidity_pools(swings: list[SwingPoint], tolerance_pct: float = 0.25, min_touches: int = 2) -> list[LiquidityPool]:
    """Group nearby confirmed swing highs/lows into liquidity pools."""
    if tolerance_pct <= 0:
        raise ValueError("tolerance_pct must be > 0")
    if min_touches < 2:
        raise ValueError("min_touches must be >= 2")
    pools: list[LiquidityPool] = []
    for kind in ("HIGH", "LOW"):
        candidates = sorted((s for s in swings if s.kind == kind), key=lambda s: s.index)
        groups: list[list[SwingPoint]] = []
        for swing in candidates:
            matched_group = None
            best_distance = float("inf")
            for group in groups:
                level = sum(item.price for item in group) / len(group)
                distance_pct = abs(swing.price - level) / level * 100 if level else 0.0
                if distance_pct <= tolerance_pct and distance_pct < best_distance:
                    matched_group, best_distance = group, distance_pct
            if matched_group is None:
                groups.append([swing])
            else:
                matched_group.append(swing)
        for group in groups:
            if len(group) < min_touches:
                continue
            level = sum(item.price for item in group) / len(group)
            pools.append(LiquidityPool("EQUAL_HIGHS" if kind == "HIGH" else "EQUAL_LOWS", "BUY_SIDE" if kind == "HIGH" else "SELL_SIDE", round(level, 8), tolerance_pct, tuple(item.index for item in group), group[0].index, group[-1].index, len(group)))
    return sorted(pools, key=lambda pool: (pool.last_index, pool.side))


def detect_liquidity_sweeps(candles: list[Candle], pools: list[LiquidityPool], min_penetration_pct: float = 0.01) -> list[LiquiditySweep]:
    """Detect wick-through + close-reclaim sweeps of established pools."""
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
                if candle.high > pool.level and penetration_pct >= min_penetration_pct and candle.close <= pool.level:
                    sweeps.append(LiquiditySweep("BUY_SIDE", "BEARISH", index, candle.timestamp, pool.level, candle.high, candle.close, round(penetration_pct, 4), pool.kind, pool.last_index))
                    consumed.add(key)
            else:
                penetration_pct = (pool.level - candle.low) / pool.level * 100
                if candle.low < pool.level and penetration_pct >= min_penetration_pct and candle.close >= pool.level:
                    sweeps.append(LiquiditySweep("SELL_SIDE", "BULLISH", index, candle.timestamp, pool.level, candle.low, candle.close, round(penetration_pct, 4), pool.kind, pool.last_index))
                    consumed.add(key)
    return sorted(sweeps, key=lambda sweep: sweep.index)


def _average_range(candles: list[Candle], end_index: int, lookback: int = 10) -> float:
    start = max(0, end_index - lookback)
    previous = candles[start:end_index]
    ranges = [max(c.high - c.low, 0.0) for c in previous]
    return sum(ranges) / len(ranges) if ranges else 0.0


def detect_fair_value_gaps(candles: list[Candle], min_gap_pct: float = 0.05, min_displacement_ratio: float = 1.20) -> list[FairValueGap]:
    """Detect three-candle FVGs and track later mitigation.

    Bullish FVG: candle[i].low > candle[i-2].high.
    Bearish FVG: candle[i].high < candle[i-2].low.
    The middle candle must show displacement relative to its preceding average
    range, which filters tiny mechanical gaps that lack meaningful expansion.
    """
    if min_gap_pct < 0:
        raise ValueError("min_gap_pct must be >= 0")
    if min_displacement_ratio <= 0:
        raise ValueError("min_displacement_ratio must be > 0")

    gaps: list[FairValueGap] = []
    for index in range(2, len(candles)):
        first, middle, third = candles[index - 2], candles[index - 1], candles[index]
        baseline = _average_range(candles, index - 1)
        middle_range = max(middle.high - middle.low, 0.0)
        displacement_ratio = middle_range / baseline if baseline > 0 else 1.0
        if displacement_ratio < min_displacement_ratio:
            continue

        direction: Direction | None = None
        kind: FVGKind | None = None
        lower = upper = 0.0
        if third.low > first.high:
            direction, kind = "BULLISH", "BULLISH_FVG"
            lower, upper = first.high, third.low
        elif third.high < first.low:
            direction, kind = "BEARISH", "BEARISH_FVG"
            lower, upper = third.high, first.low
        else:
            continue

        midpoint = (lower + upper) / 2
        gap_pct = (upper - lower) / midpoint * 100 if midpoint else 0.0
        if gap_pct < min_gap_pct:
            continue

        status: FVGStatus = "OPEN"
        mitigation_index: int | None = None
        for later_index in range(index + 1, len(candles)):
            later = candles[later_index]
            if direction == "BULLISH":
                if later.low <= lower:
                    status, mitigation_index = "MITIGATED", later_index
                    break
                if later.low < upper:
                    status = "PARTIALLY_MITIGATED"
                    mitigation_index = later_index
            else:
                if later.high >= upper:
                    status, mitigation_index = "MITIGATED", later_index
                    break
                if later.high > lower:
                    status = "PARTIALLY_MITIGATED"
                    mitigation_index = later_index

        gaps.append(FairValueGap(kind, direction, index, third.timestamp, round(lower, 8), round(upper, 8), round(midpoint, 8), round(gap_pct, 4), round(displacement_ratio, 3), status, mitigation_index))
    return gaps


def _analysis_bias(events: list[StructureEvent], swing_state: str) -> tuple[str, str]:
    if events:
        latest = events[-1]
        if latest.kind == "CHOCH":
            return latest.direction, f"{latest.direction}_TRANSITION"
        return latest.direction, f"{latest.direction}_CONTINUATION"
    if swing_state in {"BULLISH", "BEARISH"}:
        return swing_state, f"{swing_state}_STRUCTURE"
    return "NEUTRAL", swing_state


def analyze_smc(market: MarketData, timeframe: str = "1h", swing_left: int = 2, swing_right: int = 2, use_close_confirmation: bool = True, liquidity_tolerance_pct: float = 0.25, fvg_min_gap_pct: float = 0.05, fvg_min_displacement_ratio: float = 1.20) -> SMCAnalysis:
    """Analyze SMC structure, liquidity and imbalance on one timeframe."""
    timeframe = timeframe.lower()
    if timeframe not in {"1d", "4h", "1h", "15m"}:
        raise ValueError(f"Unsupported timeframe: {timeframe}")
    is_valid, errors = validate_market_data(market, required_timeframes=[timeframe], require_current_price=False)
    if not is_valid:
        return SMCAnalysis(market.symbol, timeframe, "UNKNOWN", "INVALID_DATA", [], [], [], [], [], None, None, "Required SMC data is unavailable.", errors)

    candles = _timeframe_candles(market, timeframe)
    raw_swings = detect_swings(candles, left=swing_left, right=swing_right)
    structure_swings = _compress_same_kind_swings(raw_swings)
    swing_state = classify_swing_structure(structure_swings)
    events = detect_structure_events(candles, structure_swings, use_close_confirmation=use_close_confirmation)
    liquidity_pools = detect_liquidity_pools(raw_swings, tolerance_pct=liquidity_tolerance_pct)
    liquidity_sweeps = detect_liquidity_sweeps(candles, liquidity_pools)
    fair_value_gaps = detect_fair_value_gaps(candles, min_gap_pct=fvg_min_gap_pct, min_displacement_ratio=fvg_min_displacement_ratio)

    latest_high = next((s for s in reversed(structure_swings) if s.kind == "HIGH"), None)
    latest_low = next((s for s in reversed(structure_swings) if s.kind == "LOW"), None)
    bias, trend_state = _analysis_bias(events, swing_state)

    open_gaps = [gap for gap in fair_value_gaps if gap.status != "MITIGATED"]
    if liquidity_sweeps:
        latest_sweep = liquidity_sweeps[-1]
        interpretation = f"{latest_sweep.side.replace('_', '-').title()} liquidity sweep detected with {latest_sweep.direction.lower()} rejection."
        if events:
            latest_event = events[-1]
            interpretation += f" Latest structure event: {latest_event.direction.title()} {latest_event.kind}."
        if open_gaps:
            latest_gap = open_gaps[-1]
            interpretation += f" Active {latest_gap.kind.replace('_', ' ').lower()} remains as imbalance evidence."
    elif events:
        latest = events[-1]
        interpretation = f"{latest.direction.title()} {'CHoCH detected: structure has broken against the prior active direction.' if latest.kind == 'CHOCH' else 'BOS detected: structure currently supports continuation in that direction.'}"
        if open_gaps:
            interpretation += f" {len(open_gaps)} active FVG(s) detected."
    elif open_gaps:
        interpretation = f"{len(open_gaps)} active fair value gap(s) detected, but structure confirmation remains limited."
    elif swing_state == "BULLISH":
        interpretation = "Confirmed higher-high / higher-low swing structure."
    elif swing_state == "BEARISH":
        interpretation = "Confirmed lower-high / lower-low swing structure."
    else:
        interpretation = "Market structure is mixed or not yet sufficiently confirmed."

    return SMCAnalysis(market.symbol, timeframe, bias, trend_state, structure_swings, events, liquidity_pools, liquidity_sweeps, fair_value_gaps, latest_high, latest_low, interpretation, [])


if __name__ == "__main__":
    print("Wyckoff + SMC Spot Swing Agent")
    print("SMC structure + liquidity + imbalance engine ready.")
