"""Unit tests for the SMC structure + liquidity + imbalance engine."""

from src.market_data import Candle, MarketData
from src.smc import (
    analyze_smc,
    detect_fair_value_gaps,
    detect_liquidity_pools,
    detect_liquidity_sweeps,
    detect_structure_events,
    detect_swings,
)


def candle(index: int, open_price: float, high: float, low: float, close: float, volume: float = 1_000.0) -> Candle:
    return Candle(timestamp=index * 3_600_000, open=open_price, high=high, low=low, close=close, volume=volume)


def make_bullish_structure() -> list[Candle]:
    return [candle(0,100,101,99,100),candle(1,100,103,100,102),candle(2,102,106,101,105),candle(3,105,104,99,100),candle(4,100,102,96,98),candle(5,98,104,98,103),candle(6,103,108,102,107),candle(7,107,106,101,103),candle(8,103,105,99,101),candle(9,101,107,101,106),candle(10,106,110,105,109),candle(11,109,112,108,111),candle(12,111,113,110,112)]


def make_bullish_then_bearish_choch() -> list[Candle]:
    candles = make_bullish_structure()
    candles.extend([candle(13,112,113,108,109),candle(14,109,110,103,104),candle(15,104,105,97,98),candle(16,98,100,95,96)])
    return candles


def make_equal_highs_buy_side_sweep() -> list[Candle]:
    return [candle(0,100,101,99,100),candle(1,100,105,100,104),candle(2,104,103,98,99),candle(3,99,104.95,99,104),candle(4,104,103,98.5,100),candle(5,100,106.2,99.5,104.7),candle(6,104.7,104.8,100,101)]


def make_equal_lows_sell_side_sweep() -> list[Candle]:
    return [candle(0,100,102,99,101),candle(1,101,103,95,96),candle(2,96,102,97,101),candle(3,101,102,95.08,96),candle(4,96,101,97,100),candle(5,100,101,93.8,95.4),candle(6,95.4,100,95,99)]


def make_bullish_fvg() -> list[Candle]:
    return [
        candle(0,100,101,99,100),
        candle(1,100,101,99.5,100.5),
        candle(2,100.5,101.5,100,101),
        candle(3,101,108,100.8,107),  # displacement candle
        candle(4,107,110,103,109),    # low 103 > candle 2 high 101.5
        candle(5,109,111,104,110),    # remains above gap
    ]


def make_bearish_fvg() -> list[Candle]:
    return [
        candle(0,110,111,109,110),
        candle(1,110,110.5,109,109.5),
        candle(2,109.5,110,108.5,109),
        candle(3,109,109.2,101,102),  # displacement candle
        candle(4,102,107,100,101),    # high 107 < candle 2 low 108.5
        candle(5,101,106,99,100),
    ]


def market_with_only_one_hour(candles: list[Candle]) -> MarketData:
    return MarketData(symbol="TESTUSDT", current_price=None, daily=[], four_hour=[], one_hour=candles, fifteen_minute=[])


def test_detect_swings_finds_confirmed_highs_and_lows() -> None:
    swings = detect_swings(make_bullish_structure(), left=1, right=1)
    assert any(s.index == 2 for s in swings if s.kind == "HIGH")
    assert any(s.index == 4 for s in swings if s.kind == "LOW")
    assert all(s.strength == 1 for s in swings)


def test_bullish_break_registers_bos() -> None:
    candles = make_bullish_structure(); swings = detect_swings(candles, left=1, right=1); events = detect_structure_events(candles, swings)
    bullish = [e for e in events if e.direction == "BULLISH"]
    assert bullish and bullish[-1].kind == "BOS" and bullish[-1].confirmation == "CLOSE"
    assert bullish[-1].break_price > bullish[-1].broken_swing_price


def test_bearish_break_after_bullish_structure_registers_choch() -> None:
    result = analyze_smc(market_with_only_one_hour(make_bullish_then_bearish_choch()), timeframe="1h", swing_left=1, swing_right=1)
    assert any(e.kind == "CHOCH" and e.direction == "BEARISH" for e in result.events)
    assert result.bias == "BEARISH" and result.trend_state == "BEARISH_TRANSITION" and result.errors == []


def test_wick_only_break_does_not_confirm_when_close_confirmation_enabled() -> None:
    candles = [candle(0,100,101,99,100),candle(1,100,104,100,103),candle(2,103,106,102,105),candle(3,105,104,99,100),candle(4,100,102,96,98),candle(5,98,107,98,105),candle(6,105,105.5,100,101)]
    events = detect_structure_events(candles, detect_swings(candles,left=1,right=1), use_close_confirmation=True)
    assert not any(e.direction == "BULLISH" and e.broken_swing_price == 106 for e in events)


def test_equal_highs_form_buy_side_liquidity_pool() -> None:
    candles=make_equal_highs_buy_side_sweep(); pools=detect_liquidity_pools(detect_swings(candles,left=1,right=1), tolerance_pct=0.25); buy=[p for p in pools if p.side=="BUY_SIDE"]
    assert buy and buy[0].kind=="EQUAL_HIGHS" and buy[0].touches>=2 and 104.9<=buy[0].level<=105.1


