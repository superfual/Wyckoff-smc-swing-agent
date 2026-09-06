# Hackathon Submission Checklist

## Reproducible proof

- [ ] Open the public GitHub repository on branch `main`.
- [ ] Show the latest green GitHub Actions `Tests` run.
- [ ] Open Actions → `Control-Room Demo` → `Run workflow`, then show its log.
- [ ] Run `python scripts/run_control_room_demo.py` from the repository root.
- [ ] Point out `PAPER ONLY`, `CLOSED CANDLES ONLY`, `NO LOOK-AHEAD`, and `REAL ORDERS DISABLED`.
- [ ] Show acquisition and preflight are `READY` before the paper cycle advances.
- [ ] Show scanner ranking and at least one deep-analysis result.
- [ ] Show the portfolio summary and that no real order was submitted.
- [ ] Open `docs/LIVE_CONTROL_ROOM_20260906.md` as the final 12-coin real-feed evidence.
- [ ] Run `python -m pytest -q` or show its green CI equivalent.

## Suggested 90-second video flow

1. **Problem (0–12s):** Manually applying Wyckoff + SMC across multiple Spot assets is slow and inconsistent.
2. **Agent (12–25s):** Show the curated watchlist and the Binance MCP → closed-candle → analysis architecture.
3. **Live proof (25–55s):** Run the control-room command and explain acquisition, complete-batch preflight, ranking, and selective deep analysis.
4. **Safety proof (55–75s):** Highlight PAPER ONLY, closed candles, no-lookahead, bearish `AVOID_BUY`, and fail-closed `BLOCKED` outcomes.
5. **Engineering proof (75–85s):** Show the latest green CI and deterministic regression count.
6. **Close (85–90s):** “The agent is designed to preserve capital first; it is allowed to decide that no trade is the best trade.”

## Submission fields

- [ ] Public repository URL
- [ ] Demo video URL
- [ ] Track A selected
- [ ] Short project description
- [ ] Architecture and Binance Agent OS/MCP usage explained
- [ ] Setup and demo command included
- [ ] Educational/paper-only disclaimer included
- [ ] Required event survey and social tasks verified

## Live Binance MCP host contract

The control-room CLI never stores Binance credentials. A live host injects one
callable using `module:function` that accepts `(tool_name, arguments)` and returns
the MCP response. Only the configured `get_price` and `get_klines` tool names are
used by the bridge.

Example shape:

```python
def invoke_binance_mcp(tool_name: str, arguments: dict):
    # Delegate to the host's already-connected, read-only Binance MCP transport.
    ...
```

Then run:

```bash
python scripts/run_control_room_demo.py \
  --mode live \
  --tool-call your_host_module:invoke_binance_mcp \
  --captured-at 2026-09-05T21:00:00Z
```

Live calls must remain read-only. Do not add real-order, account, wallet,
transfer, or credential methods for the V1 submission.
