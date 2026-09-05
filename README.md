# 🧠 Wyckoff + SMC Swing Agent

> An AI-powered swing trading agent built with Binance Agent OS that combines Wyckoff market-cycle analysis with Smart Money Concepts (SMC) to identify structured swing trading opportunities.

**Binance Agent OS Mini Hackathon — Track A: Build an AI Agent**

---

## 🎯 Problem

Crypto traders have access to enormous amounts of market data, but turning that data into a consistent trading decision is still highly manual.

A swing trader may need to answer several questions before taking a position:

- Is the market accumulating or distributing?
- Where is liquidity concentrated?
- Has liquidity been swept?
- Has market structure shifted?
- Is there a valid BOS or CHoCH?
- Where is the optimal entry?
- Where should the setup be invalidated?
- Is the risk/reward worth taking?

Wyckoff and Smart Money Concepts can help answer these questions, but combining them consistently across multiple timeframes requires significant manual analysis.

---

## 💡 Solution

**Wyckoff + SMC Swing Agent** is an AI agent designed to transform Binance market data into a structured swing-trading decision workflow.

Instead of simply asking:

> “Is BTC bullish or bearish?”

the agent follows a multi-stage reasoning process:

**Market Data → Wyckoff → SMC → Setup → Risk → Decision**

The goal is not to predict every market move.

The goal is to identify selective, high-quality swing setups and return one of three decisions:

- 🟢 **TRADE READY**
- 🟡 **WAIT**
- 🔴 **NO TRADE**

---

## 🧠 What the Agent Does

The agent is designed around six core capabilities:

### 1. Market Data

Retrieve the market information required for analysis.

### 2. Wyckoff Analysis

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

### 3. Smart Money Concepts

Analyze price structure and liquidity using concepts such as:

- Swing High / Swing Low
- Liquidity
- Liquidity Sweep
- Break of Structure (BOS)
- Change of Character (CHoCH)
- Order Block (OB)
- Fair Value Gap (FVG)

### 4. Setup Detection

Combine Wyckoff context, SMC confirmation, and multi-timeframe structure to determine whether a valid swing setup exists.

### 5. Risk Assessment

Evaluate:

- Entry zone
- Invalidation
- Stop Loss
- Take Profit
- Risk/Reward

### 6. Decision & Action

Return a structured decision and prepare an action only when the setup passes the required checks.

---

## 🔄 Agent Workflow

```text
PHASE 0 — CONFIGURATION
          ↓
PHASE 1 — MARKET SCAN
          ↓
PHASE 2 — WYCKOFF ANALYSIS
          ↓
PHASE 3 — SMC CONFIRMATION
          ↓
PHASE 4 — SETUP DETECTION
          ↓
PHASE 5 — RISK CHECK
          ↓
PHASE 6 — DECISION
          ↓
     ┌────┼────┐
     ↓    ↓    ↓
   READY WAIT NO TRADE
     ↓
HUMAN CONFIRMATION
     ↓
BINANCE ACTION
```

The agent does not need to force every market through the entire workflow.

Each phase determines what should happen next.

For example:

```text
Accumulation detected
        ↓
Check SMC confirmation
        ↓
Liquidity Sweep detected
        ↓
Bullish CHoCH
        ↓
Bullish BOS
        ↓
Valid Entry Zone
        ↓
Risk Check passed
        ↓
TRADE READY
```

If confirmation is missing:

```text
Setup incomplete
      ↓
     WAIT
```

---

## 🟡 Binance Agent OS

This project is being developed for **Track A of the Binance Agent OS Mini Hackathon**.

Binance Agent OS provides the infrastructure and tools that allow the AI agent to interact with Binance capabilities.

The project uses this infrastructure to connect AI reasoning with real market context.

```text
          WYCKOFF + SMC AGENT
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

The AI agent is responsible for deciding **what should happen next**, while Binance Agent OS provides the capabilities required to interact with the Binance ecosystem.

---

## 🛡️ Human-in-the-Loop Safety

The initial version uses human confirmation before trade execution.

Even when the agent identifies a valid setup:

```text
TRADE READY
     ↓
WAIT FOR CONFIRMATION
     ↓
USER APPROVES
     ↓
ACTION
```

The agent should never force a trade when market conditions are unclear.

A high-quality **NO TRADE** is better than a low-quality trade.

---

## 🧩 Agent States

The agent can transition between states:

```text
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

If no valid setup exists, the agent returns to **WATCHING**.

---

## 🎬 Demo

Demo video coming soon.

The MVP demo will show the agent:

1. Receiving a market-analysis request
2. Retrieving Binance market data
3. Identifying the Wyckoff market phase
4. Confirming the setup using SMC
5. Evaluating risk/reward
6. Returning TRADE READY, WAIT, or NO TRADE

---

## 🗺️ Development Roadmap

### V1 — Analyst Agent

Market Data → Wyckoff → SMC → Trading Decision

### V2 — Trading Assistant

Market Scan → Setup Detection → Risk → Alert → Human Confirmation

### V3 — Swing Trading Agent

Market Scan → Analysis → Risk → Execution → Position Management → Exit

---

## ⚠️ Disclaimer

This project is built for educational and hackathon demonstration purposes.

It does not constitute financial advice, investment advice, or a recommendation to buy or sell any asset.

Cryptocurrency trading involves significant risk.

---

## 📄 License

MIT License
