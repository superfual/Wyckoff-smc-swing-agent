"""Run the captured BTCUSDT Binance MCP snapshot through the real agent pipeline.

This is a deterministic regression harness. It never authenticates to Binance
and never places an exchange order.
"""
from __future__ import annotations

import base64
import json
from pathlib import Path
import sys
import zlib

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.history_sufficiency import evaluate_history_sufficiency
from src.market_data import Candle, MarketData
from src.orchestrator import AgentConfig, analyze_symbol

FIXTURE_DIR = ROOT / "tests" / "fixtures"
FIXTURE = FIXTURE_DIR / "btcusdt_spot_20260905_1800.json.zlib.b64"
FIXTURE_PART_GLOB = "btcusdt_spot_20260905_1800.part*"
DECISION_TIME = 1_788_631_364_000  # 2026-09-05 18:02:44 UTC
DURATION_MS = {"1D": 86_400_000, "4H": 14_400_000, "1H": 3_600_000, "15M": 900_000}
EXPECTED_CLOSED = {"1D": 119, "4H": 239, "1H": 299, "15M": 298}


def _decode_fixture() -> dict:
    parts = sorted(FIXTURE_DIR.glob(FIXTURE_PART_GLOB), key=lambda p: int(p.suffix.removeprefix(".part")))
    if parts:
        encoded = "".join(part.read_text(encoding="utf-8").strip() for part in parts)
    else:
        encoded = FIXTURE.read_text(encoding="utf-8").strip()
    packed = base64.b64decode(encoded)
    return json.loads(zlib.decompress(packed).decode("utf-8"))


def _row_to_candle(row) -> Candle:
    if isinstance(row, dict):
        ts = row.get("timestamp", row.get("open_time", row.get("open_time_ms")))
        return Candle(
            int(ts),
            float(row["open"]),
            float(row["high"]),
            float(row["low"]),
            float(row["close"]),
            float(row["volume"]),
        )
    if len(row) < 6:
        raise ValueError("Fixture candle must contain timestamp + OHLCV")
    return Candle(int(row[0]), float(row[1]), float(row[2]), float(row[3]), float(row[4]), float(row[5]))


def _timeframes(payload: dict) -> dict:
    source = payload.get("timeframes", payload)
    aliases = {
        "1D": ("1D", "1d", "daily"),
        "4H": ("4H", "4h", "four_hour"),
        "1H": ("1H", "1h", "one_hour"),
        "15M": ("15M", "15m", "fifteen_minute"),
    }
    result = {}
    for tf, candidates in aliases.items():
        rows = None
        for key in candidates:
            if key in source:
                rows = source[key]
                break
        if rows is None:
            raise KeyError(f"Fixture missing timeframe {tf}")
        result[tf] = rows
    return result


def build_closed_market() -> MarketData:
    payload = _decode_fixture()
    raw = _timeframes(payload)
    closed = {}
    for tf, rows in raw.items():
        candles = [_row_to_candle(row) for row in rows]
        candles = [c for c in candles if c.timestamp + DURATION_MS[tf] <= DECISION_TIME]
        closed[tf] = candles

    counts = {tf: len(rows) for tf, rows in closed.items()}
    if counts != EXPECTED_CLOSED:
        raise AssertionError(f"Closed-candle counts mismatch: expected={EXPECTED_CLOSED}, actual={counts}")

    for tf, candles in closed.items():
        timestamps = [c.timestamp for c in candles]
        if timestamps != sorted(timestamps) or len(timestamps) != len(set(timestamps)):
            raise AssertionError(f"Timestamp ordering/uniqueness failed for {tf}")
        if any(c.timestamp + DURATION_MS[tf] > DECISION_TIME for c in candles):
            raise AssertionError(f"Unclosed/future candle leaked into {tf}")

    reference_price = closed["15M"][-1].close
    return MarketData(
        symbol="BTCUSDT",
        current_price=reference_price,
        daily=closed["1D"],
        four_hour=closed["4H"],
        one_hour=closed["1H"],
        fifteen_minute=closed["15M"],
    )


