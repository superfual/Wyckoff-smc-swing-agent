import json
from pathlib import Path

from src.history_sufficiency import evaluate_history_sufficiency
from src.market_data import build_market_data
from src.orchestrator import analyze_symbol
from src.scanner import scan_market

FIXTURE = Path(__file__).parent / "fixtures" / "btcusdt_real_20260905T180244Z.json"


def _load_real_btc_market():
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    tf = payload["timeframes"]
    market = build_market_data(
        payload["symbol"],
        tf["1H"][-1][4],
        tf["1D"],
        tf["4H"],
        tf["1H"],
        tf["15M"],
    )
    return payload, market


def test_real_btc_fixture_is_history_sufficient_for_v1():
    payload, market = _load_real_btc_market()
    history = evaluate_history_sufficiency(market)

    assert payload["source"] == "Binance MCP Server"
    assert payload["decision_time"] == 1788631364000
    assert history.ready is True
    assert history.blockers == ()
    assert len(market.daily) == 20
    assert len(market.four_hour) == 30
    assert len(market.one_hour) == 80
    assert len(market.fifteen_minute) == 16


def test_real_btc_scanner_regression_remains_watch_73():
    _, market = _load_real_btc_market()
    result = scan_market(market, priority="HIGH")

    assert result.classification == "WATCH"
    assert result.score == 73.0
    assert result.breakdown.trend == 25.0
    assert result.breakdown.structure == 17.0
    assert result.breakdown.volume == 10.0
    assert result.breakdown.compression == 15.0
    assert result.breakdown.range_location == 6.0


def test_real_btc_end_to_end_regression_stays_defensive():
    _, market = _load_real_btc_market()
    decision = analyze_symbol(market, account_equity=10_000.0)

    assert decision.scan.classification == "WATCH"
    assert decision.scan.score == 73.0
    assert decision.wyckoff is not None
    assert decision.wyckoff.bias == "NEUTRAL"
    assert decision.wyckoff.phase == "UNCONFIRMED"
    assert decision.wyckoff.trading_range is not None
    assert decision.wyckoff.trading_range.support == 76968.0
    assert decision.wyckoff.trading_range.resistance == 81288.0

    assert decision.smc is not None
    assert decision.smc.events
    assert decision.smc.events[-1].kind == "CHOCH"
    assert decision.smc.events[-1].direction == "BULLISH"

    assert decision.thesis is not None
    assert decision.thesis.state != "READY"
    assert decision.risk is not None
    assert decision.risk.decision == "NO_TRADE"
    assert decision.execution is not None
    assert decision.execution.allowed is False
    assert decision.action == "BLOCKED"
