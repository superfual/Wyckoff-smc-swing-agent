import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import paper_trading
from market_data import Candle, MarketData
from paper_trading import PaperPosition, PaperTradingConfig, create_paper_account, process_paper_snapshot


def _market(price=100.0, low=99.0, high=101.0):
    candles = [Candle(0, 100, high, low, price, 10)]
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


def test_enter_long_opens_virtual_position(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("ENTER_LONG", True, 100, 95, 110, 1000))
    account = create_paper_account()
    result = process_paper_snapshot(account, _market(), timestamp=1)
    assert result.account.open_position is not None
    assert result.account.open_position.direction == "LONG"
    assert any(event.kind == "OPEN" for event in result.events)


def test_short_signal_never_opens_spot_paper_position(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("ENTER_SHORT", True, 100, 105, 90, 1000))
    account = create_paper_account()
    result = process_paper_snapshot(account, _market(), timestamp=1)
    assert result.account.open_position is None
    assert not any(event.kind == "OPEN" for event in result.events)


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


def test_cooldown_prevents_immediate_reentry_after_exit(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("ENTER_LONG", True, 100, 95, 110, 1000))
    account = create_paper_account()
    account.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 95, 110, 1000, 10, 1)
    result = process_paper_snapshot(account, _market(price=111, low=100, high=112), timestamp=2)
    assert result.account.open_position is None
    assert result.account.cooldown_bars_remaining == 1
    assert any(event.kind == "CLOSE" for event in result.events)
    assert not any(event.kind == "OPEN" for event in result.events)
