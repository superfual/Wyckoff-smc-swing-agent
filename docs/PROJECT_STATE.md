# Project State — Wyckoff + SMC Spot Swing Agent V1

> Durable technical checkpoint for continuing the project across ChatGPT conversations.
>
> Resume instruction:
>
> `Read docs/PROJECT_STATE.md and latest CI, then continue from NEXT STEP.`

## Source of truth protocol

1. GitHub branch `main` is the source of truth for code and project state.
2. At the start of a new working session, read this file, inspect the latest commit on `main`, and inspect the latest GitHub Actions run.
3. If this document conflicts with the current repository, the current repository wins.
4. Before real-feed work, verify Binance MCP with a harmless read-only Spot price call.
5. Use Binance MCP, not web search, for Binance real-feed validation.
6. Update this document whenever a milestone changes the architecture, safety rules, verified status, or next step.
7. Do not report a coding milestone complete until tests pass and the corresponding CI run on `main` is green.

## Project identity

- Repository: `superfual/Wyckoff-smc-swing-agent`
- Product: Wyckoff + SMC Spot Swing Agent V1
- Market: Binance Spot
- Trading style: defensive swing trading
- Runtime status: PAPER ONLY
- Real exchange orders: forbidden
- Primary objective: capital preservation over trading frequency
- Hackathon scope: Binance Agent OS Mini Hackathon, Track A

## Safety invariants

These rules must remain true unless the project owner explicitly changes the product scope:

- SPOT is the default and production-safe mode.
- Internal analytical theses may be LONG or SHORT.
- Spot may BUY only when the bullish setup, risk checks, and execution guards all pass.
- A bearish Spot thesis becomes `AVOID_BUY` or `NO_TRADE`; it must never create a Futures SHORT.
- Never use an unclosed candle.
- Never use future data or look ahead.
- Never force the agent to produce a trade signal.
- WATCH, SKIP, BLOCKED, AVOID_BUY, and NO_TRADE are valid outcomes.
- Market-data and analysis code must not expose real-order methods.
- Important changes require regression tests.
- No milestone is complete until CI is green.

## Current architecture

```text
Binance MCP
→ MarketData normalization
→ Closed-candle validation
→ History Sufficiency
→ Scanner
→ Wyckoff
→ SMC
→ Confluence
→ Thesis
→ Risk
→ Spot Execution Guard
→ Paper Trading
```

Supporting validation layers:

```text
Historical MarketData
→ As-of cutoff
→ Bar-by-bar Replay
→ No-lookahead audit
→ Conservative Backtest
→ Out-of-sample validation
→ Walk-forward validation
```

## Repository map

### Core market-data and safety boundary

- `src/market_data.py`: Binance kline normalization and `MarketData`
- `src/binance_mcp_bridge.py`: fail-closed, read-only MCP response bridge
- `src/binance_adapter.py`: read-only Binance multi-timeframe provider
- `src/binance_live_paper_validation.py`: live-feed preflight without portfolio mutation
- `src/history_sufficiency.py`: component-specific closed-history requirements
- `src/paper_readiness.py`: paper-runtime configuration safety
- `src/modes.py`: trading-mode definitions

### Analysis pipeline

- `src/scanner.py`: watchlist scoring and classification
- `src/wyckoff.py`: Wyckoff range, event, phase, bias, and confidence analysis
- `src/smc.py`: confirmed swings, BOS/CHoCH, liquidity, FVG, and order blocks
- `src/confluence.py`: evidence agreement and contradiction scoring
- `src/thesis.py`: directional analytical thesis and setup state
- `src/risk.py`: risk acceptance or `NO_TRADE`
- `src/execution.py`: final Spot execution guard
- `src/orchestrator.py`: end-to-end symbol analysis

### Paper runtime

- `src/paper_trading.py`: paper portfolio behavior
- `src/paper_runner.py`: closed-candle paper cycle
- `src/paper_runtime.py`: provider/runtime orchestration
- `src/paper_session.py`: paper-session state
- `src/binance_paper_host.py`: production-safe paper host configuration
- `src/portfolio_safety.py`: portfolio-level safety
- `src/persistence.py`: checkpoint persistence and recovery
- `src/paper_report.py`: paper reports
- `src/readiness.py`: readiness evaluation

### Research validation

- `src/replay.py`: as-of, bar-by-bar historical replay with audit metadata
- `src/backtest.py`: conservative future-bar-only trade simulation
- `src/analytics.py`: backtest performance breakdown
- `src/validation.py`: research/out-of-sample validation
- `src/walk_forward.py`: chronological multi-fold validation
- `src/comparator.py`: strategy/result comparison

### Configuration and CI

- `config/watchlist.json`: curated 12-symbol Binance Spot watchlist
- `.github/workflows/tests.yml`: full pytest suite plus BTC regression
- `.github/workflows/real-btc-snapshot.yml`: deterministic BTC snapshot workflow
- `tests/fixtures/btcusdt_real_20260905T180244Z.json`: canonical compact BTC regression fixture

## Watchlist

The configured 12-symbol Spot watchlist is:

