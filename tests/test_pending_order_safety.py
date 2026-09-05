import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import paper_trading
from market_data import Candle, MarketData
from paper_trading import PaperTradingConfig, create_paper_account, process_paper_snapshot


def _market(symbol="BTCUSDT", price=100.0, low=99.0, high=101.0):
    candles = [Candle(0, 100.0, high, low, price, 10.0)]
    return MarketData(symbol, price, candles, candles, candles, candles)


def _wait_decision():
    return SimpleNamespace(action="WAIT", execution=None, interpretation="wait")


def _pending_account():
    account = create_paper_account()
    account.pending_entry_price = 100.0
    account.pending_stop_price = 95.0
    account.pending_target_price = 110.0
    account.pending_size_quote = 1000.0
    account.pending_created_timestamp = 1
    return account


def test_pending_order_is_cancelled_before_touch_when_kill_switch_activates(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _wait_decision())
    account = _pending_account()

    result = process_paper_snapshot(
        account,
        _market(price=104, low=103, high=105),
        timestamp=2,
        entry_blockers=("PORTFOLIO_KILL_SWITCH_ACTIVE",),
    )

    assert account.pending_entry_price is None
    assert account.open_position is None
    assert any(event.kind == "CANCEL" and event.action == "ENTRY_CANCELLED_SAFETY" for event in result.events)
    assert "PORTFOLIO_KILL_SWITCH_ACTIVE" in next(event.note for event in result.events if event.kind == "CANCEL")


def test_pending_order_cannot_fill_on_same_candle_that_safety_blocks(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _wait_decision())
    account = _pending_account()

    result = process_paper_snapshot(
        account,
        _market(price=101, low=99, high=103),
        timestamp=2,
        config=PaperTradingConfig(slippage_bps_per_side=0),
        entry_blockers=("DAILY_LOSS_LIMIT_REACHED",),
    )

    assert account.pending_entry_price is None
    assert account.open_position is None
    assert not any(event.kind == "OPEN" for event in result.events)
    assert any(event.kind == "CANCEL" for event in result.events)


def test_multiple_blockers_are_deduplicated_in_cancel_note(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _wait_decision())
    account = _pending_account()

    result = process_paper_snapshot(
        account,
        _market(price=104, low=103, high=105),
        timestamp=2,
        entry_blockers=(
            "MAX_CONCURRENT_POSITIONS_REACHED",
            "MAX_CONCURRENT_POSITIONS_REACHED",
            "CORRELATION_GROUP_LIMIT_REACHED:CRYPTO_BETA",
        ),
    )

    note = next(event.note for event in result.events if event.kind == "CANCEL")
    assert note.count("MAX_CONCURRENT_POSITIONS_REACHED") == 1
    assert "CORRELATION_GROUP_LIMIT_REACHED:CRYPTO_BETA" in note


def test_pending_order_still_fills_when_revalidation_has_no_blockers(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _wait_decision())
    account = _pending_account()

    result = process_paper_snapshot(
        account,
        _market(price=101, low=99, high=103),
        timestamp=2,
        config=PaperTradingConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
        entry_blockers=(),
    )

    assert account.open_position is not None
    assert account.open_position.entry_price == 100.0
    assert any(event.kind == "OPEN" for event in result.events)
    assert not any(event.kind == "CANCEL" for event in result.events)