def test_equal_lows_form_sell_side_liquidity_pool() -> None:
    candles=make_equal_lows_sell_side_sweep(); pools=detect_liquidity_pools(detect_swings(candles,left=1,right=1), tolerance_pct=0.25); sell=[p for p in pools if p.side=="SELL_SIDE"]
    assert sell and sell[0].kind=="EQUAL_LOWS" and sell[0].touches>=2 and 94.9<=sell[0].level<=95.2


def test_buy_side_liquidity_sweep_requires_reclaim_close() -> None:
    candles=make_equal_highs_buy_side_sweep(); pools=detect_liquidity_pools(detect_swings(candles,left=1,right=1),tolerance_pct=0.25); sweeps=detect_liquidity_sweeps(candles,pools); buy=[s for s in sweeps if s.side=="BUY_SIDE"]
    assert buy and buy[0].direction=="BEARISH" and buy[0].extreme_price>buy[0].pool_level and buy[0].close_price<=buy[0].pool_level


def test_sell_side_liquidity_sweep_requires_reclaim_close() -> None:
    candles=make_equal_lows_sell_side_sweep(); pools=detect_liquidity_pools(detect_swings(candles,left=1,right=1),tolerance_pct=0.25); sweeps=detect_liquidity_sweeps(candles,pools); sell=[s for s in sweeps if s.side=="SELL_SIDE"]
    assert sell and sell[0].direction=="BULLISH" and sell[0].extreme_price<sell[0].pool_level and sell[0].close_price>=sell[0].pool_level


def test_close_acceptance_beyond_pool_is_not_a_sweep() -> None:
    candles=make_equal_highs_buy_side_sweep(); candles[5]=candle(5,100,106.2,99.5,105.7); pools=detect_liquidity_pools(detect_swings(candles,left=1,right=1),tolerance_pct=0.25); sweeps=detect_liquidity_sweeps(candles,pools)
    assert not any(s.side=="BUY_SIDE" and s.index==5 for s in sweeps)


def test_bullish_fvg_detected_after_displacement() -> None:
    gaps = detect_fair_value_gaps(make_bullish_fvg(), min_gap_pct=0.05, min_displacement_ratio=1.2)
    bullish = [g for g in gaps if g.kind == "BULLISH_FVG"]
    assert bullish
    gap = bullish[0]
    assert gap.lower == 101.5 and gap.upper == 103
    assert gap.direction == "BULLISH" and gap.status == "OPEN"
    assert gap.displacement_ratio >= 1.2


def test_bearish_fvg_detected_after_displacement() -> None:
    gaps = detect_fair_value_gaps(make_bearish_fvg(), min_gap_pct=0.05, min_displacement_ratio=1.2)
    bearish = [g for g in gaps if g.kind == "BEARISH_FVG"]
    assert bearish
    gap = bearish[0]
    assert gap.lower == 107 and gap.upper == 108.5
    assert gap.direction == "BEARISH" and gap.status == "OPEN"


def test_fvg_tracks_partial_and_full_mitigation() -> None:
    candles = make_bullish_fvg()
    candles.extend([candle(6,110,110.5,102.4,104), candle(7,104,105,101.2,102)])
    gaps = detect_fair_value_gaps(candles, min_gap_pct=0.05, min_displacement_ratio=1.2)
    target = next(g for g in gaps if g.kind == "BULLISH_FVG" and g.lower == 101.5 and g.upper == 103)
    assert target.status == "MITIGATED"
    assert target.mitigation_index == 7


def test_small_gap_without_displacement_is_filtered() -> None:
    candles = [candle(0,100,101,99,100),candle(1,100,101.2,99.8,100.5),candle(2,100.5,102,101.1,101.5)]
    assert detect_fair_value_gaps(candles, min_gap_pct=0.05, min_displacement_ratio=1.2) == []


def test_analyze_smc_exposes_liquidity_and_fvg_evidence() -> None:
    result = analyze_smc(market_with_only_one_hour(make_bullish_fvg()), timeframe="1h", swing_left=1, swing_right=1, fvg_min_displacement_ratio=1.2)
    assert result.fair_value_gaps
    assert any(g.kind == "BULLISH_FVG" for g in result.fair_value_gaps)
    assert result.errors == []


def test_analyze_smc_exposes_liquidity_evidence() -> None:
    result=analyze_smc(market_with_only_one_hour(make_equal_lows_sell_side_sweep()),timeframe="1h",swing_left=1,swing_right=1,liquidity_tolerance_pct=0.25)
    assert result.liquidity_pools and result.liquidity_sweeps and any(s.side=="SELL_SIDE" for s in result.liquidity_sweeps) and result.errors==[]


def test_smc_requires_only_selected_timeframe() -> None:
    result=analyze_smc(market_with_only_one_hour(make_bullish_structure()),timeframe="1h",swing_left=1,swing_right=1)
    assert result.trend_state!="INVALID_DATA" and result.errors==[] and result.timeframe=="1h"


def test_missing_selected_timeframe_is_invalid() -> None:
    market=MarketData(symbol="BROKENUSDT",current_price=None,daily=[],four_hour=[],one_hour=[],fifteen_minute=[]); result=analyze_smc(market,timeframe="1h")
    assert result.bias=="UNKNOWN" and result.trend_state=="INVALID_DATA" and result.liquidity_pools==[] and result.liquidity_sweeps==[] and result.fair_value_gaps==[] and "1H_DATA_UNAVAILABLE" in result.errors