- High priority: `BTCUSDT`, `ETHUSDT`, `BNBUSDT`, `SOLUSDT`
- Medium priority: `XRPUSDT`, `DOGEUSDT`, `ADAUSDT`, `LINKUSDT`, `AVAXUSDT`, `SUIUSDT`, `UNIUSDT`, `AAVEUSDT`

## Completed milestones

- Curated Spot watchlist created.
- Deterministic market-data normalization implemented.
- Closed-candle filtering and validation implemented.
- Strategy-specific history sufficiency gate implemented.
- Scanner, Wyckoff, SMC, confluence, thesis, risk, and Spot execution guard implemented.
- Paper runtime, checkpointing, reporting, readiness, and portfolio safety implemented.
- Binance MCP read-only bridge and live-paper preflight implemented.
- Conservative replay/backtest/OOS/walk-forward research layers implemented.
- Canonical BTCUSDT real-feed regression fixture committed.
- BTC end-to-end regression locked to a defensive result.
- Historical replay hardened with:
  - explicit `ReplayConfig.as_of_time`
  - strict timestamp chronology validation
  - per-step multi-timeframe candle-count audit
  - per-step latest-known close-time audit
  - future-prefix invariance regression test
  - `no_lookahead_verified` and `audit_errors`

## Verified BTC checkpoints

### Canonical deterministic regression

Decision time: `2026-09-05 18:02:44 UTC`

Original validated raw snapshot after removing open candles:

- 1D: 119 closed
- 4H: 239 closed
- 1H: 299 closed
- 15M: 298 closed
- Total: 955 closed candles

The committed compact fixture intentionally keeps only the history needed for deterministic regression:

- 1D: 20
- 4H: 30
- 1H: 80
- 15M: 16

Locked end-to-end result:

- Scanner: `WATCH`, score `73`
- Wyckoff 4H: `NEUTRAL / UNCONFIRMED`
- SMC 1H: bullish transition; latest structural trigger is bullish CHoCH
- Confluence: bullish, low confidence
- Thesis: `WATCH / LONG` analytical thesis
- Risk: `NO_TRADE`
- Spot execution: `BLOCKED`
- Exchange order: none

### Latest live read-only verification before this document

Checked at approximately `2026-09-05 19:47 UTC`.

- Binance MCP Spot ticker and all required kline endpoints responded successfully.
- BTCUSDT was approximately `79,790 USDT` at the check time.
- 1D, 4H, 1H, and 15M each correctly exposed one currently forming candle.
- The last closed 1H candle was `18:00–19:00 UTC`, close `79,999.98`.
- Open candles were excluded from decision data.

Prices are time-sensitive and must be refreshed from Binance MCP; they are not golden test values.

## Historical replay verification

A full 1H replay of the refreshed BTC snapshot, bounded by an exact as-of time, produced:

- 260 decision steps
- 216 `SKIP`
- 30 `BLOCKED`
- 14 `AVOID_BUY`
- 0 real orders
- 1 open reference candle excluded
- `no_lookahead_verified = true`
- `audit_errors = []`

At the final 1H decision boundary, replay could see only the 15M candles that had closed by that exact hour. Later-closed 15M candles present in the downloaded snapshot were excluded. Tests also prove that appending future candles cannot change earlier decisions.

## Last verified repository baseline

Implementation baseline immediately before adding this document:

- Commit: `c0dcef1b726186dc66e94ed5f823edd84b49f100`
- Message: `Harden historical replay no-lookahead audit`
- Local suite: `260 passed`
- GitHub Actions workflow `Tests`: success
- CI run: `33987931763`

Always inspect the current `main` commit and latest CI instead of assuming this baseline is still latest.

## NEXT STEP

### Validate the complete 12-coin real watchlist through the read-only pipeline

Implement and verify a repeatable multi-symbol real-feed validation flow:

1. Read enabled symbols and priorities from `config/watchlist.json`.
2. Use Binance MCP Spot endpoints only; do not use web data.
3. Fetch current price plus required `1D`, `4H`, `1H`, and `15M` klines for every enabled symbol.
4. Capture one explicit decision time for the whole batch.
5. Normalize timestamps and OHLCV.
6. Remove every candle whose close time is later than the batch decision time.
7. Reject missing, duplicate, descending, stale, or future data.
8. Apply history sufficiency before analysis.
9. Run Scanner for all valid symbols.
10. Rank candidates without forcing a signal.
11. Run Wyckoff + SMC deep analysis only for eligible candidates.
12. Enforce Spot semantics: bearish means `AVOID_BUY / NO_TRADE`, never Futures SHORT.
13. Produce a deterministic paper-only validation report.
14. Add tests for all new batch-level safety behavior.
15. Push to `main` and wait for green CI.

Do not expand to autonomous execution. Do not send exchange orders.

## New-session startup checklist

When resuming in a new chat:

1. Read this file directly from GitHub `main`.
2. Inspect the latest commit and latest CI.
3. Confirm the worktree/source matches GitHub.
4. Test Binance MCP with `BTCUSDT Spot current price`.
5. Re-read `NEXT STEP`.
6. State the planned change before editing.
7. Preserve PAPER ONLY and all safety invariants.
8. Run focused tests, then the full suite.
9. Push only reviewed changes.
10. Confirm the latest CI is green.
11. Update this file when the milestone or next step changes.
