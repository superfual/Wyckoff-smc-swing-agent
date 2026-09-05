# 🧠 Wyckoff + SMC Swing Agent

> An autonomous AI swing-trading agent built with Binance Agent OS that scans Binance Spot markets, discovers potential Wyckoff opportunities, monitors promising candidates, and uses Smart Money Concepts (SMC) to confirm actionable swing setups.

**Binance Agent OS Mini Hackathon — Track A: Build an AI Agent**

---

## 🎯 Problem

Crypto traders have access to hundreds of tradable markets and enormous amounts of market data, but finding the right swing opportunity at the right time is still highly manual.

A trader must repeatedly scan charts and ask:

- Which coins are entering Accumulation?
- Which coins may be transitioning into Markup?
- Is a Spring or liquidity sweep developing?
- Has market structure shifted with CHoCH or BOS?
- Which candidates deserve active monitoring?
- Is there a valid entry with acceptable risk/reward?
- Is an existing position entering Distribution?
- When should a position be reduced or exited?

Wyckoff and Smart Money Concepts can help answer these questions, but manually applying them across many Binance Spot markets and multiple timeframes is difficult to scale.

The challenge is not simply analyzing one chart.

**The challenge is continuously discovering the right charts at the right time.**

---

## 💡 Solution

**Wyckoff + SMC Swing Agent** is designed as an autonomous market-discovery and swing-trading agent.

Instead of waiting for the trader to manually inspect every coin, the agent can scan eligible Binance Spot markets, identify promising Wyckoff structures, place candidates into a dynamic watchlist, and monitor them for SMC confirmation.

The core workflow is:

**Binance Spot → Scan → Filter → Wyckoff Screen → Watch → SMC Confirm → Risk → Signal**

The goal is not to predict every market move.

The goal is to discover selective, high-quality swing opportunities and notify the trader when market structure becomes actionable.

The agent can return states such as:

- 🔵 **WATCH**
- 🟢 **TRADE READY**
- 🟠 **EXIT READY**
- 🔴 **NO TRADE**
- ⚫ **INVALIDATED**

---

## 🤖 Agent Operating Modes

The agent supports three operating modes.

### 🔎 DISCOVER

Autonomously scan eligible Binance Spot markets to discover potential swing opportunities.

The agent searches for structures such as:

- Potential Accumulation
- Potential Distribution
- Spring
- Sign of Strength
- UTAD
- Sign of Weakness
- Early Markup
- Early Markdown

Promising candidates are moved into the dynamic watchlist.

### 👁️ WATCH

Continuously monitor candidates that are structurally interesting but not yet ready to trade.

The agent watches for:

- Liquidity Sweep
- CHoCH
- BOS
- Displacement
- Order Block interaction
- Fair Value Gap interaction
- Setup confirmation
- Setup invalidation

A candidate can transition from:

**WATCH → TRADE READY**

or:

**WATCH → INVALIDATED**

### 🎯 ANALYZE

Perform deep analysis on a specific Binance Spot symbol requested by the user.

For example:

```text
Analyze UNIUSDT for a swing setup.
```

This allows the agent to support both autonomous market discovery and on-demand analysis.

---

## 🧠 What the Agent Does

The agent is designed around eight core capabilities.

### 1. Binance Spot Universe

Identify eligible Binance Spot markets that can be considered for swing analysis.

### 2. Market Scanner

Scan the market for structurally interesting candidates instead of performing expensive deep analysis on every symbol.

### 3. Pre-Filter

Remove markets that do not meet basic requirements such as:

- Tradability
- Sufficient liquidity
- Sufficient market history
- Suitable market structure

### 4. Wyckoff Screening

Identify potential market-cycle conditions such as:

- Accumulation
- Markup
- Distribution
- Markdown
- Spring
- Sign of Strength (SOS)
- Last Point of Support (LPS)
- UTAD
- Sign of Weakness (SOW)
- Last Point of Supply (LPSY)

### 5. Dynamic Watchlist

Automatically track promising candidates.

The watchlist is not limited to a manually selected list of coins.

Candidates may be:

- Added when an interesting structure develops
- Kept under observation while confirmation is incomplete
- Promoted when a valid setup appears
- Removed when the thesis is invalidated

### 6. Smart Money Concepts Confirmation

Analyze market structure and liquidity using:

- Swing High / Swing Low
- Liquidity
- Liquidity Sweep
- Break of Structure (BOS)
- Change of Character (CHoCH)
- Order Block (OB)
- Fair Value Gap (FVG)
- Displacement

### 7. Risk Assessment

For confirmed setups, evaluate:

- Entry zone
- Invalidation
- Stop Loss
- Take Profit
- Risk/Reward

### 8. Signal & Position Monitoring

Generate structured signals and continue monitoring market structure after entry.

Possible outputs include:

- WATCH
- TRADE READY
- EXIT READY
- NO TRADE
- INVALIDATED

---

## 🔄 Agent Workflow

