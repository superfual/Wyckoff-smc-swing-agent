# Final Binance MCP Control-Room Evidence

This is the final read-only, PAPER-ONLY watchlist capture prepared for the
hackathon demo. It is a time-specific observation, not a golden trading output.

## Capture boundary

- Decision time: `2026-09-06 07:00:00 UTC` (`1788678000000` ms)
- Source: Binance MCP Server Spot ticker and kline endpoints
- Watchlist: all 12 enabled symbols from `config/watchlist.json`
- Raw candles per symbol: `120/240/300/300` (`1D/4H/1H/15M`)
- Closed candles per symbol: `119/239/299/299`
- Open candle removed from every symbol and timeframe: yes
- Acquisition failures: `0`
- Complete-batch preflight: `READY`
- Real exchange orders: `0` (unsupported and disabled)

## Control-room result

| Rank | Symbol | Score | Scanner | Spot action |
|---:|---|---:|---|---|
| 1 | BTCUSDT | 83 | HIGH_INTEREST | BLOCKED |
| 2 | XRPUSDT | 83 | HIGH_INTEREST | BLOCKED |
| 3 | ETHUSDT | 77 | HIGH_INTEREST | BLOCKED |
| 4 | ADAUSDT | 77 | HIGH_INTEREST | BLOCKED |
| 5 | LINKUSDT | 76 | HIGH_INTEREST | BLOCKED |
| 6 | SOLUSDT | 71 | WATCH | BLOCKED |
| 7 | AVAXUSDT | 70 | WATCH | BLOCKED |
| 8 | SUIUSDT | 70 | WATCH | BLOCKED |
| 9 | BNBUSDT | 65 | WATCH | BLOCKED |
| 10 | DOGEUSDT | 60 | WATCH | BLOCKED |
| 11 | UNIUSDT | 60 | WATCH | BLOCKED |
| 12 | AAVEUSDT | 53 | NEUTRAL | SCANNED_ONLY |

## Paper portfolio result

- Cycle status: `PAPER_CYCLE_COMPLETE`
- Symbols processed: `12`
- Symbols skipped by runtime: `0`
- Paper equity: `10,000.00 USDT`
- Exposure: `0.00%`
- Open positions: `0`
- Paper trades: `0`
- Real trades: `0`

## Interpretation

Eleven symbols passed the lightweight scanner threshold for deep analysis, but
none passed the complete thesis, risk, and Spot execution gates. The agent did
not force a BUY signal. This validates the V1 design principle that capital
preservation has priority over trading frequency.

Safety statement: **PAPER ONLY · CLOSED CANDLES ONLY · NO LOOK-AHEAD · REAL
ORDERS DISABLED**.