def _summary(decision) -> dict:
    return {
        "action": decision.action,
        "scan": {
            "classification": decision.scan.classification,
            "score": decision.scan.score,
            "signals": decision.scan.signals,
            "breakdown": decision.scan.breakdown.__dict__,
        },
        "wyckoff": None if decision.wyckoff is None else {
            "bias": decision.wyckoff.bias,
            "phase": decision.wyckoff.phase,
            "confidence": decision.wyckoff.confidence,
            "range": None if decision.wyckoff.trading_range is None else decision.wyckoff.trading_range.__dict__,
            "events": [e.code for e in decision.wyckoff.events],
        },
        "smc": None if decision.smc is None else {
            "bias": decision.smc.bias,
            "trend_state": decision.smc.trend_state,
            "swings": len(decision.smc.swings),
            "events": [f"{e.kind}:{e.direction}" for e in decision.smc.events[-8:]],
            "liquidity_pools": len(decision.smc.liquidity_pools),
            "liquidity_sweeps": len(decision.smc.liquidity_sweeps),
            "fair_value_gaps": len(decision.smc.fair_value_gaps),
            "order_blocks": len(decision.smc.order_blocks),
        },
        "confluence": None if decision.confluence is None else {
            "bias": decision.confluence.bias,
            "classification": decision.confluence.classification,
            "bullish_score": decision.confluence.bullish_score,
            "bearish_score": decision.confluence.bearish_score,
            "confidence": decision.confluence.confidence,
            "agreement_score": decision.confluence.agreement_score,
            "contradictions": decision.confluence.contradictions,
        },
        "thesis": None if decision.thesis is None else {
            "state": decision.thesis.state,
            "direction": decision.thesis.direction,
            "confidence": decision.thesis.confidence,
            "entry_zone": None if decision.thesis.entry_zone is None else decision.thesis.entry_zone.__dict__,
            "invalidation": decision.thesis.invalidation_level,
            "target": decision.thesis.target_level,
            "blockers": decision.thesis.blockers,
        },
        "risk": None if decision.risk is None else {
            "decision": decision.risk.decision,
            "entry": decision.risk.entry_price,
            "stop": decision.risk.stop_price,
            "target": decision.risk.target_price,
            "reward_risk": decision.risk.reward_risk,
            "position_size_quote": decision.risk.position_size_quote,
            "reasons": decision.risk.reasons,
        },
        "execution": None if decision.execution is None else {
            "state": decision.execution.state,
            "action": decision.execution.action,
            "allowed": decision.execution.allowed,
            "blockers": decision.execution.blockers,
            "notes": decision.execution.notes,
        },
        "errors": decision.errors,
        "reasons": decision.reasons,
    }


def main() -> None:
    market = build_closed_market()
    history = evaluate_history_sufficiency(market, smc_timeframe="1h")
    if not history.ready:
        raise AssertionError(f"History sufficiency blocked: {history.blockers}")

    production = analyze_symbol(
        market,
        account_equity=10_000.0,
        current_portfolio_exposure_pct=0.0,
        config=AgentConfig(trading_mode="SPOT"),
    )
    diagnostic = analyze_symbol(
        market,
        account_equity=10_000.0,
        current_portfolio_exposure_pct=0.0,
        config=AgentConfig(scanner_min_classification="LOW_INTEREST", trading_mode="SPOT"),
    )

    if diagnostic.wyckoff is None or diagnostic.smc is None or diagnostic.confluence is None:
        raise AssertionError("Diagnostic run did not traverse the full analytical pipeline")
    if diagnostic.errors:
        raise AssertionError(f"Diagnostic pipeline errors: {diagnostic.errors}")
    if diagnostic.action not in {"ENTER_LONG", "AVOID_BUY", "WAIT", "BLOCKED"}:
        raise AssertionError(f"Unexpected SPOT diagnostic action: {diagnostic.action}")

    report = {
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "decision_time_utc": "2026-09-05T18:02:44Z",
        "closed_counts": EXPECTED_CLOSED,
        "reference_price_from_last_closed_15m": market.current_price,
        "history_ready": history.ready,
        "history_warnings": list(history.warnings),
        "production_default_gate": _summary(production),
        "diagnostic_full_pipeline": _summary(diagnostic),
        "note": "Synthetic 10,000 USDT equity is used only for deterministic risk-sizing validation; no exchange order is sent.",
    }
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
