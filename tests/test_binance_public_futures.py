"""Offline tests for strict USD-M public candle acquisition."""
import unittest
import tempfile
from pathlib import Path
from src.futures_chart import render_chart

from src.binance_public_futures import FuturesDataError, fetch_closed_klines, collect_futures_market, INTERVAL_MS, LIMITS


def candles(interval, now_ms, count):
    delta = INTERVAL_MS[interval]
    last = (now_ms // delta - 1) * delta
    return [
        [last - (count - 1 - i) * delta, "100", "110", "90", "105", "1000",
         last - (count - 1 - i) * delta + delta - 1, "0", 10, "0", "0", "0"]
        for i in range(count)
    ]


class TestBinancePublicFutures(unittest.TestCase):
    NOW = 1_800_000_001_000

    def test_exact_300_closed_even_when_current_candle_included(self):
        rows = candles("1h", self.NOW, 305)
        live_open = self.NOW // INTERVAL_MS["1h"] * INTERVAL_MS["1h"]
        rows.append([live_open, "105", "110", "95", "108", "7", live_open + 3_599_999])
        result = fetch_closed_klines("BTCUSDT", "1h", 300, now_ms=self.NOW, request_json=lambda _: rows)
        self.assertEqual(len(result), 300)
        self.assertEqual(result[-1][0], live_open - INTERVAL_MS["1h"])

    def test_reject_gap(self):
        rows = candles("1h", self.NOW, 305)
        rows.pop(150)
        with self.assertRaisesRegex(FuturesDataError, "GAP_IN_CLOSED_CANDLES"):
            fetch_closed_klines("BTCUSDT", "1h", 300, now_ms=self.NOW, request_json=lambda _: rows)

    def test_reject_stale(self):
        rows = candles("1h", self.NOW - INTERVAL_MS["1h"], 305)
        with self.assertRaisesRegex(FuturesDataError, "STALE_OR_FUTURE"):
            fetch_closed_klines("BTCUSDT", "1h", 300, now_ms=self.NOW, request_json=lambda _: rows)

    def test_reject_malformed_ohlcv(self):
        rows = candles("1h", self.NOW, 305)
        rows[15][2] = "nan"
        with self.assertRaisesRegex(FuturesDataError, "INVALID_OHLCV"):
            fetch_closed_klines("BTCUSDT", "1h", 300, now_ms=self.NOW, request_json=lambda _: rows)

    def test_reject_binance_error_response(self):
        with self.assertRaisesRegex(FuturesDataError, "INVALID_KLINES_PAYLOAD"):
            fetch_closed_klines("BTCUSDT", "1h", 300, now_ms=self.NOW, request_json=lambda _: {"code": -1003})

    def test_four_timeframes(self):
        def fake_request(url):
            interval = url.split("interval=")[1].split("&")[0]
            return candles(interval, self.NOW, LIMITS[interval] + 5)
        market = collect_futures_market("BTCUSDT", now_ms=self.NOW, request_json=fake_request)
        self.assertEqual((len(market.daily), len(market.four_hour), len(market.one_hour), len(market.fifteen_minute)), (120, 240, 300, 300))
        self.assertEqual(market.current_price, 105.0)

    def test_symbol_validation(self):
        with self.assertRaisesRegex(FuturesDataError, "INVALID_FUTURES_SYMBOL"):
            fetch_closed_klines("BTCUSDT&foo=bar", "1h", 300, now_ms=self.NOW, request_json=lambda _: [])


    def test_chart_uses_verified_candle_prices(self):
        def fake_request(url):
            interval = url.split("interval=")[1].split("&")[0]
            return candles(interval, self.NOW, LIMITS[interval] + 5)
        market = collect_futures_market("ZECUSDT", now_ms=self.NOW, request_json=fake_request)
        with tempfile.TemporaryDirectory() as tmp:
            path = render_chart(market, "H4", Path(tmp) / "chart.svg")
            content = path.read_text(encoding="utf-8")
            self.assertIn("ZECUSDT", content)
            self.assertIn("105.0000", content)
            self.assertIn("<svg", content)

    def test_cli_timeframe_and_mode_validation(self):
        from scripts.run_public_futures_signal import run
        with self.assertRaisesRegex(ValueError, "Unsupported timeframe"):
            run("BTCUSDT", timeframe="W1")
        with self.assertRaisesRegex(ValueError, "Unsupported mode"):
            run("BTCUSDT", mode="trade")

if __name__ == "__main__":
    unittest.main()
