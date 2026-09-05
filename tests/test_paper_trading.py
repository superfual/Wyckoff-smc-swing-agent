import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import paper_trading
from market_data import Candle, MarketData
from paper_trading import PaperPosition, PaperTradingConfig, create_paper_account, process_paper_snapshot


def _market(price=100.0, low=99.0, high=101.0, open_price=100.0):
    candles = [Candle(0, open_price, high, low, price, 10)]
    return MarketData("BTCUSDT", price, candles, candles, candles, candles)


def _decision(action="WAIT", allowed=False, entry=None, stop=None, target=None, size=0.0):
    execution = SimpleNamespace(
        allowed=allowed,
        planned_entry=entry,
        stop_price=stop,
        target_price=target,
        position_size_quote=size,
    )
    return SimpleNamespace(action=action, execution=execution, interpretation="test decision")


def test_create_account_uses_virtual_equity():
    account = create_paper_account(PaperTradingConfig(initial_equity=5000))
    assert account.equity == 5000
    assert account.open_position is None
    assert account.pending_entry_price is None
    assert account.unrealized_pnl == 0


def test_enter_long_stages_pending_limit_not_same_candle_fill(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("ENTER_LONG", True, 100, 95, 110, 1000))
    account = create_paper_account()

    result = process_paper_snapshot(account, _market(price=100, low=90, high=110), timestamp=1)

    assert account.open_position is None
    assert account.pending_entry_price == 100
    assert any(event.kind == "ORDER" for event in result.events)
    assert not any(event.kind == "OPEN" for event in result.events)