```text
                 BINANCE SPOT
                      │
                      ↓
              MARKET UNIVERSE
                      │
                      ↓
                MARKET SCAN
                      │
                      ↓
                 PRE-FILTER
                      │
                      ↓
              WYCKOFF SCREEN
                      │
              ┌───────┴───────┐
              ↓               ↓
           REJECT         CANDIDATE
                              │
                              ↓
                     DYNAMIC WATCHLIST
                              │
                              ↓
                     DEEP WYCKOFF + SMC
                              │
                              ↓
                      SETUP CONFIRMATION
                              │
                              ↓
                         RISK CHECK
                              │
                   ┌──────────┼──────────┐
                   ↓          ↓          ↓
                 WATCH   TRADE READY  NO TRADE
                              │
                              ↓
                     HUMAN CONFIRMATION
                              │
                              ↓
                       BINANCE ACTION
                              │
                              ↓
                     POSITION MONITORING
                              │
                              ↓
                      DISTRIBUTION /
                       EXIT ANALYSIS
                              │
                              ↓
                         EXIT READY
```

The agent does not force every market through the entire deep-analysis workflow.

Each stage determines what should happen next.

This creates a funnel:

```text
Many Binance Spot Markets
          ↓
     Pre-Filtered Markets
          ↓
   Wyckoff Candidates
          ↓
    Dynamic Watchlist
          ↓
  Confirmed SMC Setups
          ↓
     Trade Signals
```

This allows the agent to focus computational and reasoning resources on the markets that matter most.

---

## 📈 Example — Finding a Long Setup

```text
Binance Spot Scan
        ↓
Potential Accumulation detected
        ↓
Candidate added to Watchlist
        ↓
Spring / Liquidity Sweep detected
        ↓
Bullish CHoCH
        ↓
Bullish BOS
        ↓
Valid Entry Zone
        ↓
Risk/Reward Check
        ↓
TRADE READY 🔔
```

If confirmation is incomplete:

```text
Potential Accumulation
        ↓
Spring detected
        ↓
No bullish BOS yet
        ↓
WATCH 👁️
        ↓
Re-evaluate later
```

If the structure fails:

```text
Candidate
    ↓
Structure Invalidated
    ↓
INVALIDATED
    ↓
Remove from Watchlist
```

---

## 📉 Position & Exit Logic

The agent is not designed only to find entries.

The longer-term objective is to follow the market cycle:

```text
ACCUMULATION
     ↓
TRADE READY
     ↓
   ENTRY
     ↓
  MARKUP
     ↓
   HOLD
     ↓
POTENTIAL DISTRIBUTION
     ↓
UTAD / LIQUIDITY SWEEP
     ↓
BEARISH CHoCH / BOS
     ↓
EXIT READY
```

This allows the agent to reason about the complete swing lifecycle rather than producing isolated buy signals.

---

## 🟡 Binance Agent OS

This project is being developed for **Track A of the Binance Agent OS Mini Hackathon**.

Binance Agent OS provides the infrastructure and capabilities that allow the AI agent to interact with the Binance ecosystem.

The architecture separates AI reasoning from Binance capabilities:

```text
       WYCKOFF + SMC SWING AGENT
                  │
                  ↓
        Discovery & Reasoning
                  │
                  ↓
          Decision Engine
                  │
                  ↓
         Binance Agent OS
                  │
                  ↓
        Binance Capabilities
```

The AI agent decides **what should happen next**.

Binance Agent OS provides the market and trading capabilities required to act on those decisions.

---

## 🛡️ Human-in-the-Loop Safety

The initial version uses human confirmation before trade execution.

The agent may autonomously:

- Scan markets
- Discover candidates
- Maintain a watchlist
- Analyze setups
- Generate signals

But a trading action requires explicit user confirmation.

```text
TRADE READY
     ↓
WAITING FOR CONFIRMATION
     ↓
USER APPROVES
     ↓
BINANCE ACTION
```

The agent should never force a trade when market conditions are unclear.

**A high-quality NO TRADE is better than a low-quality trade.**

---

## 🧩 Agent States

The agent can transition between states:

```text
SCANNING
   ↓
CANDIDATE_FOUND
   ↓
WATCHING
   ↓
ANALYZING
   ↓
SETUP_DETECTED
   ↓
RISK_CHECK
   ↓
TRADE_READY
   ↓
WAITING_CONFIRMATION
   ↓
POSITION_OPEN
   ↓
MANAGING
   ↓
EXIT_READY
   ↓
CLOSED
```

If confirmation is incomplete:

```text
ANALYZING
   ↓
WATCHING
```

If the thesis becomes invalid:

```text
WATCHING
   ↓
INVALIDATED
   ↓
SCANNING
```

---

## 🎬 MVP Demo

The MVP will demonstrate the agent:

1. Accessing Binance Spot market data
2. Scanning multiple markets
3. Filtering potential candidates
4. Detecting a possible Wyckoff structure
5. Adding the candidate to the watchlist
6. Applying SMC confirmation
7. Evaluating risk/reward
8. Returning WATCH, TRADE READY, or NO TRADE

The demo can also show direct analysis of a user-requested symbol.

---

## 🗺️ Development Roadmap

### V1 — Market Discovery Agent

**Binance Spot → Scan → Wyckoff Candidates → Watchlist → SMC Confirmation → Signal**

### V2 — Swing Trading Assistant

**Discovery → Setup → Risk → Alert → Human Confirmation → Position Monitoring**

### V3 — Full Swing Trading Agent

**Discovery → Analysis → Risk → Execution → Position Management → Distribution Detection → Exit**

---

## ⚠️ Disclaimer

This project is built for educational and hackathon demonstration purposes.

It does not constitute financial advice, investment advice, or a recommendation to buy or sell any asset.

Cryptocurrency trading involves significant risk.

---

## 📄 License

MIT License
