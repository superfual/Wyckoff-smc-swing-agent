from types import SimpleNamespace

import pytest

from src.market_data import Candle, MarketData
from src.orchestrator import AgentConfig
from src.scanner import ScanResult, ScoreBreakdown, WatchlistSymbol
from src.watchlist_validation import validate_watchlist_batch


HOUR = 3_600_000
DAY = 86_400_000
DECISION_TIME = 100 * DAY


def _series(step: int, count: int, end_time: int, close: float) -> list[Candle]:
    start = end_time - step * count
    return [Candle(start + i * step, close, close + 1, close - 1, close, 10.0) for i in range(count)]


def _market(symbol: str, close: float = 100.0, include_open: bool = False) -> MarketData:
    market = MarketData(
        symbol=symbol,
        current_price=None,
        daily=_series(DAY, 20, DECISION_TIME, close),
        four_hour=_series(4 * HOUR, 30, DECISION_TIME, close),
        one_hour=_series(HOUR, 40, DECISION_TIME, close),
        fifteen_minute=_series(15 * 60_000, 8, DECISION_TIME, close),
    )
    if include_open:
        for candles in (market.daily, market.four_hour, market.one_hour, market.fifteen_minute):
            candles.append(Candle(DECISION_TIME, close, close + 1, close - 1, close, 10.0))
    return market


def _scan(symbol: str, score: float, classification: str, priority: str) -> ScanResult:
    return ScanResult(
        symbol=symbol,
        score=score,
        classification=classification,
        priority=priority,
        signals=[],
        breakdown=ScoreBreakdown(score, 0, 0, 0, 0),
        errors=[],
    )


def test_complete_batch_ranks_all_symbols_and_deep_analyzes_only_candidates(monkeypatch) -> None:
    scores = {
        "BTCUSDT": (80.0, "HIGH_INTEREST"),
        "ETHUSDT": (35.0, "LOW_INTEREST"),
    }

    def fake_scan(market, priority="MEDIUM"):
        score, classification = scores[market.symbol]
        return _scan(market.symbol, score, classification, priority)

    monkeypatch.setattr("src.watchlist_validation.scan_market", fake_scan)
    monkeypatch.setattr(
        "src.watchlist_validation.analyze_symbol",
        lambda market, **kwargs: SimpleNamespace(action="BLOCKED", errors=[]),
    )

    result = validate_watchlist_batch(
        [_market("ETHUSDT"), _market("BTCUSDT", include_open=True)],
        [WatchlistSymbol("BTCUSDT", "HIGH"), WatchlistSymbol("ETHUSDT", "MEDIUM")],
        decision_time=DECISION_TIME,
        observed_prices={"BTCUSDT": 100.5, "ETHUSDT": 99.5},
    )

    assert result.ready is True
    assert result.paper_only is True
    assert result.ranked_symbols == ["BTCUSDT", "ETHUSDT"]
    assert result.deep_analysis_symbols == ["BTCUSDT"]
    assert [item.symbol for item in result.symbols] == ["BTCUSDT", "ETHUSDT"]
    assert result.symbols[0].status == "BLOCKED"
    assert result.symbols[1].status == "SCANNED_ONLY"
    assert dict(result.symbols[0].feed.open_candle_counts) == {"1d": 1, "4h": 1, "1h": 1, "15m": 1}


def test_missing_observed_price_fails_closed_before_scanning(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.watchlist_validation.scan_market",
        lambda *args, **kwargs: pytest.fail("invalid feed must not be scanned"),
    )
    result = validate_watchlist_batch(
        [_market("BTCUSDT")],
        [WatchlistSymbol("BTCUSDT", "HIGH")],
        decision_time=DECISION_TIME,
        observed_prices={},
    )

    assert result.ready is False
    assert result.symbols[0].status == "INVALID_FEED"
    assert "BTCUSDT:MISSING_OR_INVALID_OBSERVED_PRICE" in result.blockers


