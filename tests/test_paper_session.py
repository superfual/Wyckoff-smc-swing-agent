import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import paper_session
import paper_trading
from market_data import Candle, MarketData
from paper_session import create_paper_session, process_session_snapshot, summarize_paper_session
from paper_trading import PaperAccount, PaperEvent, PaperPosition, PaperStepResult, PaperTrade, PaperTradingConfig


def _market(symbol="BTCUSDT", price=100.0, low=99.0, high=101.0):
    candles = [Candle(0, 100, high, low, price, 10)]
    return MarketData(symbol, price, candles, candles, candles, candles)


def _decision(action="WAIT"):
    return SimpleNamespace(action=action, interpretation="test")


def test_create_session_uses_one_shared_equity():
    session = create_paper_session()
    assert session.equity == 10000
    assert session.unrealized_pnl == 0
    assert session.accounts == {}
    assert session.equity_curve[0].equity == 10000


def test_second_symbol_receives_exposure_from_first_open_position(monkeypatch):
    seen_exposure = []

    def fake_process(account, market, *, timestamp, current_portfolio_exposure_pct, **kwargs):
        seen_exposure.append(round(current_portfolio_exposure_pct, 4))
        if market.symbol == "BTCUSDT":
            account.open_position = PaperPosition("BTCUSDT", "LONG", timestamp, 100, 95, 110, 2000, 20, 2)
        return PaperStepResult(market.symbol, timestamp, _decision("ENTER_LONG"), account, [PaperEvent(timestamp, "DECISION", "ENTER_LONG", "test")], [])

    monkeypatch.setattr(paper_session, "process_paper_snapshot", fake_process)
    session = create_paper_session()
    process_session_snapshot(session, _market("BTCUSDT"), timestamp=1)
    process_session_snapshot(session, _market("ETHUSDT"), timestamp=1)

    assert seen_exposure == [0.0, 20.0]
    assert summarize_paper_session(session).exposure_pct == 20.0


def test_realized_pnl_updates_shared_equity_and_syncs_accounts(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("WAIT"))
    session = create_paper_session()
    btc = PaperAccount(10000, 10000)
    eth = PaperAccount(10000, 10000)
    btc.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 95, 110, 1000, 10, 0)
    session.accounts["BTCUSDT"] = btc
    session.accounts["ETHUSDT"] = eth

    process_session_snapshot(
        session,
        _market("BTCUSDT", price=111, low=100, high=112),
        timestamp=2,
        paper_config=PaperTradingConfig(fee_bps_per_side=0, slippage_bps_per_side=0),
    )

    assert session.realized_pnl == 100
    assert session.unrealized_pnl == 0
    assert session.equity == 10100
    assert session.accounts["BTCUSDT"].equity == 10100
    assert session.accounts["ETHUSDT"].equity == 10100


def test_unrealized_pnl_marks_shared_equity_and_drawdown(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("WAIT"))
    session = create_paper_session()
    btc = PaperAccount(10000, 10000)
    btc.open_position = PaperPosition("BTCUSDT", "LONG", 1, 100, 90, 120, 1000, 10, 0)
    session.accounts["BTCUSDT"] = btc
    cfg = PaperTradingConfig(fee_bps_per_side=0, slippage_bps_per_side=0)

    process_session_snapshot(session, _market("BTCUSDT", price=105, low=101, high=106), timestamp=2, paper_config=cfg)
    assert session.unrealized_pnl == 50
    assert session.equity == 10050

    process_session_snapshot(session, _market("BTCUSDT", price=98, low=97, high=104), timestamp=3, paper_config=cfg)
    summary = summarize_paper_session(session)
    assert session.unrealized_pnl == -20
    assert session.equity == 9980
    assert summary.unrealized_pnl == -20
    assert summary.return_pct == -0.2
    assert summary.max_drawdown_pct > 0


def test_duplicate_symbol_timestamp_is_not_double_counted(monkeypatch):
    monkeypatch.setattr(paper_trading, "analyze_symbol", lambda *a, **k: _decision("WAIT"))
    session = create_paper_session()
    first = process_session_snapshot(session, _market(), timestamp=5)
    second = process_session_snapshot(session, _market(), timestamp=5)

    assert first.errors == []
    assert second.errors == ["NON_MONOTONIC_TIMESTAMP"]
    assert session.decisions == 1
    assert len(session.journal) == 1


def test_summary_aggregates_trades_across_symbols():
    session = create_paper_session()
    btc = PaperAccount(10000, 10000)
    eth = PaperAccount(10000, 10000)
    btc.trades.append(PaperTrade("BTCUSDT", "LONG", 1, 2, 100, 110, 95, 110, 1000, 100, 0, 100, 2.0, "WIN", "TARGET"))
    eth.trades.append(PaperTrade("ETHUSDT", "LONG", 1, 2, 100, 95, 95, 110, 1000, -50, 0, -50, -1.0, "LOSS", "STOP"))
    session.accounts = {"BTCUSDT": btc, "ETHUSDT": eth}
    session.realized_pnl = 50
    session.equity = 10050

    summary = summarize_paper_session(session)
    assert summary.total_trades == 2
    assert summary.wins == 1
    assert summary.losses == 1
    assert summary.win_rate_pct == 50.0
    assert summary.expectancy_r == 0.5
    assert summary.realized_pnl == 50
