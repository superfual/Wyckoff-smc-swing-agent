"""Run the real BTCUSDT Binance-MCP closed-candle snapshot through V1.

This is read-only analysis. It does not send exchange orders or mutate paper state.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import zlib

from src.confluence import analyze_confluence
from src.execution import ExecutionConfig, build_execution_intent
from src.history_sufficiency import evaluate_history_sufficiency
from src.market_data import Candle, MarketData
from src.orchestrator import AgentConfig, analyze_symbol
from src.risk import RiskConfig, evaluate_risk
from src.scanner import scan_market
from src.smc import analyze_smc
from src.thesis import build_trade_thesis
from src.wyckoff import analyze_wyckoff

FIXTURE = Path("tests/fixtures/btcusdt_spot_20260905_1800.json.zlib.b64")


def _load_snapshot() -> tuple[dict, MarketData]:
    raw = zlib.decompress(base64.b64decode(FIXTURE.read_text(encoding="utf-8"))).decode("utf-8")
    payload = json.loads(raw)

    def candles(tf: str) -> list[Candle]:
        return [Candle(int(ts), float(o), float(h), float(l), float(c), float(v)) for ts, o, h, l, c, v in payload["candles"][tf]]

    daily = candles("1D")
    four_hour = candles("4H")
    one_hour = candles("1H")
    fifteen_minute = candles("15M")
    # At the 18:00 UTC decision boundary, the 17:45 15M close and 17:00 1H
    # close both equal 80058.60. Use the latest closed 15M close as the
    # read-only reference price; no live ticker is fabricated.
    current_price = fifteen_minute[-1].close
    market = MarketData("BTCUSDT", current_price, daily, four_hour, one_hour, fifteen_minute)
    return payload, market


def main() -> None:
    payload, market = _load_snapshot()
    history = evaluate_history_sufficiency(market, smc_timeframe="1h")

    # Diagnostic deep run: compute every analytical layer even if the official
    # scanner gate would later choose SKIP. This lets us inspect the full real
    # snapshot while preserving orchestrator semantics for the final action.
    scan = scan_market(market, priority="HIGH")
    wyckoff = analyze_wyckoff(market)
    smc = analyze_smc(market, timeframe="1h")
    confluence = analyze_confluence(wyckoff, smc)
    thesis = build_trade_thesis(confluence, wyckoff, smc)
    risk = evaluate_risk(thesis, account_equity=10_000.0, current_portfolio_exposure_pct=0.0, config=RiskConfig(trading_mode="SPOT"))
    execution = build_execution_intent(thesis, risk, market.current_price or 0.0, config=ExecutionConfig(trading_mode="SPOT"))

    official = analyze_symbol(
        market,
        account_equity=10_000.0,
        current_portfolio_exposure_pct=0.0,
        config=AgentConfig(watchlist_priority="HIGH", trading_mode="SPOT"),
        risk_config=RiskConfig(trading_mode="SPOT"),
        execution_config=ExecutionConfig(trading_mode="SPOT"),
    )

    result = {
        "source": payload["source"],
        "symbol": market.symbol,
        "decision_time": payload["decision_time"],
        "closed_counts": {
            "1D": len(market.daily),
            "4H": len(market.four_hour),
            "1H": len(market.one_hour),
            "15M": len(market.fifteen_minute),
            "total": len(market.daily) + len(market.four_hour) + len(market.one_hour) + len(market.fifteen_minute),
        },
        "reference_price": market.current_price,
        "history": history.to_dict(),
        "diagnostic": {
            "scanner": scan.to_dict(),
            "wyckoff": wyckoff.to_dict(),
            "smc": {
                "bias": smc.bias,
                "trend_state": smc.trend_state,
                "swings": len(smc.swings),
                "events": [e.__dict__ for e in smc.events[-8:]],
                "liquidity_sweeps": [e.__dict__ for e in smc.liquidity_sweeps[-5:]],
                "active_fvgs": [e.__dict__ for e in smc.fair_value_gaps if e.status != "MITIGATED"][-5:],
                "active_order_blocks": [e.__dict__ for e in smc.order_blocks if e.status != "INVALIDATED"][-5:],
                "errors": smc.errors,
            },
            "confluence": confluence.to_dict(),
            "thesis": thesis.to_dict(),
            "risk": risk.to_dict(),
            "execution": execution.to_dict(),
        },
        "official_orchestrator": {
            "action": official.action,
            "reasons": official.reasons,
            "interpretation": official.interpretation,
            "errors": official.errors,
        },
    }
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
