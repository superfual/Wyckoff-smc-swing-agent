# Guarded Live Spot Execution Roadmap

> **Status:** Post-hackathon product direction. The V1 repository remains
> **PAPER ONLY** and does not submit real exchange orders.

## Product vision

The long-term goal is a defensive, autonomous Binance Spot swing agent that can
move from market discovery to guarded execution and position management without
weakening the V1 principles: closed candles only, no look-ahead, no forced
signals, and capital preservation before trading frequency.

V1 already implements the reasoning and safety boundary:

```text
Binance MCP market data
→ Closed-candle and history gates
→ Scanner
→ Wyckoff
→ SMC
→ Confluence
→ Thesis
→ Risk
→ Spot Execution Guard
→ Paper runtime
```

A future live version would replace only the final paper sink with a tightly
controlled execution adapter. Analysis does not receive permission to bypass
risk or execution gates.

## Current versus planned capability

| Capability | V1 status | Post-validation direction |
| --- | --- | --- |
| Binance MCP Spot price and klines | Implemented | Retain as read-only market-data boundary |
| Closed-candle and no-look-ahead gates | Implemented and tested | Mandatory before every live decision |
| Wyckoff + SMC decision pipeline | Implemented | Continue deterministic validation |
| Risk engine and Spot Execution Guard | Implemented | Become mandatory pre-order authorization |
| Paper portfolio and persistence | Implemented | Extend with exchange reconciliation |
| Real Binance Spot order adapter | Not implemented | Add behind a disabled-by-default feature flag |
| Agentic Sub-account isolation | Not configured by this repo | Use as the live account boundary |
| Withdrawals, Margin, and Futures | Outside V1 | Keep disabled for the Spot agent |

## Why an Agentic Sub-account

A dedicated Agentic Sub-account can isolate the agent from the main account and
limit the capital exposed to an execution defect. The MCP/API connection should
be scoped to that sub-account, not the parent account.

Sub-account isolation limits the blast radius, but it is not a complete risk
engine. It does not by itself prevent duplicate orders, invalid quantities,
partial-fill mistakes, stale decisions, or repeated buys after a retry. Those
controls remain the responsibility of the agent and execution adapter.

## Proposed execution boundary

```text
Main Binance account
→ Explicit, capped funding
→ Agentic Sub-account
→ Binance MCP connection with minimum permissions
→ V1 analysis pipeline
→ Risk authorization
→ Spot Execution Guard
→ Manual confirmation during rollout
→ Idempotent Spot order adapter
→ Fill reconciliation
→ Position checkpoint
```

The live adapter must fail closed. Missing state, stale data, malformed exchange
responses, or uncertain order status must block new exposure.

## Mandatory controls before live activation

### Account and permission controls

- Use a dedicated Agentic Sub-account with a deliberately capped balance.
- Scope credentials to that sub-account.
- Permit Spot trading only.
- Disable withdrawals, universal transfers, Margin, and Futures.
- Never store credentials in source control, fixtures, artifacts, or CI logs.
- Keep `LIVE_TRADING_ENABLED=false` by default.

### Order safety

- Validate Binance symbol filters, minimum notional, step size, and quantity
  precision immediately before submission.
- Use a unique client order ID derived from the approved decision.
- Make retries idempotent so a timeout cannot create a duplicate order.
- Re-query uncertain orders before attempting another submission.
- Reconcile partial fills, fees, cancellations, and final average fill price.
- Reject any order whose decision candle is no longer current.

### Portfolio controls

- Cap quote value per order and aggregate portfolio exposure.
- Limit open positions and entries per symbol.
- Add daily loss, consecutive-error, and stale-checkpoint circuit breakers.
- Persist the approved thesis, risk decision, execution intent, and exchange
  response as one auditable lifecycle.
- Provide an emergency kill switch that blocks all new orders.

## Staged rollout

| Stage | Execution mode | Required evidence |
| --- | --- | --- |
| 0 | Deterministic replay | No-look-ahead and prefix-invariance tests |
| 1 | Paper runtime | Stable checkpoints and conservative fill simulation |
| 2 | Sub-account read-only | Balance, permissions, filters, and order-state reads |
| 3 | Manual-confirm Spot | Tiny capped orders with reconciliation and kill switch |
| 4 | Capped automation | Strict exposure limits and continuous monitoring |
| 5 | Monitored lifecycle | Entry, management, distribution detection, and exit |

Promotion between stages requires regression tests, an incident-free observation
period, and an explicit owner decision. No stage is promoted merely to increase
trading frequency.

## Definition of live-ready

The project may describe live execution as implemented only when all of the
following are true:

1. The order adapter exists and is disabled by default.
2. Duplicate-order and uncertain-timeout tests pass.
3. Exchange filters and precision are validated.
4. Partial fills and reconciliation are tested.
5. Circuit breakers and the kill switch are tested.
6. The connection is scoped to a capped Spot-only sub-account.
7. CI cannot access trading credentials.
8. An explicit activation procedure and rollback procedure are documented.

Until then, the accurate product statement is:

> V1 is paper-only for validated demonstration, with a guarded architecture
> designed to extend to automated Binance Spot execution.

## V1 non-goals

The hackathon build will not:

- submit real Spot orders;
- create Futures or Margin positions;
- transfer or withdraw funds;
- expose account credentials;
- weaken the Spot Execution Guard to manufacture a demo trade.

This boundary preserves the credibility of the current evidence while making
the path to a production Spot swing agent concrete and reviewable.
