"""Unit tests for the bar-by-bar replay engine."""

from copy import deepcopy

from src.market_data import Candle, MarketData
from src.replay import ReplayConfig, run_replay, slice_market_at_decision_time


def candle(timestamp: int, close: float) -> Candle:
    return Candle(
        timestamp=timestamp,
        open=close,
        high=close + 1,
        low=close - 1,
        close=close,
        volume=1_000.0,
    )


def make_market() -> MarketData:
    hour = 3_600_000
    quarter = 900_000
    day = 86_400_000
    four = 14_400_000
    return MarketData(
        symbol="TESTUSDT",
        current_price=150.0,
        daily=[candle(0, 100.0), candle(day, 101.0)],
        four_hour=[candle(i * four, 100.0 + i) for i in range(8)],
        one_hour=[candle(i * hour, 100.0 + i) for i in range(12)],
        fifteen_minute=[candle(i * quarter, 100.0 + i * 0.1) for i in range(48)],
    )


def test_snapshot_uses_only_fully_closed_higher_timeframe_candles() -> None:
    market = make_market()
    # Decision at the close of the third 1H candle = hour 3.
    decision_time = 3 * 3_600_000
    snapshot = slice_market_at_decision_time(market, decision_time, reference_timeframe="1h")

    assert len(snapshot.one_hour) == 3
    assert snapshot.current_price == market.one_hour[2].close
    # The first 4H candle opened at t=0 but has not closed by hour 3.
    assert snapshot.four_hour == []


def test_snapshot_includes_higher_timeframe_only_after_its_close() -> None:
    market = make_market()
    decision_time = 4 * 3_600_000
    snapshot = slice_market_at_decision_time(market, decision_time, reference_timeframe="1h")
    assert len(snapshot.four_hour) == 1
    assert snapshot.four_hour[0].timestamp == 0


def test_replay_runs_one_decision_per_reference_bar_after_warmup() -> None:
    market = make_market()
    result = run_replay(
        market,
        account_equity=10_000,
        config=ReplayConfig(reference_timeframe="1h", warmup_bars=5),
    )

    assert result.errors == []
    assert len(result.steps) == 8
    assert sum(result.action_counts.values()) == len(result.steps)
    assert result.first_decision_time == market.one_hour[4].timestamp + 3_600_000
    assert result.last_decision_time == market.one_hour[-1].timestamp + 3_600_000
    assert [step.decision_time for step in result.steps] == sorted(step.decision_time for step in result.steps)


def test_replay_never_uses_future_reference_price() -> None:
    market = make_market()
    result = run_replay(
        market,
        account_equity=10_000,
        config=ReplayConfig(reference_timeframe="1h", warmup_bars=3),
    )

    for step in result.steps:
        expected = market.one_hour[step.bar_index].close
        assert step.current_price == expected
        assert step.decision.scan.symbol == market.symbol


def test_replay_rejects_insufficient_history() -> None:
    market = make_market()
    result = run_replay(
        market,
        account_equity=10_000,
        config=ReplayConfig(reference_timeframe="1h", warmup_bars=20),
    )
    assert result.steps == []
    assert "INSUFFICIENT_REPLAY_BARS" in result.errors


def test_replay_rejects_invalid_account_equity() -> None:
    result = run_replay(make_market(), account_equity=0)
    assert result.steps == []
    assert "INVALID_ACCOUNT_EQUITY" in result.errors


def test_as_of_time_excludes_reference_candle_that_has_not_closed() -> None:
    market = make_market()
    hour = 3_600_000
    # The candle opening at hour 11 closes at hour 12, so it is unavailable
    # when the historical decision cutoff is hour 11.
    result = run_replay(
        market,
        account_equity=10_000,
        config=ReplayConfig(reference_timeframe="1h", warmup_bars=5, as_of_time=11 * hour),
    )

    assert result.errors == []
    assert result.no_lookahead_verified is True
    assert result.excluded_reference_bars == 1
    assert result.last_decision_time == 11 * hour
    assert all(step.decision_time <= result.as_of_time for step in result.steps)


def test_every_replay_step_carries_auditable_closed_candle_counts() -> None:
    result = run_replay(
        make_market(),
        account_equity=10_000,
        config=ReplayConfig(reference_timeframe="1h", warmup_bars=5),
    )

    assert result.no_lookahead_verified is True
    assert result.audit_errors == []
    for step in result.steps:
        assert set(step.snapshot_candle_counts) == {"1d", "4h", "1h", "15m"}
        assert step.snapshot_candle_counts["1h"] == step.bar_index + 1
        assert all(
            close_time is None or close_time <= step.decision_time
            for close_time in step.latest_closed_times.values()
        )


def test_future_data_append_cannot_change_past_replay_decisions() -> None:
    market = make_market()
    augmented = deepcopy(market)
    hour = 3_600_000
    cutoff = 12 * hour
    augmented.one_hour.append(candle(12 * hour, 9_999.0))
    augmented.fifteen_minute.append(candle(48 * 900_000, 9_999.0))
    augmented.four_hour.append(candle(8 * 14_400_000, 9_999.0))
    augmented.daily.append(candle(2 * 86_400_000, 9_999.0))

    cfg = ReplayConfig(reference_timeframe="1h", warmup_bars=5, as_of_time=cutoff)
    baseline = run_replay(market, account_equity=10_000, config=cfg)
    with_future = run_replay(augmented, account_equity=10_000, config=cfg)

    assert baseline.errors == [] and with_future.errors == []
    assert [step.to_dict() for step in with_future.steps] == [step.to_dict() for step in baseline.steps]
    assert with_future.excluded_reference_bars == baseline.excluded_reference_bars + 1


def test_replay_fails_closed_on_duplicate_candle_timestamp() -> None:
    market = make_market()
    market.one_hour[5].timestamp = market.one_hour[4].timestamp

    result = run_replay(
        market,
        account_equity=10_000,
        config=ReplayConfig(reference_timeframe="1h", warmup_bars=5),
    )

    assert result.steps == []
    assert "NON_MONOTONIC_CANDLES:1h" in result.errors
    assert result.no_lookahead_verified is False
