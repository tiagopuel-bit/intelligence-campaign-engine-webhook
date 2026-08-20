# Task packet — wire the Unified Relay's batched events into the real `alerts` table

**Requested by:** Tiago, 2026-08-20. **For:** DeepSeek. Receiver-side half of
a Pine script consolidation — I (Claude) wrote the new Pine script
(`pine_research/DNA_UNIFIED_RELAY_V1.pine`); this task is only the receiver
changes needed to handle its payload correctly.

## Why this exists

TradingView's alert cap (~100 technical alerts, `docs/TRADINGVIEW_ALERT_CAPACITY_PLAN.md`)
makes 8-10 per-timeframe alerts × 7+ tracked assets unworkable — confirmed
tonight when Tiago deleted all of AMC's per-timeframe native alerts along
with the other 6 assets', keeping only the price-heartbeat relay. Right now
**zero assets have live DNA event generation** — only price ticks.

The fix: one Pine script, one alert per asset
(`DNA_UNIFIED_RELAY_V1.pine`), sending ONE payload per 1m anchor-bar close
that carries both the underlying heartbeat AND a batched array of whichever
tracked timeframes' bars just closed, each with its own event/phase (via
`request.security()`, same technique as the retired `DNA_MTF_RELAY_V1.pine`).
Option-heartbeat mode is unchanged (options don't get DNA classification,
only price — untouched, don't modify that branch).

**Known, explicitly-flagged gap, do not silently paper over it:** the
event classification in this script (`f_dnaPhase()`) is a self-contained,
single-bar, price-action-only approximation of the real production DNA
cascade — not the stateful `DNA_v12.6.21.pine` (no `campaignHealth`
persistence, no Trade Box, no multi-factor evidence gating). It was never
validated against native output (`scripts/compare_mtf_relay.py` never
completed a real comparison run). Every event this script produces must be
tagged with a distinct `source` so it is never confused with a
fully-validated native alert or fabricated as equivalent — same discipline
as the `backfill_replay` fix (`docs/PAPER_TRADE_DESK_LOG.md`, "recent_event
surfacing backfill reconstructions").

## The payload shape

```json
{
  "kind": "UNDERLYING_HEARTBEAT",
  "symbol": "AMC",
  "ticker": "BATS:AMC",
  "timeframe": "1",
  "time": 1787167800000,
  "close": 2.35,
  "session": "RTH",
  "events": [
    {"timeframe": "60", "event": "EXPANSION", "time": 1787167800000, "close": 2.35, "phase": "EXPANSION"},
    {"timeframe": "240", "event": "WAIT", "time": ..., "close": ..., "phase": "WAIT"}
  ]
}
```

`events` is present only when at least one tracked timeframe's bar closed
on this anchor tick; may be entirely absent on most 1m ticks. Option-mode
payloads are unchanged (no `events` key ever).

## What to build

1. In `/webhook` (`webhook_receiver.py:575`), `_record_price_heartbeat()`
   currently returns early on any `UNDERLYING_HEARTBEAT`/`OPTION_HEARTBEAT`
   payload (`webhook_receiver.py:590-593`), before the native/relay event
   insertion logic ever runs. Extend the underlying-heartbeat branch of
   `_record_price_heartbeat()` (or the caller, your call which is
   cleaner) so that after recording the heartbeat row, it also iterates
   `payload.get("events") or []` and inserts each fragment into the real
   `alerts` table via `_insert_alert()` — same call used for native
   payloads, NOT `alerts_relay` (that table is documented as never
   feeding the native DNA read; this new relay is meant to actually feed
   it, so it must go into `alerts`).
2. Every row inserted this way must get `source='live_relay'` (a new,
   distinct value — not `'live_webhook'`, not `'backfill_replay'`). This
   requires `_insert_alert()` to accept an explicit source override
   (right now it always relies on the schema `DEFAULT 'live_webhook'`) —
   add an optional `source` parameter, default `'live_webhook'` so every
   existing call site (native payloads, the old alerts_relay path) is
   unaffected unless it explicitly passes something else.
3. Update the three places filtering on `source='live_webhook'` for
   "true last real event" (`webhook_receiver.py:_last_real_event`,
   `webhook_receiver.py:_dna_context`, `bracket_suggestions.load_campaign_states`)
   to accept **either** `'live_webhook'` **or** `'live_relay'` — both are
   genuinely live, neither is fabricated or reconstructed; only
   `backfill_replay` stays excluded. Use an explicit tuple/IN clause, not
   a bare `!=` exclusion (fail-closed: an unrecognized future source value
   should not silently count as live).
4. The existing `relay_events = payload.get("events") if payload.get("relay")` /
   `alerts_relay` path (`webhook_receiver.py:598-614`, triggered by
   `payload.get("relay")` being truthy) is unrelated to this — that was
   the old MTF-relay-only parity-shadow payload shape (`{"relay":true,...}`,
   no `kind`). Leave it untouched; the new payload never sets `"relay":true`.
5. Somewhere visible (dashboard, `/state` response, wherever `source` is
   already surfaced per `webhook_receiver.py:969-985`'s live/backfill
   counter) make `live_relay` distinguishable from `live_webhook` in any
   existing reporting that breaks down alert provenance, so nobody looking
   at aggregate counts mistakes provisional relay events for validated
   native ones.

## Grounded validation

- A payload with `events` populated creates rows in `alerts` (not
  `alerts_relay`) with `source='live_relay'`, retrievable via
  `_last_real_event`/`/state_all` exactly like a native event would be.
- A payload with `events` absent (most 1m ticks) only records the
  heartbeat, no `alerts` rows created.
- `_last_real_event` picks up a `live_relay` row when it's the most
  recent, but a `backfill_replay` row never outranks anything, and an
  unrecognized/未来 source value is excluded too (test this explicitly).
- Existing native-alert and old `alerts_relay` behavior unchanged —
  regression-test the existing suites for both.
- Full suite green, `git diff --check` clean.

## Boundary

- Don't touch the option-heartbeat branch, don't touch the old
  `alerts_relay`/`"relay":true` path, don't touch `_last_real_event`'s
  underlying-heartbeat logic (`activation.py`, unrelated system).
- Don't attempt to "fix" or improve `f_dnaPhase()`'s classification logic
  — that's a Pine-side, separately-scoped validation effort, not part of
  this task.
- No deploy/commit/push — hand back for review like every task.
- Log a summary to `docs/PAPER_TRADE_DESK_LOG.md` when done.

## What to report back

The diff, new/updated tests, and confirmation of the four validation
points above with concrete before/after query results (not a description
of the method).
