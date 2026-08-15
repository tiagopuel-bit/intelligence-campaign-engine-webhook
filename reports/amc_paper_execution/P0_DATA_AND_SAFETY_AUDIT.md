# AMC Paper Execution — P0 Data and Safety Audit

## 1. Field inventory (observed, no fake data added)

### Positions (manual log, source of truth)
`GET /positions`, `GET /positions/<id>`
- `symbol`, `direction` (LONG/SHORT), `status` (OPEN/CLOSED), `opened_at`,
  `closed_at`, `origin_timeframe`, `origin_event`, `notes`.
- `instruments[]`: `instrument_type` (SHARE/CALL/PUT), `strike`, `expiration`,
  `quantity`, `entry_price`, `entry_time`, `exit_price`, `exit_time`,
  `status` (OPEN/CLOSED/ROLLED), `rolled_from_id`, `rolled_to_id`.
- **Classification:** live (human-entered), frozen-at-entry.

### Valuation
`GET /positions/<id>/valuation`
- `underlying`: `{symbol, current, prev}` — `current` is the live webhook close,
  `prev` is the Massive daily close.
- `stock`: `shares, avg_cost, current_price, prev_price, market_value,
  cost_basis, first_entry, today_pnl, today_return_pct, total_pnl,
  total_return_pct, leg_ids`.
- `options[]`: `contract{type,strike,expiration}, contracts, avg_cost,
  current_price, prev_price, market_value, cost_basis, first_entry, breakeven,
  itm, today_pnl, today_return_pct, total_pnl, total_return_pct, leg_ids`.
- **Classification:** `underlying.current` live; option `current_price` delayed
  (Massive daily close); `avg_cost`/`first_entry` frozen manual entries.

### DNA state
`GET /state_all/<symbol>`
- `symbol, timeframe, phase, health, confidence, momentum, recent_event,
  exhaustion_warning, reload_quality, htf_phase, campaign_alignment,
  last_fail_type, close, bar_time, rsi, ema21_distance_atr, session,
  active_trade, active_entry, active_stop, active_target, active_trade_source,
  active_trade_open_pct, source, next_event_after_signal, signal_event,
  signal_time, signal_bar_extension_label`.
- **Classification:** `source=live_webhook` live; `source=backfill_replay`
  reconstructed (retain provenance).

### OHLC / option bars / chain
- `GET /ohlc/<symbol>/<tf>` → Massive aggregate bars `{t,o,h,l,c,v,vw,n}`.
- `GET /options/ohlc/<ticker>/<tf>` → Massive option bars.
- `GET /options/chain/<symbol>` → contracts (cached 1h).
- **Classification:** delayed (~1 day) on the free plan.

### SEC / news
- `GET /filings/<symbol>` → normalized filings (PUBLIC_ACCEPTANCE acceptance
  clock; OPERATIONAL_SEEN only when a real poller ran).
- `GET /news/<symbol>` → Yahoo + Google headlines (cached 5 min).

## 2. Live / cached / reconstructed / delayed / absent

| class | fields |
|---|---|
| live | manual positions, live-webhook underlying close, live-webhook DNA state |
| delayed | Massive OHLC and option bars, option `current_price` (~1 day) |
| reconstructed | `backfill_replay` state rows |
| cached | options chain (1h), news (5 min) |
| absent | bid/ask, spread, Greeks, IV, OI, real-time quotes, broker execution, transaction-level option fills |

Absent fields are never invented. The fill model uses the latest bar close and
reports `UNSCORABLE_EXECUTION_DATA` when no price reference exists.

## 3. Safety boundaries verified

- No broker connection, credentials, or routing-capable endpoint exists.
- No abstract adapter whose default could become live.
- `AUTO_IF_VERY_HIGH_PAPER` is the only auto mode; the current Options DNA
  entry finding is excluded from `VERY_HIGH`.
- Global and per-position kill switches win over any pending timer.
- Proposals are append-only; the event ledger is authoritative.
- No future-outcome access during proposal generation (policy uses causal
  fields only; tests assert this).

## 4. Goal contract — P0 PASSED

The user approved the provisional goal template at 2026-08-14. The contract is
now `FROZEN_APPROVED_V1` in `paper_execution/experiment_goal_v1.json`:

- `starting_portfolio.cash` = **$100.00**;
- all 18 provisional values approved (max drawdown 25%, daily paper loss 5%,
  3 auto-executions/day, shutdown after 3 failed revalidations, min sample 30
  proposals / 10 auto-executions, allocation caps 70/50/25/15%, four benchmarks,
  deposits allowed-and-tracked-separately, primary tier Diamond, end
  January 31 2027 market close);
- `chronology.start` = the first verified AMC 1-minute heartbeat after activation
  and the atomic portfolio snapshot.

`pending_confirmations` is empty. P0 passes; P1 (engine + persistence) is not
started and requires separate authorization.

## 5. Live-price freshness and watchlist

The Massive feed is delayed (~1 day), not real-time; the underlying heartbeat
and any option-quote relay are separate future tasks (no Pine change in P0).
Option premium freshness is not solved by the underlying heartbeat, so stale
option cases resolve to `BLOCKED_STALE_OPTION_QUOTE` or
`UNSCORABLE_EXECUTION_DATA`. A bounded option-contract watchlist (HELD /
ENTRY_CANDIDATE / ROLL_CANDIDATE / EXIT_WATCH) is specified, not streamed, with
per-contract data-age/session status and the four freshness labels
(`LIVE_CONTRACT_BAR`, `DELAYED_PROVIDER_BAR`, `STALE_CONTRACT_DATA`,
`NO_LIVE_CONTRACT_SOURCE`).
