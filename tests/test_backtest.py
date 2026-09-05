"""Unit tests for the conservative trade simulation backtest engine."""

from types import SimpleNamespace

from src.backtest import BacktestConfig, run_backtest
from src.market_data import Candle, MarketData
from src.replay import ReplayResult, ReplayStep


def candle(index: int, open_price: float, high: float, low: float, close: float) -> Candle:
    return Candle(index * 3_600_000, open_price, high, low, close, 1_000.0)


def market(candles: list[Candle]) -> MarketData:
    return MarketData("TESTUSDT", candles[-1].close, [], [], candles, [])


def decision(direction: str, entry: float, stop: float, target: float, size: float = 1_000.0):
    action = "ENTER_LONG" if direction == "LONG" else "ENTER_SHORT"
    execution = SimpleNamespace(
        allowed=True,
        planned_entry=entry,
        stop_price=stop,
        target_price=target,
        position_size_quote=size,
    )
    return SimpleNamespace(
        execution=execution,
        confluence=SimpleNamespace(classification=f"HIGH_CONVICTION_{direction == 'LONG' and 'BULLISH' or 'BEARISH'}", confidence=82.0),
        wyckoff=SimpleNamespace(phase="D_TO_E"),
        scan=SimpleNamespace(score=80.0),
        action=action,
    )


def replay_step(index: int, direction: str, entry: float, stop: float, target: float, size: float = 1_000.0) -> ReplayStep:
    d = decision(direction, entry, stop, target, size)
    return ReplayStep(
        bar_index=index,
        bar_timestamp=index * 3_600_000,
        decision_time=(index + 1) * 3_600_000,
        current_price=entry,
        action=d.action,
        decision=d,
    )


def replay(steps: list[ReplayStep]) -> ReplayResult:
    return ReplayResult(
        symbol="TESTUSDT",
        reference_timeframe="1h",
        steps=steps,
        action_counts={},
        first_decision_time=steps[0].decision_time if steps else None,
        last_decision_time=steps[-1].decision_time if steps else None,
        errors=[],
    )


def test_long_trade_hits_target_on_future_bar() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 104, 99, 103),
        candle(2, 103, 111, 102, 110),
    ]
    result = run_backtest(
        replay([replay_step(0, "LONG", 100, 95, 110)]),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
    )
    assert result.total_trades == 1
    assert result.trades[0].outcome == "WIN"
    assert result.trades[0].exit_bar_index == 2
    assert result.trades[0].gross_r == 2.0
    assert result.final_equity > result.initial_equity


def test_same_bar_stop_and_target_uses_stop_conservatively() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 111, 94, 105),
    ]
    result = run_backtest(
        replay([replay_step(0, "LONG", 100, 95, 110)]),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=0, slippage_bps_per_side=0, conservative_same_bar=True),
    )
    trade = result.trades[0]
    assert trade.exit_reason == "STOP"
    assert trade.outcome == "LOSS"
    assert trade.gross_r == -1.0


def test_entry_bar_extremes_are_not_used_for_outcome() -> None:
    candles = [
        candle(0, 100, 120, 90, 100),  # both levels touched before decision at this bar close
        candle(1, 100, 108, 97, 105),
        candle(2, 105, 111, 104, 110),
    ]
    result = run_backtest(
        replay([replay_step(0, "LONG", 100, 95, 110)]),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
    )
    assert result.trades[0].exit_bar_index == 2
    assert result.trades[0].exit_reason == "TARGET"


def test_overlapping_entry_is_ignored_until_position_closes() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 104, 98, 102),
        candle(2, 102, 106, 99, 104),
        candle(3, 104, 111, 103, 110),
        candle(4, 110, 112, 108, 111),
    ]
    steps = [
        replay_step(0, "LONG", 100, 95, 110),
        replay_step(1, "LONG", 102, 96, 112),
    ]
    result = run_backtest(
        replay(steps),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
    )
    assert result.total_trades == 1
    assert result.ignored_overlapping_entries == 1


def test_short_trade_hits_target() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 102, 96, 97),
        candle(2, 97, 98, 89, 90),
    ]
    result = run_backtest(
        replay([replay_step(0, "SHORT", 100, 105, 90)]),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
    )
    trade = result.trades[0]
    assert trade.outcome == "WIN"
    assert trade.gross_r == 2.0


def test_fees_and_slippage_reduce_net_r_and_equity() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 111, 99, 110),
    ]
    no_cost = run_backtest(
        replay([replay_step(0, "LONG", 100, 95, 110)]),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
    )
    with_cost = run_backtest(
        replay([replay_step(0, "LONG", 100, 95, 110)]),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=10, slippage_bps_per_side=5),
    )
    assert with_cost.trades[0].net_r < no_cost.trades[0].net_r
    assert with_cost.final_equity < no_cost.final_equity


def test_end_of_data_marks_position_without_fabricated_win_or_loss() -> None:
    candles = [
        candle(0, 100, 101, 99, 100),
        candle(1, 100, 104, 98, 103),
    ]
    result = run_backtest(
        replay([replay_step(0, "LONG", 100, 95, 110)]),
        market(candles),
        initial_equity=10_000,
        config=BacktestConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
    )
    assert result.trades[0].outcome == "OPEN_END"
    assert result.trades[0].exit_reason == "END_OF_DATA"
    assert result.open_end == 1
    assert result.wins == 0 and result.losses == 0


def test_invalid_replay_or_symbol_is_rejected() -> None:
    bad = ReplayResult("OTHERUSDT", "1h", [], {}, None, None, ["REPLAY_ERROR"])
    result = run_backtest(bad, market([candle(0, 100, 101, 99, 100)]), initial_equity=10_000)
    assert "SYMBOL_MISMATCH" in result.errors
    assert "REPLAY_INVALID" in result.errors
    assert result.total_trades == 0
