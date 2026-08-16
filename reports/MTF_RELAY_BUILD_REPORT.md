# MTF Webhook Relay — Build Report (2026-08-16)

Follows `docs/TRADINGVIEW_ALERT_CAPACITY_PLAN.md` ("Preferred engineering
solution") and `docs/DEEPSEEK_MTF_RELAY_BUILD_TASK.md`. Build authorized; relay
runs **alongside** native alerts for parity comparison only.

## What was built

1. **`pine_research/DNA_MTF_RELAY_V1.pine`** — the relay script source.
2. **`webhook_receiver.py`** — ingestion accepts relay batches and stores them
   in a separate `alerts_relay` table.
3. **`mtf_relay_compare.py` + `scripts/compare_mtf_relay.py`** — the parity
   comparison harness.

## 1. Pine relay — and exactly what Tiago must do in TradingView

The script runs on the **1m** anchor, pulls each tracked timeframe
(`3,5,15,30,60,120,180,240,D,W`) via `request.security()` with
`lookahead_off`, and emits **one batched `alert()` per anchor-bar close** only
when at least one tracked bar actually closed (its security bar time advanced).
Payload carries, per event: source `timeframe`, `event`, `time`, `close`, and
`phase` — the four identity fields plus price the receiver depends on.

**Manual TradingView steps (Tiago only — DS cannot touch the TV UI):**
1. Add the script to the asset's **1m** chart.
2. Create **one** Alert on it (condition = "This indicator", the `alert()`
   trigger), Webhook URL = the existing `/webhook` URL.
3. Leave the alert **message empty** — the script's `alert()` builds the JSON.
4. Recreate the alert after **any** edit to the script (alerts snapshot the
   script at creation time).
5. Do **not** disable the asset's native per-timeframe alerts.

**Storm-safety:** at most one alert per anchor-bar close, gated on a real bar
close — well under the >15-per-3-minutes kill threshold.

**Honest v1 caveat (parity gap):** `f_dnaEvent()` is a self-contained,
`var`-free price-action port of the production phase *vocabulary*. It is **not**
a byte-for-byte port of the stateful production indicator (`campaignHealth`
persistence, `pendingActive`, `resolvedAddEvent`, Trade Box, the full
`currentBarEvent` cascade). Those stateful parts cannot be reproduced reliably
inside `request.security()` and are the known gap to tune on-platform — exactly
what the comparison harness exists to measure.

## 2. webhook_receiver.py — how relay is distinguished from native

The `/webhook` route now detects a relay payload by the `"relay": true` marker
plus an `"events"` list. Relay rows are written to a **separate
`alerts_relay` table** (same columns as `alerts`), so they never feed the
native DNA read — `/state_all`, `/state`, `/history` and `cloud_state` keep
reading `alerts` only. Native payloads are unchanged and still land in
`alerts`.

- `_insert_alert(conn, table, symbol, timeframe, event, fields, now)` — shared
  single-row insert used by both paths.
- Relay batch: each event is attributed to its own source `timeframe` +
  `bar_time`, matching native semantics exactly.

## 3. Comparison harness

`scripts/compare_mtf_relay.py` reads `alerts` (native, ground truth) vs
`alerts_relay` (relay), keys each by `(symbol, timeframe, bar_time)`, and
reports the five plan-doc comparison points: event type/priority (exact string
match — priority is encoded in `currentBarEvent`), bar-time (signal/decision
timestamp) via the key match, price + `phase` field parity (with a configurable
close tolerance), dedup/bar-close behavior (flags relay duplicate bars), and
session boundary (session tag match).

**Current parity result:** `native_rows=65, relay_rows=0, missed=65` — expected,
because the relay has **not** been activated on TradingView yet. The harness is
ready; parity numbers will populate the moment Tiago switches the relay alert on
and both streams accumulate.

## Verification

- Full suite: **410 tests passing** (`git diff --check` clean). Added 4 relay
  ingestion tests + 6 harness tests.
- Native webhook tests (88) unchanged and passing — the native path is
  untouched.

## Boundaries honored

- No production TradingView alert modified/disabled; no Pine production file
  (`DNA_v12.6.2x.pine`) touched.
- `paper_execution/` untouched (git-clean).
- No alert-content/threshold change for existing assets; the relay reproduces
  the vocabulary, not a new DNA logic.
- Alert-storm limit designed around explicitly (one alert per bar close).
- No deploy/commit/push — handed back for review.
