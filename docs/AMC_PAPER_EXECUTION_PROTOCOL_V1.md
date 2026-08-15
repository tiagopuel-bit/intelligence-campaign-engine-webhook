# AMC Paper Execution Experiment — Protocol v1 (P0)

**Status:** design + contract freeze. `PAPER_ONLY`. No timers, APIs, scheduler,
UI, broker connection, order transmission, or deployment are implemented at P0.

## 1. Boundary

- This stage is `PAPER_ONLY`. No broker connection, no live or paper broker
  credentials, no endpoint capable of routing to a broker, no abstract adapter
  whose default could become live.
- Pine, TradingView alerts, DNA signal definitions and webhook ingestion are
  not modified.
- The Options DNA entry result (`HISTORICAL_RESEARCH_FINDING_NEEDS_EXTERNAL_REPLICATION`)
  must not power `VERY_HIGH`, production wording, or an order proposal.
- Position-management calibration (`BLOCKED_INSUFFICIENT_REPLAY_COVERAGE`) is
  not used; any initial paper decision policy is `EXPERIMENTAL_HEURISTIC_V1`,
  pre-registered and causal, not fitted.

## 2. Goal-establishment gate

P0 does not pass, and the experiment cannot activate, until the user approves a
versioned goal contract with the following **user-supplied** values (never
invented by the engine):

| field | supplied by |
|---|---|
| exact start/end timestamps (America/Los_Angeles) | user |
| immutable starting cash + starting holdings (valued under a declared method) | user (holdings may be snapshotted from the live beta portfolio) |
| primary January 2027 target portfolio value | user |
| secondary return target (derived from the frozen starting value) | derived |
| maximum tolerated portfolio drawdown | user |
| maximum AMC exposure and per option/expiry exposure | user |
| deposit/withdrawal policy (prohibited vs tracked separately) | user |
| allowed action types | user (default: hold, add, open, partial reduce, close, roll) |
| benchmark portfolio and success criteria | user |
| minimum observation count before judging auto-execution | user |
| safety goals (max daily paper loss, orders/day, consecutive failed proposals) | user |

The approved contract is written to `paper_execution/experiment_goal_v1.json`,
hashed, and never silently edited; later changes create a new version and
preserve the original. **Until the user supplies these values, the goal contract
is `PENDING_USER_INPUT` and no execution is possible.**

### User-defined January 2027 milestones (supplied)

Measured against **Total Portfolio Value** (never AMC-only value, option
premium, realized P&L, or cumulative trade proceeds):

| tier | target total portfolio value |
|---|---|
| Silver | $6,000 |
| Gold | $8,000 |
| Premium | $10,000 |
| Diamond | $15,000 |

`Diamond` is recorded as `$15,000` from the user's shorthand "15$" and is
**flagged for confirmation** before the goal JSON freezes. Tiers may not change
execution eligibility, loosen risk limits, or encourage extra trades as the
deadline approaches.

### Strategic AMC allocation floor (supplied)

While the AMC campaign remains objectively intact and no loss-of-confidence
process has completed, target at least **30% of Total Portfolio Value** in
combined AMC exposure (marked market value of AMC shares + options). This is a
strategic floor, not permission to force a trade. If the portfolio falls below
it from market movement, DNA reports the gap and evaluates an action — it does
not auto-buy to restore the percentage.

The floor may be suspended only when all four hold: (1) the versioned
campaign-break definition is satisfied, (2) a structured `CONFIDENCE_WITHDRAWN`
decision is recorded with evidence, (3) the user records agreement, and (4) any
reduction passes the normal proposal workflow. DNA damage without user agreement
→ `DECISION_REQUIRED` and no unattended exposure-increasing orders. User
confidence loss without DNA confirmation → record the disagreement and require
manual approval. Cash is a valid allocation, and the goal contract must still
define maximum AMC allocation and an option-risk cap (the floor does not replace
those upper bounds).

## 3. Operating modes

Every proposal carries one of: `ADVISORY_ONLY`, `APPROVAL_REQUIRED`,
`AUTO_IF_VERY_HIGH_PAPER` (the only auto mode), `PROTECTION_ONLY_PAPER`.

Proposal lifecycle (append-only event ledger is authoritative):

```text
DRAFT -> PENDING_APPROVAL -> APPROVED | REJECTED | CANCELLED | EXPIRED
PENDING_APPROVAL -> REVALIDATING -> PAPER_EXECUTED | CANCELLED_REVALIDATION
APPROVED -> REVALIDATING -> PAPER_EXECUTED | CANCELLED_REVALIDATION
PAPER_EXECUTED -> PARTIALLY_FILLED | FILLED | UNFILLED | EXPIRED_UNFILLED
```

## 4. Ten-minute rule

