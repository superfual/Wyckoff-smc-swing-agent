"""Read-only USD-M snapshot -> existing Wyckoff/SMC orchestrator.

This script never places orders. A signal candidate is not an instruction
to auto-execute. Any data validation failure produces DATA_UNAVAILABLE.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from src.binance_public_futures import FuturesDataError, collect_futures_market
from src.futures_chart import render_chart
from src.execution import ExecutionConfig
from src.history_sufficiency import evaluate_history_sufficiency
from src.orchestrator import AgentConfig, analyze_symbol
from src.risk import RiskConfig


def run(symbol: str, *, timeframe: str = "H4", mode: str = "deep", chart_output: str | None = None, captured_at_ms: int | None = None) -> dict:
    timeframe = timeframe.upper().strip()
    if timeframe not in ("D1", "H4", "H1", "M15"):
        raise ValueError("Unsupported timeframe: use D1, H4, H1, M15")
    if mode not in ("deep", "scanner"):
        raise ValueError("Unsupported mode: use deep or scanner")
    captured_at_ms = int(time.time() * 1000) if captured_at_ms is None else captured_at_ms
    report = {
        "symbol": symbol.upper().strip(),
        "analysis_timeframe": timeframe,
        "analysis_mode": mode,
        "source": "BINANCE_USDM_FUTURES_PUBLIC_API",
        "captured_at_ms": captured_at_ms,
        "status": "DATA_UNAVAILABLE",
        "action": "NO_CLEAR_EDGE",
        "execution": "READ_ONLY_NO_ORDERS",
    }
    try:
        market = collect_futures_market(symbol, now_ms=captured_at_ms)
        history = evaluate_history_sufficiency(market, smc_timeframe={"D1":"1d","H4":"4h","H1":"1h","M15":"15m"}[timeframe])
        report["closed_candles"] = {
            "1D": len(market.daily), "4H": len(market.four_hour),
            "1H": len(market.one_hour), "15M": len(market.fifteen_minute),
        }
        report["last_closed_open_ms"] = {
            "1D": market.daily[-1].timestamp, "4H": market.four_hour[-1].timestamp,
            "1H": market.one_hour[-1].timestamp, "15M": market.fifteen_minute[-1].timestamp,
        }
        report["reference_price"] = market.current_price
        report["reference_type"] = "LAST_CLOSED_15M_CLOSE"
        if chart_output:
            render_chart(market, timeframe, chart_output, status="ANALYSIS PENDING")
            report["chart_path"] = str(chart_output)
        if not history.ready:
            report["errors"] = list(history.blockers)
            return report
        decision = analyze_symbol(
            market,
            account_equity=10_000.0,  # Scenario NAV only, not user's real balance.
            config=AgentConfig(trading_mode="FUTURES", watchlist_priority="HIGH",
                               smc_timeframe={"D1":"1d","H4":"4h","H1":"1h","M15":"15m"}[timeframe],
                               scanner_min_classification="LOW_INTEREST" if mode == "deep" else "WATCH"),
            risk_config=RiskConfig(trading_mode="FUTURES", risk_per_trade_pct=0.5),
            execution_config=ExecutionConfig(trading_mode="FUTURES"),
        )
        report["agent_action"] = decision.action
        report["status"] = "SIGNAL_CANDIDATE" if decision.action in ("ENTER_LONG", "ENTER_SHORT") and not decision.errors else "NO_CLEAR_EDGE"
        report["action"] = decision.action if report["status"] == "SIGNAL_CANDIDATE" else "NO_CLEAR_EDGE"
        report["reasons"] = decision.reasons
        report["errors"] = decision.errors
        report["scanner"] = decision.scan.to_dict()
        report["wyckoff"] = decision.wyckoff.to_dict() if decision.wyckoff else None
        report["smc"] = {
            "bias": decision.smc.bias,
            "trend_state": decision.smc.trend_state,
            "errors": decision.smc.errors,
        } if decision.smc else None
        report["confluence"] = decision.confluence.to_dict() if decision.confluence else None
        report["thesis"] = decision.thesis.to_dict() if decision.thesis else None
        report["risk"] = decision.risk.to_dict() if decision.risk else None
        report["execution_intent"] = decision.execution.to_dict() if decision.execution else None
        if chart_output:
            render_chart(market, timeframe, chart_output, status=report["status"])
    except (FuturesDataError, ValueError, KeyError, TypeError, IndexError) as exc:
        report["errors"] = [str(exc)]
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only public USD-M Wyckoff-SMC snapshot")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--timeframe", default="H4", choices=["D1","H4","H1","M15"])
    parser.add_argument("--mode", default="deep", choices=["deep","scanner"])
    parser.add_argument("--output", default="reports/public_futures_signal.json")
    parser.add_argument("--chart-output", default=None)
    args = parser.parse_args()
    result = run(args.symbol, timeframe=args.timeframe, mode=args.mode, chart_output=args.chart_output)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False))
    return 1 if result["status"] == "DATA_UNAVAILABLE" else 0


if __name__ == "__main__":
    sys.exit(main())