def test_batch_rejects_missing_unexpected_and_duplicate_provider_symbols() -> None:
    result = validate_watchlist_batch(
        [_market("BTCUSDT"), _market("BTCUSDT"), _market("XRPUSDT")],
        [WatchlistSymbol("BTCUSDT", "HIGH"), WatchlistSymbol("ETHUSDT", "HIGH")],
        decision_time=DECISION_TIME,
        observed_prices={"BTCUSDT": 100.0, "ETHUSDT": 100.0},
    )

    assert result.ready is False
    assert "DUPLICATE_PROVIDER_SYMBOLS:BTCUSDT" in result.blockers
    assert "MISSING_PROVIDER_SYMBOLS:ETHUSDT" in result.blockers
    assert "UNEXPECTED_PROVIDER_SYMBOLS:XRPUSDT" in result.blockers


def test_spot_batch_blocks_any_impossible_short_execution(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.watchlist_validation.scan_market",
        lambda market, priority="MEDIUM": _scan(market.symbol, 90.0, "HIGH_INTEREST", priority),
    )
    monkeypatch.setattr(
        "src.watchlist_validation.analyze_symbol",
        lambda market, **kwargs: SimpleNamespace(action="ENTER_SHORT", errors=[]),
    )
    result = validate_watchlist_batch(
        [_market("BTCUSDT")],
        [WatchlistSymbol("BTCUSDT", "HIGH")],
        decision_time=DECISION_TIME,
        observed_prices={"BTCUSDT": 100.0},
    )

    assert result.ready is False
    assert result.symbols[0].status == "BLOCKED"
    assert "BTCUSDT:SPOT_SHORT_INVARIANT_BREACH" in result.blockers


def test_batch_api_rejects_futures_configuration() -> None:
    with pytest.raises(ValueError, match="SPOT only"):
        validate_watchlist_batch(
            [_market("BTCUSDT")],
            [WatchlistSymbol("BTCUSDT", "HIGH")],
            decision_time=DECISION_TIME,
            observed_prices={"BTCUSDT": 100.0},
            agent_config=AgentConfig(trading_mode="FUTURES"),
        )


def test_batch_fails_closed_on_duplicate_candle_timestamp() -> None:
    market = _market("BTCUSDT")
    market.one_hour[10].timestamp = market.one_hour[9].timestamp

    result = validate_watchlist_batch(
        [market],
        [WatchlistSymbol("BTCUSDT", "HIGH")],
        decision_time=DECISION_TIME,
        observed_prices={"BTCUSDT": 100.0},
    )

    assert result.ready is False
    assert "BTCUSDT:NON_MONOTONIC_CANDLES:1h" in result.blockers


def test_batch_fails_closed_on_future_candle_timestamp() -> None:
    market = _market("BTCUSDT")
    market.fifteen_minute.append(
        Candle(DECISION_TIME + 900_000, 100, 101, 99, 100, 10)
    )

    result = validate_watchlist_batch(
        [market],
        [WatchlistSymbol("BTCUSDT", "HIGH")],
        decision_time=DECISION_TIME,
        observed_prices={"BTCUSDT": 100.0},
    )

    assert result.ready is False
    assert "BTCUSDT:FUTURE_CANDLE_TIMESTAMP:15m" in result.blockers


def test_batch_fails_closed_on_stale_reference_candle() -> None:
    market = _market("BTCUSDT")
    market.one_hour.pop()

    result = validate_watchlist_batch(
        [market],
        [WatchlistSymbol("BTCUSDT", "HIGH")],
        decision_time=DECISION_TIME,
        observed_prices={"BTCUSDT": 100.0},
    )

    assert result.ready is False
    assert "BTCUSDT:REFERENCE_CANDLE_NOT_FRESH" in result.blockers


def test_deep_analysis_errors_block_batch_readiness(monkeypatch) -> None:
    monkeypatch.setattr(
        "src.watchlist_validation.scan_market",
        lambda market, priority="MEDIUM": _scan(market.symbol, 90.0, "HIGH_INTEREST", priority),
    )
    monkeypatch.setattr(
        "src.watchlist_validation.analyze_symbol",
        lambda market, **kwargs: SimpleNamespace(action="BLOCKED", errors=["BROKEN_ANALYSIS"]),
    )
    result = validate_watchlist_batch(
        [_market("BTCUSDT")],
        [WatchlistSymbol("BTCUSDT", "HIGH")],
        decision_time=DECISION_TIME,
        observed_prices={"BTCUSDT": 100.0},
    )

    assert result.ready is False
    assert "BTCUSDT:DEEP_ANALYSIS_ERROR:BROKEN_ANALYSIS" in result.blockers