1. On proposal creation, alert immediately and expose `Approve`, `Modify`,
   `Reject`, `Cancel auto-execution`.
2. Default maximum approval window is 10 minutes.
3. User approval may trigger immediate revalidation.
4. No response does not approve the stale proposal.
5. At the deadline, revalidate atomically with current causal data.
6. Submit to the paper fill simulator only if every gate still passes.
7. Otherwise record the exact cancellation reason.

A disabled global or per-position switch wins over any pending timer.

## 5. `VERY_HIGH` evidence contract

`VERY_HIGH` requires all four independent roots, never a numeric confidence
field:

1. **Underlying DNA** — named timeframe agreement, event recency, no
   disqualifying FAIL/pressure conflict.
2. **Contract response** — real active prints and causal premium behavior; no
   unchanged-print inference, no missing bar as evidence.
3. **Execution quality** — fresh input, deterministic bar-close price reference,
   no stale/ambiguous quote.
4. **Portfolio risk** — position exists for reductions; exposure, size, daily
   limit, duplicate and conflict checks pass.

Catalyst/SEC risk is an independent veto or policy modifier, never folded into a
score. Every proposal stores its named roots, raw causal fields, missing
evidence, contradictions/vetoes, policy version + hash, type and
time-sensitivity, and the exact cancel/change condition.

## 6. Fill and censoring model

Bid/ask is absent. The paper fill model is the latest available option aggregate
bar close at revalidation time — conservative and declared (delayed bar-close;
no midpoint, spread, fee or slippage). Missing price → `UNSCORABLE_EXECUTION_DATA`.
Rolls are two-leg decisions; both legs must have a price reference.

## 7. Schema

`paper_execution/schema_v1.sql` defines experiments (goal contract), immutable
starting holdings, proposals, evidence snapshots, append-only lifecycle events,
paper orders/fills, user decisions, outcome snapshots, daily reports and
global/per-position auto switches, with idempotency keys and append-only
transitions.

## 8. Alert delivery

Alert delivery is a boundary only. Reuse an existing verified channel if one
exists; do not add an unapproved external messaging service.

## 9. Data availability (summary of the P0 audit)

- **Live:** manual positions, live-webhook underlying close and DNA state.
- **Delayed (~1 day):** Massive OHLC and option bars, option `current_price`.
- **Reconstructed:** `backfill_replay` state rows (provenance retained).
- **Cached:** options chain (1h), news (5 min).
- **Absent (never invented):** bid/ask, spread, Greeks, IV, OI, real-time quotes,
  broker execution, transaction-level option fills.

## 10. Program North Star

The January 2027 Portfolio Challenge is the primary operating framework. Two
explicit tracks are preserved: `CHALLENGE_OPERATIONS` (frozen policy versions,
timestamped paper decisions, scored without hindsight edits) and
`RESEARCH_DEVELOPMENT` (new hypotheses on separate historical/discovery data,
entering Challenge operations only through a versioned promotion checkpoint). A
rule is never refit to a Challenge loss and then re-scored as if the revised
rule had been active; policy updates begin a new evaluation segment. The
milestone target never overrides evidence or safety.

## 11. Live-price freshness gate

The Massive free-plan aggregate feed is not a real-time execution feed. No
proposal may be described as real-time or `VERY_HIGH` merely because a 1-minute
TradingView alert exists. Before paper activation, a separate underlying
heartbeat must be verified (smallest separate task + acceptance test; no Pine
change inside P0). Underlying heartbeat does not solve option-premium freshness:
a premium-based proposal is ineligible unless the contract has a fresh causal
quote/bar source, and the free Massive option close is labelled delayed. Stale
option cases resolve to `BLOCKED_STALE_OPTION_QUOTE` or
`UNSCORABLE_EXECUTION_DATA`; no live premium is inferred from the underlying
move. No real option order path is enabled until bid/ask, quote timestamp,
spread and revalidation are verified.

## 12. Bounded option-contract watchlist

Do not stream the full chain. Maintain a small rotating watchlist of contracts
whose live behavior could change a decision: `HELD`, `ENTRY_CANDIDATE`,
`ROLL_CANDIDATE`, `EXIT_WATCH`. Provisional capacity is all held contracts plus
no more than three entry and two roll candidates. Each watched contract carries
ticker/type/strike/expiration, watch reason and linked position/proposal,
created/last-needed/expires timestamps, latest causal bar timestamp and source,
data age and session, active/paused/stale/error status, and automatic retirement.
The dashboard/daily report distinguishes `LIVE_CONTRACT_BAR`,
`DELAYED_PROVIDER_BAR`, `STALE_CONTRACT_DATA`, and `NO_LIVE_CONTRACT_SOURCE`, and
never silently falls back from a live contract bar to a delayed daily close in a
time-sensitive proposal.
