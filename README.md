# 🧠 Wyckoff + SMC Spot Swing Agent

> An autonomous AI swing-trading agent built with Binance Agent OS that continuously monitors a curated watchlist of liquid Binance Spot assets, identifies potential Wyckoff accumulation opportunities, uses Smart Money Concepts (SMC) for confirmation, and monitors positions for distribution and exit conditions.

**Binance Agent OS Mini Hackathon — Track A: Build an AI Agent**

---

## Run the deterministic demo

Open the judge-facing dashboard:

**[Wyckoff + SMC Spot Control Room](https://superfual.github.io/Wyckoff-smc-swing-agent/)**

The static GitHub Pages dashboard presents the verified 12-symbol snapshot,
safety gates, paper portfolio, pipeline, and links to reproducible evidence. It
does not call Binance or expose credentials/order functions in the browser.

From the repository root (Python 3.11+; no API key required):

```bash
python scripts/run_control_room_demo.py
```

The command runs the real acquisition → preflight → analysis → Spot guard →
paper-cycle path against a deterministic, read-only Binance MCP callback. It
prints watchlist ranking, defensive actions, checkpoint status, and portfolio
state. The expected safety banner is:

```text
Mode: PAPER ONLY
Safety: CLOSED CANDLES ONLY | NO LOOK-AHEAD | REAL ORDERS DISABLED
```

Run the complete regression suite with:

```bash
python -m pytest -q
```

Live market data remains host-injected and read-only. The CLI accepts a callback
as `--tool-call module:function`; no credentials or exchange-order functions are
stored in this repository. See [the submission checklist](docs/SUBMISSION_CHECKLIST.md)
for the judge-facing demo flow.

---

## 🎯 Problem

Swing trading crypto is not simply about finding a coin that may go up.

A trader must repeatedly answer questions such as:

- Which assets are currently entering Accumulation?
- Is a Spring or sell-side liquidity sweep developing?
- Has market structure shifted with CHoCH or BOS?
- Is the setup confirmed or still too early?
- Is the current price located in a reasonable entry zone?
- Does the setup offer acceptable risk/reward?
- Should an existing position continue to be held?
- Is Markup losing strength?
- Is Distribution beginning?
- Has an exit condition appeared?

Wyckoff and Smart Money Concepts can help answer these questions, but applying them manually across multiple assets and multiple timeframes requires constant chart monitoring.

For Spot swing trading, analyzing every Binance-listed asset is also unnecessary.

The agent should focus its attention on a curated watchlist of liquid, established Binance Spot markets and continuously search that watchlist for high-quality swing opportunities.

**The challenge is not analyzing every coin.**

**The challenge is continuously monitoring the right assets and recognizing when market structure becomes actionable.**

---

## 💡 Solution

**Wyckoff + SMC Spot Swing Agent** is an autonomous monitoring and decision agent designed specifically for Binance Spot swing trading.

Instead of waiting for the trader to manually inspect each chart, the agent continuously monitors a configurable watchlist of liquid Binance Spot assets.

It uses:

- Binance market data
- Wyckoff market-cycle analysis
- Smart Money Concepts
- Multi-timeframe structure
- Liquidity behavior
- Volume
- Risk/Reward analysis

to determine what action, if any, deserves the trader's attention.

The core workflow is:

```text
CURATED SPOT WATCHLIST
          ↓
     BINANCE DATA
          ↓
   WYCKOFF SCREENING
          ↓
   SMC CONFIRMATION
          ↓
      RISK CHECK
          ↓
      DECISION
          ↓
 POSITION MONITORING
          ↓
 DISTRIBUTION / EXIT
```

The goal is not to predict every price movement.

The goal is to selectively identify attractive Spot swing opportunities and monitor them throughout the trade lifecycle.

---

## 🎯 V1 Trading Focus

The initial hackathon version focuses on:

**Spot + Long Swing Trading**

The primary market lifecycle is:

```text
ACCUMULATION
     ↓
CONFIRMATION
     ↓
BUY READY
     ↓
ENTRY
     ↓
MARKUP
     ↓
HOLD / MANAGE
     ↓
DISTRIBUTION
     ↓
EXIT READY
     ↓
CLOSED
```

The V1 agent does not seek short-selling opportunities.

Bearish Wyckoff and SMC signals are still important, but they are primarily used to:

- Avoid poor long entries
- Invalidate developing setups
- Detect deterioration in an open position
- Identify potential Distribution
- Generate EXIT READY conditions

---

## 👀 Curated Spot Watchlist

Instead of scanning every Binance Spot market, V1 monitors a curated watchlist of liquid Spot assets.

The initial watchlist can include markets such as:

```text
BTCUSDT
ETHUSDT
BNBUSDT
SOLUSDT
XRPUSDT
DOGEUSDT
ADAUSDT
LINKUSDT
AVAXUSDT
SUIUSDT
UNIUSDT
AAVEUSDT
```

The watchlist is configurable and is not intended to imply that every listed asset is always suitable for a trade.

The purpose of the watchlist is to concentrate the agent's reasoning resources on markets that are intentionally selected for monitoring.

For the MVP, this provides several practical advantages:

- Smaller monitoring universe
- Lower data requirements
- Faster analysis
- More consistent market history
- Better focus for multi-timeframe reasoning
- Easier demonstration of the autonomous agent workflow

Future versions may support broader autonomous Binance Spot market discovery.

---

## 🤖 Agent Operating Modes

The agent supports three primary operating modes:

### 🔎 DISCOVER

Autonomously scan the configured Spot watchlist for developing swing opportunities.

The trader does not need to request analysis coin by coin.

For example:

```text
Scan my swing watchlist.
```

The agent may return:

```text
BTCUSDT    → NO_TRADE
ETHUSDT    → WATCH
BNBUSDT    → NO_TRADE
SOLUSDT    → WATCH
SUIUSDT    → BUY_READY
UNIUSDT    → WATCH
```

DISCOVER is therefore autonomous opportunity discovery **inside the configured watchlist**.

---

### 👁️ WATCH

Continuously monitor a structurally interesting asset that is not yet ready for entry.

The agent may watch for:

- Trading range development
- Accumulation
- Spring
- Test
- Sign of Strength
- Last Point of Support
- Sell-side liquidity sweep
- Bullish CHoCH
- Bullish BOS
- Displacement
- Order Block interaction
- Fair Value Gap interaction
- Entry-zone interaction
- Setup invalidation

A promising setup does not need to become a trade immediately.

For example:

```text
Potential Accumulation
        ↓
Spring detected
        ↓
Sell-side liquidity swept
        ↓
Bullish CHoCH
        ↓
No confirmed BOS yet
        ↓
WATCH
```

The agent continues monitoring instead of forcing an early entry.

---

### 🎯 ANALYZE

Perform immediate deep analysis on a specific Binance Spot symbol requested by the user.

Example:

```text
Analyze UNIUSDT for a Spot swing setup.
```

ANALYZE mode allows the trader to inspect a particular asset even when the autonomous watchlist scan has not selected it as the highest-priority candidate.

---

## 🧠 Analysis Framework

The agent combines three primary reasoning layers.

### 1. Wyckoff — Market Cycle Context

Wyckoff is used to understand where price may be located within the broader market cycle.

The agent analyzes conditions such as:

- Accumulation
- Markup
- Distribution
- Markdown
- Trading Range

Relevant accumulation events may include:

- Selling Climax (SC)
- Automatic Rally (AR)
- Secondary Test (ST)
- Spring
- Test
- Sign of Strength (SOS)
- Last Point of Support (LPS)

Relevant distribution events may include:

- Buying Climax (BC)
- Automatic Reaction (AR)
- Secondary Test (ST)
- Upthrust
- UTAD
- Sign of Weakness (SOW)
- Last Point of Supply (LPSY)

The agent must not classify a Wyckoff phase from one isolated candle.

Wyckoff provides the **context**, not an automatic buy signal.

---

### 2. SMC — Structure & Confirmation

Smart Money Concepts are primarily used for confirmation and timing.

The agent analyzes:

- Swing High
- Swing Low
- Equal Highs
- Equal Lows
- Buy-side Liquidity
- Sell-side Liquidity
- Liquidity Sweep
- Change of Character (CHoCH)
- Break of Structure (BOS)
- Displacement
- Order Block (OB)
- Fair Value Gap (FVG)
- Structural invalidation

For a potential long setup, a stronger sequence may look like:

```text
ACCUMULATION
     ↓
SPRING
     ↓
SELL-SIDE LIQUIDITY SWEEP
     ↓
BULLISH CHoCH
     ↓
BULLISH BOS
     ↓
ENTRY OPPORTUNITY
```

SMC confirms the thesis rather than replacing Wyckoff context.

---

### 3. Risk — Trade Quality

A technically valid setup is not automatically a good trade.

Before producing BUY READY, the agent evaluates:

- Entry zone
- Preferred entry
- Structural invalidation
- Stop Loss
- Take Profit
- Risk/Reward

If confirmation exists but price has not reached a suitable entry area:

```text
WATCH
```

If expected Risk/Reward is unacceptable:

```text
NO_TRADE
```

The agent should never create a trade merely because a recognizable pattern exists.

---

## ⏱️ Multi-Timeframe Analysis

The agent uses multiple timeframes because each timeframe serves a different purpose.

| Timeframe | Primary Role |
|---|---|
| 1D | Macro context |
| 4H | Primary Wyckoff structure |
| 1H | Market structure and setup confirmation |
| 15M | Entry refinement |

Suggested deep-analysis history:

| Timeframe | Candles |
|---|---:|
| 1D | 150 |
| 4H | 200 |
| 1H | 300 |
| 15M | 300 |

The agent does not need to perform maximum-depth analysis on every watchlist asset during every scan.

A lightweight screen can first identify which assets deserve deeper reasoning.

---

## 🔄 Agent Workflow

```text
             CONFIGURED WATCHLIST
                     │
                     ↓
              BINANCE SPOT DATA
                     │
                     ↓
              WYCKOFF SCREENING
                     │
             ┌───────┴────────┐
             ↓                ↓
        NOT INTERESTING    INTERESTING
             │                │
             ↓                ↓
         NO_TRADE          DEEP ANALYSIS
                              │
                              ↓
                       WYCKOFF + SMC
                              │
                              ↓
                       SETUP DECISION
                              │
                   ┌──────────┼──────────┐
                   ↓          ↓          ↓
               NO_TRADE     WATCH     BUY_READY
                                         │
                                         ↓
                                  PAPER GUARD
                                         │
                                         ↓
                                  PAPER ACTION
                                         │
                                         ↓
                              PAPER POSITION OPEN
                                         │
                                         ↓
                                   MONITORING
                                         │
                             ┌───────────┴───────────┐
                             ↓                       ↓
                           HOLD              DISTRIBUTION /
                                               INVALIDATION
                                                     │
                                                     ↓
                                                EXIT_READY
                                                     │
                                                     ↓
                                               PAPER GUARD
                                                     │
                                                     ↓
                                             PAPER POSITION CLOSED
```

---

## 🟢 Long Setup Logic

The agent looks for alignment between Wyckoff context and SMC confirmation.

A stronger long setup may contain:

- Accumulation or early Markup
- Meaningful location inside or around a trading range
- Spring or failed breakdown
- Sell-side liquidity sweep
- Bullish CHoCH
- Bullish BOS
- Bullish displacement
- Logical entry zone
- Clearly defined invalidation
- Acceptable Risk/Reward

Example:

```text
Potential Accumulation
        ↓
Spring
        ↓
Liquidity Sweep
        ↓
Bullish CHoCH
        ↓
Bullish BOS
        ↓
Entry Zone
        ↓
Risk Check
        ↓
BUY_READY
```

If confirmation is incomplete:

```text
Potential Accumulation
        ↓
Spring
        ↓
Bullish CHoCH
        ↓
No BOS yet
        ↓
WATCH
```

If the thesis fails:

```text
WATCH
   ↓
Structural Invalidation
   ↓
INVALIDATED
```

---

## 📈 Position Management

The agent does not stop working after identifying an entry.

Once a confirmed trade becomes an actively monitored position, the objective changes from finding an entry to managing the swing thesis.

The agent monitors:

- Original Wyckoff thesis
- Structural invalidation
- Markup progression
- New liquidity behavior
- Trend continuation
- Potential Distribution
- Buy-side liquidity sweep
- UTAD
- Bearish CHoCH
- Bearish BOS
- Sign of Weakness

A temporary price decline does not automatically mean EXIT READY.

The agent evaluates structural evidence.

---

## 📉 Distribution & Exit Logic

A possible exit sequence may look like:

```text
MARKUP
   ↓
POTENTIAL DISTRIBUTION
   ↓
BUY-SIDE LIQUIDITY SWEEP
   ↓
UPTHRUST / UTAD
   ↓
BEARISH CHoCH
   ↓
BEARISH BOS
   ↓
SIGN OF WEAKNESS
   ↓
EXIT_READY
```

The purpose is to allow the agent to reason about the complete Spot swing lifecycle rather than generating isolated buy signals.

---

## 🚦 Agent Decisions

The primary V1 decision states are:

### 🔵 WATCH

The asset is structurally interesting, but the setup is incomplete or the desired entry has not been reached.

### 🟢 BUY_READY

A Spot long setup has sufficient Wyckoff context, SMC confirmation, defined invalidation, and acceptable trade structure.

BUY_READY does **not** mean automatic execution. In V1 it can only become a
paper-trading action; this repository has no real exchange-order path.

### 🟡 HOLD

An existing position remains structurally valid and no confirmed exit condition has developed.

### 🟠 EXIT_READY

An existing position shows sufficiently strong structural evidence of deterioration, Distribution, or thesis invalidation.

### 🔴 NO_TRADE

There is currently no sufficiently attractive long opportunity.

### ⚫ INVALIDATED

A previously monitored setup has structurally failed.

---

## 🧩 Agent State Machine

```text
SCANNING_WATCHLIST
        ↓
   ANALYZING
        ↓
 ┌──────┴─────────────┐
 ↓                    ↓
NO_TRADE         SETUP_DETECTED
                       ↓
                  RISK_CHECK
                       ↓
             ┌─────────┴─────────┐
             ↓                   ↓
           WATCH             BUY_READY
             │                   │
             │                   ↓
             │          WAITING_CONFIRMATION
             │                   │
             │                   ↓
             └──────────→   POSITION_OPEN
                                 │
                                 ↓
                              MANAGING
                                 │
                        ┌────────┴────────┐
                        ↓                 ↓
                       HOLD          EXIT_READY
                                          │
                                          ↓
                               WAITING_CONFIRMATION
                                          │
                                          ↓
                                        CLOSED
```

A watched thesis may also transition to:

```text
WATCH
  ↓
INVALIDATED
```

---

## 📊 Required Watchlist Output

A watchlist scan should produce a concise overview.

Example:

```text
SPOT SWING WATCHLIST

BTCUSDT
Status: NO_TRADE
Wyckoff: Markup
Reason: No attractive entry location

ETHUSDT
Status: WATCH
Wyckoff: Potential Accumulation
Trigger: Bullish BOS required

SUIUSDT
Status: BUY_READY
Wyckoff: Late Accumulation / Early Markup
SMC: Bullish CHoCH + BOS confirmed
Next Action: Review full setup
```

This allows the trader to immediately see which assets deserve attention.

---

## 📋 Required BUY_READY Output

When a setup becomes actionable, the agent should return:

```text
SYMBOL:
DIRECTION: LONG SPOT

WYCKOFF THESIS:
SMC CONFIRMATION:

ENTRY ZONE:
PREFERRED ENTRY:
STOP LOSS:
TAKE PROFIT:
RISK/REWARD:

INVALIDATION:

DECISION:
BUY_READY

EXECUTION:
PAPER ONLY / REAL ORDERS DISABLED
```

---

## 📋 Required Position Output

For an actively monitored position:

```text
SYMBOL:

ORIGINAL THESIS:
CURRENT WYCKOFF PHASE:

MARKET STRUCTURE:
LIQUIDITY EVENT:
CHoCH:
BOS:

DECISION:
HOLD / EXIT_READY

REASON:
```

---

## 🟡 Binance Agent OS

This project is being developed for **Track A of the Binance Agent OS Mini Hackathon**.

Binance Agent OS provides the infrastructure and Binance capabilities used by the AI agent.

The architecture separates agent reasoning from Binance capabilities:

```text
        WYCKOFF + SMC
        SPOT SWING AGENT
               │
               ↓
       AUTONOMOUS MONITORING
               │
               ↓
       WYCKOFF + SMC REASONING
               │
               ↓
          DECISION ENGINE
               │
               ↓
        BINANCE AGENT OS
               │
               ↓
       BINANCE CAPABILITIES
```

The AI agent determines **what deserves attention and what should happen next**.

Binance Agent OS provides the capabilities required to retrieve Binance data and interact with the Binance ecosystem.

---

## 🔌 Binance MCP Integration

For the MVP, Binance MCP provides a practical connection between the agent and Binance capabilities.

The agent can use Binance market-data tools to retrieve information such as:

- Spot symbol information
- Current prices
- Candlestick / Kline data
- Volume
- Market structure inputs

This creates the core data path:

```text
BINANCE
   ↓
BINANCE AGENT OS / MCP
   ↓
MARKET DATA
   ↓
WYCKOFF + SMC AGENT
   ↓
DECISION
```

MCP is a capability used by the agent.

**The agent itself is the product.**

---

## 🛡️ Paper-Only Safety

The V1 hackathon agent is autonomous in analysis but **paper-only in execution**.

The agent may autonomously:

- Monitor the configured watchlist
- Retrieve market data
- Analyze Wyckoff structure
- Analyze SMC confirmation
- Identify opportunities
- Generate BUY_READY signals
- Monitor existing positions
- Generate EXIT_READY signals

No user phrase can authorize a real trade because the repository exposes no
account, credential, wallet, transfer, or exchange-order method.

```text
BUY_READY
    ↓
SPOT EXECUTION GUARD
    ↓
PAPER RUNTIME
    ↓
VIRTUAL POSITION ONLY
```

The same principle applies to exits. Real execution is outside V1 scope.

Casual responses such as:

```text
OK
Nice
Interesting
Looks good
```

must not be interpreted as authorization to execute a trade.

---

## 🔐 Data Integrity

The agent must never invent:

- Binance prices
- Candles
- Volume
- Account balances
- Positions
- Orders
- Execution status

The agent clearly separates:

```text
OBSERVED BINANCE DATA
```

from:

```text
AI INTERPRETATION
```

If required market data cannot be retrieved, the correct response is:

```text
DATA_UNAVAILABLE
```

not a fabricated trading signal.

---

## 🎬 MVP Demo

The hackathon MVP demonstrates an end-to-end autonomous Spot swing workflow.

### Demo Flow

```text
1. Load configured Spot watchlist
          ↓
2. Retrieve live Binance market data
          ↓
3. Screen watchlist
          ↓
4. Identify interesting asset
          ↓
5. Perform deeper Wyckoff analysis
          ↓
6. Apply SMC confirmation
          ↓
7. Evaluate entry + risk
          ↓
8. Return WATCH / BUY_READY / NO_TRADE
```

A strong demo example would look like:

```text
User:
Scan my Spot swing watchlist.

Agent:
BTCUSDT → NO_TRADE
ETHUSDT → WATCH
BNBUSDT → NO_TRADE
SOLUSDT → WATCH
SUIUSDT → BUY_READY

Highest-priority setup: SUIUSDT

Wyckoff:
Potential late Accumulation / early Markup

SMC:
Sell-side liquidity sweep
Bullish CHoCH
Bullish BOS

Decision:
BUY_READY

Execution:
PAPER ONLY / REAL ORDERS DISABLED
```

The deterministic control-room demo is available directly:

```bash
python scripts/run_control_room_demo.py
```

It intentionally permits `WATCH`, `BLOCKED`, `AVOID_BUY`, and `SCANNED_ONLY`
outcomes. A demo with no BUY is valid evidence that capital preservation outranks
trading frequency.

The demo can additionally show:

```text
Analyze UNIUSDT.
```

to demonstrate on-demand deep analysis.

---

## Historical replay and no-lookahead contract

`src/replay.py` replays one closed reference candle at a time through the full
agent orchestrator. `ReplayConfig.as_of_time` may be set to the exact historical
decision cutoff; any reference candle whose close is later than that cutoff is
excluded, including a currently forming Binance candle.

Every replay step records the candle count and latest known close time for all
four timeframes. A trustworthy result reports `no_lookahead_verified=true` and
an empty `audit_errors` list. Replay also fails closed on duplicate, descending,
or negative candle timestamps. Tests verify prefix invariance: appending future
data cannot change decisions made at or before the configured cutoff.

This is research and paper-validation infrastructure only. It does not submit
exchange orders.

---

## 🗺️ Development Roadmap

### V1 — Curated Watchlist Spot Swing Agent

```text
Watchlist
→ Binance Data
→ Wyckoff Screen
→ SMC Confirmation
→ Risk
→ WATCH / BUY_READY / NO_TRADE
```

Primary objective:

**Deliver a working Binance Agent OS hackathon MVP.**

---

### V2 — Autonomous Market Discovery

Expand beyond the curated watchlist.

```text
Binance Spot Universe
→ Liquidity Filter
→ Structural Scanner
→ Candidate Discovery
→ Dynamic Watchlist
→ Deep Analysis
```

This version allows the agent to autonomously discover new assets that deserve monitoring.

---

### V3 — Full Swing Lifecycle Agent

Expand position-management capabilities.

```text
Discovery
→ Accumulation
→ Confirmation
→ Entry
→ Markup
→ Position Management
→ Distribution Detection
→ Exit
```

Potential future improvements include:

- Dynamic watchlist management
- Broader Binance Spot discovery
- More deterministic structure detection
- Persistent position state
- Automated alerts
- Configurable risk profiles
- Enhanced execution workflows

---

## 🧠 Core Philosophy

The agent follows several principles:

1. Focus on selected, liquid Spot markets.
2. Use Wyckoff for market-cycle context.
3. Use SMC primarily for confirmation and timing.
4. Use multi-timeframe evidence.
5. WATCH is a valid decision.
6. Do not force an early entry.
7. Do not confuse one pattern with a complete setup.
8. Require logical invalidation.
9. Evaluate risk before declaring BUY_READY.
10. Continue monitoring after entry.
11. Use bearish structure primarily for risk avoidance and exit decisions in V1.
12. Separate observed Binance data from AI interpretation.
13. Require human confirmation before execution.

The objective is not maximum trading frequency.

The objective is:

**Find Accumulation → Confirm → Buy → Ride Markup → Detect Distribution → Exit.**

---

## ⚠️ Disclaimer

This project is built for educational and hackathon demonstration purposes.

It does not constitute financial advice, investment advice, or a recommendation to buy or sell any asset.

Cryptocurrency trading involves significant risk, including the potential loss of capital.

Using liquid or large-cap assets does not eliminate market risk or the possibility of significant drawdowns.

---

## 📄 License

MIT License