def test_pending_limit_fills_only_on_later_closed_candle(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    account = create_paper_account()
    account.pending_entry_price = 100
    account.pending_stop_price = 95
    account.pending_target_price = 110
    account.pending_size_quote = 1000
    account.pending_created_timestamp = 1

    result = process_paper_snapshot(account, _market(price=102, low=99, high=103), timestamp=2, config=PaperTradingConfig(slippage_bps_per_side=0))

    assert account.open_position is not None
    assert account.open_position.entry_price == 100
    assert account.pending_entry_price is None
    assert any(event.kind == "OPEN" for event in result.events)


def test_gap_above_buy_limit_does_not_fill_and_order_expires(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    cfg = PaperTradingConfig(entry_order_ttl_bars=2)
    account = create_paper_account(cfg)
    account.pending_entry_price = 100
    account.pending_stop_price = 95
    account.pending_target_price = 110
    account.pending_size_quote = 1000
    account.pending_created_timestamp = 1

    first = process_paper_snapshot(account, _market(price=104, low=103, high=105, open_price=104), timestamp=2, config=cfg)
    assert account.open_position is None
    assert account.pending_entry_price == 100
    assert not any(event.kind == "MISS" for event in first.events)

    second = process_paper_snapshot(account, _market(price=106, low=105, high=107, open_price=106), timestamp=3, config=cfg)
    assert account.open_position is None
    assert account.pending_entry_price is None
    assert any(event.kind == "MISS" for event in second.events)


def test_gap_below_limit_uses_limit_price_conservatively(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    account = create_paper_account()
    account.pending_entry_price = 100
    account.pending_stop_price = 90
    account.pending_target_price = 120
    account.pending_size_quote = 1000
    account.pending_created_timestamp = 1

    process_paper_snapshot(account, _market(price=97, low=96, high=99, open_price=97), timestamp=2, config=PaperTradingConfig(slippage_bps_per_side=0))

    assert account.open_position is not None
    assert account.open_position.entry_price == 100
    assert account.unrealized_pnl == -30


def test_pending_fill_candle_stop_is_conservative(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    cfg = PaperTradingConfig(fee_bps_per_side=0, slippage_bps_per_side=0, conservative_entry_same_bar_stop=True)
    account = create_paper_account(cfg)
    account.pending_entry_price = 100
    account.pending_stop_price = 95
    account.pending_target_price = 110
    account.pending_size_quote = 1000
    account.pending_created_timestamp = 1

    result = process_paper_snapshot(account, _market(price=101, low=94, high=104), timestamp=2, config=cfg)

    assert account.open_position is None
    assert account.trades[-1].exit_reason == "STOP"
    assert any(event.kind == "OPEN" for event in result.events)
    assert any(event.kind == "CLOSE" for event in result.events)


def test_entry_fee_is_booked_when_pending_order_fills(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    account = create_paper_account()
    account.pending_entry_price = 100
    account.pending_stop_price = 95
    account.pending_target_price = 110
    account.pending_size_quote = 1000
    account.pending_created_timestamp = 1
    cfg = PaperTradingConfig(fee_bps_per_side=10, slippage_bps_per_side=0)

    process_paper_snapshot(account, _market(price=100, low=99, high=101), timestamp=2, config=cfg)

    assert account.open_position is not None
    assert account.open_position.entry_fee_quote == 1.0
    assert account.realized_pnl == -1.0
    assert account.unrealized_pnl == 0.0
    assert account.mark_price == 100
    assert account.equity == 9999.0


def test_open_position_marks_unrealized_pnl_on_each_closed_snapshot(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    account = create_paper_account(PaperTradingConfig(fee_bps_per_side=0, slippage_bps_per_side=0))
    account.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 90, 120, 1000, 10, 0)

    process_paper_snapshot(account, _market(price=105, low=101, high=106), timestamp=2, config=PaperTradingConfig(fee_bps_per_side=0, slippage_bps_per_side=0))
    assert account.unrealized_pnl == 50
    assert account.equity == 10050

    process_paper_snapshot(account, _market(price=98, low=97, high=104), timestamp=3, config=PaperTradingConfig(fee_bps_per_side=0, slippage_bps_per_side=0))
    assert account.unrealized_pnl == -20
    assert account.equity == 9980


def test_close_does_not_double_charge_entry_fee(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    cfg = PaperTradingConfig(fee_bps_per_side=10, slippage_bps_per_side=0)
    account = create_paper_account(cfg)
    account.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 95, 110, 1000, 10, 1)
    account.realized_pnl = -1
    account.equity = 9999

    process_paper_snapshot(account, _market(price=110, low=100, high=111), timestamp=2, config=cfg)

    trade = account.trades[-1]
    assert trade.gross_pnl_quote == 100
    assert trade.fees_quote == 2.1
    assert trade.net_pnl_quote == 97.9
    assert round(account.realized_pnl, 8) == 97.9
    assert round(account.equity, 8) == 10097.9
    assert account.unrealized_pnl == 0


def test_short_signal_never_opens_or_stages_spot_position(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("ENTER_SHORT", True, 100, 105, 90, 1000))
    account = create_paper_account()
    result = process_paper_snapshot(account, _market(), timestamp=1)
    assert result.account.open_position is None
    assert result.account.pending_entry_price is None
    assert not any(event.kind in {"ORDER", "OPEN"} for event in result.events)


def test_existing_position_closes_at_stop_before_new_decision(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    account = create_paper_account()
    account.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 95, 110, 1000, 10, 1)
    result = process_paper_snapshot(account, _market(price=96, low=94, high=100), timestamp=2)
    assert result.account.open_position is None
    assert result.account.trades[-1].exit_reason == "STOP"
    assert result.account.trades[-1].outcome == "LOSS"


def test_same_bar_stop_and_target_uses_stop_conservatively(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    account = create_paper_account()
    account.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 95, 110, 1000, 10, 1)
    process_paper_snapshot(account, _market(price=100, low=94, high=111), timestamp=2)
    assert account.trades[-1].exit_reason == "STOP"


def test_duplicate_or_older_timestamp_is_rejected(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision())
    account = create_paper_account()
    process_paper_snapshot(account, _market(), timestamp=5)
    result = process_paper_snapshot(account, _market(), timestamp=5)
    assert result.errors == ["NON_MONOTONIC_TIMESTAMP"]


def test_cooldown_prevents_immediate_new_order_after_exit(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("ENTER_LONG", True, 100, 95, 110, 1000))
    account = create_paper_account()
    account.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 95, 110, 1000, 10, 1)
    result = process_paper_snapshot(account, _market(price=111, low=100, high=112), timestamp=2)
    assert result.account.open_position is None
    assert result.account.pending_entry_price is None
    assert result.account.cooldown_bars_remaining == 1
    assert any(event.kind == "CLOSE" for event in result.events)
    assert not any(event.kind == "ORDER" for event in result.events)
