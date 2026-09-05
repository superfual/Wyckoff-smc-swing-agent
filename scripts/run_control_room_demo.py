"""Run the Binance Spot PAPER-ONLY control-room pipeline.

Offline mode is deterministic and network-free. Live mode accepts an injected
``module:function`` MCP callback supplied by the host environment. This script
contains no credentials, account methods, or exchange-order methods.
"""
from __future__ import annotations

import argparse
from contextlib import nullcontext
from dataclasses import replace
from datetime import datetime, timezone
import importlib
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.binance_paper_host import (
    create_live_binance_paper_host,
    live_binance_paper_host_config,
    render_binance_control_room_output,
    run_binance_control_room_cycle,
)
from src.paper_runtime import PaperRuntimeConfig


HOUR_MS = 3_600_000
DAY_MS = 86_400_000
OFFLINE_CAPTURED_AT = 1_788_642_000_000  # 2026-09-05 21:00:00 UTC
DEFAULT_SYMBOLS = ("BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT")


class OfflineBinanceMCP:
    """Deterministic read-only MCP callback for demos and CI."""

    _BASE = {
        "BTCUSDT": 80_000.0, "ETHUSDT": 2_450.0, "BNBUSDT": 820.0, "SOLUSDT": 185.0,
        "XRPUSDT": 2.1, "DOGEUSDT": 0.19, "ADAUSDT": 0.72, "LINKUSDT": 24.0,
        "AVAXUSDT": 34.0, "SUIUSDT": 3.2, "UNIUSDT": 9.5, "AAVEUSDT": 310.0,
    }
    _SLOPE = {
        symbol: (-0.0007 if symbol == "ETHUSDT" else 0.0001 + index * 0.0001)
        for index, symbol in enumerate((
            "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
            "ADAUSDT", "LINKUSDT", "AVAXUSDT", "SUIUSDT", "UNIUSDT", "AAVEUSDT",
        ))
    }

    def __call__(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        symbol = arguments["symbol"]
        base = self._BASE[symbol]
        if tool_name == "get_price":
            return {"symbol": symbol, "price": f"{base * 1.002:.8f}"}
        if tool_name != "get_klines":
            raise ValueError(f"Unsupported read-only tool: {tool_name}")
        interval = arguments["interval"]
        step = {"1d": DAY_MS, "4h": 4 * HOUR_MS, "1h": HOUR_MS, "15m": HOUR_MS // 4}[interval]
        limit = int(arguments["limit"])
        end_time = int(arguments["end_time"])
        start = end_time - step * (limit - 1)
        slope = self._SLOPE[symbol]
        rows = []
        for index in range(limit):
            close = base * (1 + slope * (index - limit / 2))
            open_price = close * (1 - slope / 3)
            spread = max(abs(close) * 0.003, 0.000001)
            rows.append([
                start + index * step,
                f"{open_price:.8f}",
                f"{max(open_price, close) + spread:.8f}",
                f"{min(open_price, close) - spread:.8f}",
                f"{close:.8f}",
                f"{1000 + index * 3:.8f}",
            ])
        return {"data": rows}


def _load_callback(spec: str) -> Callable[[str, dict[str, Any]], Any]:
    if ":" not in spec:
        raise ValueError("--tool-call must use module:function format")
    module_name, attribute = spec.split(":", 1)
    callback = getattr(importlib.import_module(module_name), attribute)
    if not callable(callback):
        raise TypeError("Injected MCP tool callback must be callable")
    return callback


def _utc_ms(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp() * 1000)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Wyckoff + SMC Binance Spot control-room demo")
    parser.add_argument("--mode", choices=("offline", "live"), default="offline")
    parser.add_argument("--symbols", default=",".join(DEFAULT_SYMBOLS))
    parser.add_argument("--tool-call", help="Live injected MCP callback as module:function")
    parser.add_argument("--captured-at", help="Live UTC ISO timestamp, for example 2026-09-05T21:00:00Z")
    parser.add_argument("--checkpoint", default="state/binance_live_paper.json")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    symbols = tuple(symbol.strip().upper() for symbol in args.symbols.split(",") if symbol.strip())
    if not symbols:
        raise ValueError("At least one enabled watchlist symbol is required")

    if args.mode == "offline":
        callback = OfflineBinanceMCP()
        captured_at = OFFLINE_CAPTURED_AT
    else:
        if not args.tool_call or not args.captured_at:
            raise ValueError("Live mode requires --tool-call and --captured-at")
        callback = _load_callback(args.tool_call)
        captured_at = _utc_ms(args.captured_at)

    with TemporaryDirectory() if args.mode == "offline" else nullcontext(".") as checkpoint_dir:
        checkpoint = str(Path(checkpoint_dir) / "offline-paper.json") if args.mode == "offline" else args.checkpoint
        base = live_binance_paper_host_config()
        config = replace(
            base,
            runtime=PaperRuntimeConfig(
                checkpoint_path=checkpoint,
                auto_recover=args.mode == "live",
                checkpoint_after_cycle=True,
                require_all_symbols=True,
            ),
        )
        host = create_live_binance_paper_host(callback, symbols=symbols, config=config)
        cycle_kwargs = {"sleep_fn": (lambda _: None)} if args.mode == "offline" else {}
        output = run_binance_control_room_cycle(host, captured_at=captured_at, **cycle_kwargs)
        print(render_binance_control_room_output(output))
        return 0 if output.status == "PAPER_CYCLE_COMPLETE" else 2


if __name__ == "__main__":
    raise SystemExit(main())
