# Binance USD-M public-feed fallback (read-only)

This is an independent public data path, not a fix to Binance MCP.
It requests official USD-M Futures /fapi/v1/klines without keys, secrets or trading permissions.

## Launch
After merge: Actions > Public Futures Wyckoff-SMC (read-only) > Run workflow.
Input example: BTCUSDT. Automatic hourly scheduling is intentionally disabled until the API can be reached from the runner.
Download the futures-signal artifact containing the JSON report (retained 7 days).

## Hard data gates
- Obtain 120 closed daily, 240 closed 4H, exactly 300 closed H1 and 300 closed 15M candles.
- Overfetch five bars; discard the currently open candle.
- Reject stale, future, duplicate, non-contiguous, malformed or non-finite OHLCV.
- Use the last closed 15M close only as a reference, not a claimed live quote.
- Pass verified candles into the existing scanner, Wyckoff, SMC, confluence, thesis and risk engines.
- SIGNAL_CANDIDATE is analysis-only and must be manually reviewed.
- NO_CLEAR_EDGE means no actionable proposed setup.
- DATA_UNAVAILABLE fails the workflow and never fabricates a trade signal.
- Scenario NAV 10,000 USDT is illustrative; risk capped at 0.5% per theoretical trade.

## Test
Run: python -m unittest tests/test_binance_public_futures.py -v

The workflow grants read-only repository permissions, never places orders, and requires no API key.
GitHub-hosted runner network access to Binance is not guaranteed; blocked IPs fail closed. On the first live test, Binance returned an HTTP error from the GitHub runner; do not assume automatic collection works until a successful live run.
