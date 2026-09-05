from types import SimpleNamespace

import src.paper_trading as paper_trading
from src.market_data import Candle, MarketData
from src.paper_session import create_paper_session, process_session_snapshot
from src.paper_trading import PaperPosition, create_paper_account, process_paper_snapshot
from src.portfolio_safety import PortfolioSafetyConfig, set_kill_switch


def _market(symbol="BTCUSDT", price=100.0):
    candles = [Candle(0, 100, 101, 99, price, 10)]
    return MarketData(symbol, price, candles, candles, candles, candles)


def _enter_decision(symbol="BTCUSDT"):
    execution = SimpleNamespace(
        allowed=True,
        state="READY_TO_EXECUTE",
        action="ENTER_LONG",
        planned_entry=100.0,
        stop_price=95.0,
        target_price=110.0,
        position_size_quote=1000.0,
        position_size_units=10.0,
        blockers=[],
        interpretation="ready",
    )
    return SimpleNamespace(
        symbol=symbol,
        action="ENTER_LONG",
        execution=execution,
        reasons=[],
        interpretation="ready",
        errors=[],
    )


def test_external_portfolio_blocker_converts_entry_to_blocked(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _enter_decision())
    account = create_paper_account()

    result = process_paper_snapshot(
        account,
        _market(),
        timestamp=1,
        entry_blockers=["PORTFOLIO_KILL_SWITCH_ACTIVE"],
    )

    assert result.decision.action == "BLOCKED"
    assert result.decision.execution.allowed is False
    assert result.decision.execution.action == "BLOCKED"
    assert "PORTFOLIO_KILL_SWITCH_ACTIVE" in result.decision.execution.blockers
    assert account.open_position is None
    assert any(event.kind == "BLOCK" for event in result.events)


def test_session_max_positions_blocks_second_symbol(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda market, **k: _enter_decision(market.symbol))
    session = create_paper_session()
    btc = create_paper_account()
    btc.open_position = PaperPosition("BTCUSDT", "LONG", 0, 100, 95, 110, 1000, 10, 1)
    session.accounts["BTCUSDT"] = btc

    result = process_session_snapshot(
        session,
        _market("ETHUSDT"),
        timestamp=1,
        portfolio_safety_config=PortfolioSafetyConfig(max_concurrent_positions=1),
    )

    assert result.decision.action == "BLOCKED"
    assert "MAX_CONCURRENT_POSITIONS_REACHED" in result.decision.execution.blockers
    assert session.accounts["ETHUSDT"].open_position is None


def test_kill_switch_blocks_new_entry_but_does_not_force_close_existing_position(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda market, **k: _enter_decision(market.symbol))
    session = create_paper_session()
    btc = create_paper_account()
    btc.open_position = PaperPosition("BTCUSDT", "LONG", 0, 100, 90, 120, 1000, 10, 1)
    session.accounts["BTCUSDT"] = btc
    set_kill_switch(session.portfolio_safety, True)

    result = process_session_snapshot(session, _market("BTCUSDT", 101), timestamp=1)

    assert session.accounts["BTCUSDT"].open_position is not None
    assert not any(event.kind == "CLOSE" for event in result.events)
