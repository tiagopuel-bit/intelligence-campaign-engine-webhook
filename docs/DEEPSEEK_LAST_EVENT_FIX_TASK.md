# Task packet — fix "last real event" tracking + investigate a possible ingestion gap

**Requested by:** Tiago, 2026-08-18. **For:** DeepSeek. Two related but
distinct problems, both confirmed against real data on U tonight — fix
both before any "propagation"/`dormant`-state work builds on top of this
data.

## Problem 1 — `recent_event` only reflects the single latest bar, not the true last event

**Confirmed root cause:** `webhook_receiver.py:678`,
`"recent_event": latest["bar_event"]` — this is the *latest bar's own*
event field, not a lookup for the most recent real (non-null) named event.
Since most bars are plain `WAIT` with no event, `recent_event` reads blank
almost all the time, even when a real event (FAIL, MANAGE, etc.) fired
several bars ago and is still the operative context.

**Fix:** derive a genuine "last real event + how long ago" per
`(symbol, timeframe)`. Two implementation options, evaluate and pick one:
1. A backward query — scan the `alerts` table for the most recent row
   with a non-null `bar_event`, at read time (`/state_all`, dashboard
   table, `bracket_suggestions.py`'s `_to_campaign_state` — note this file
   has the *same* bug: `recent_event = (latest["bar_event"] or "").upper()`,
   fix both call sites).
2. A maintained "sticky" column, updated only when a genuine event fires
   and never cleared by a plain WAIT bar — cheaper to read, more moving
   parts to keep correct.
State the tradeoff and recommend one. Whichever is chosen, surface both
the event name **and** its real elapsed time (reuse `age()`-style
formatting) everywhere `recent_event` is currently displayed or consumed
— the dashboard's "Last event" column, the "Updated" column's relationship
to it, and `bracket_suggestions.py`'s support/resistance derivation (which
depends on `recent_event` being the real last event, not the latest bar's
often-empty one — this may materially change what
`recent_support_price`/`recent_resistance_price` actually pick up).

## Problem 2 — possible real ingestion gap, not just a display bug

**Confirmed discrepancies (real, from tonight's live check on U):**
- 30m: Tiago's own chart read shows the last meaningful signal (MANAGE)
  ~4 days ago. The dashboard's "Updated" column — which reflects the
  *latest bar's own timestamp*, unrelated to `recent_event` — showed ~8
  days ago. A bar timestamped **older** than a real event that fired
  since is a contradiction: either alerts stopped arriving for a stretch
  (a real ingestion gap), or the timestamp being read is wrong.
- 1H: real FAIL TEST → FAIL on July 30 (13 days ago per chart). Dashboard
  "Updated" showed ~7 days ago — also doesn't reconcile against real
  events in between.

**Investigate, don't assume:** query `alerts` directly for U on `30` and
`60` over the last ~14 days, real `bar_time`/`received_at` gaps included.
Report: is there a genuine multi-day stretch with zero rows (an actual
missing-alert gap — check TradingView alert config / webhook delivery for
that stretch), or does the data exist but get misread by the current
query logic (in which case Problem 1's fix likely also resolves this)?
Don't fix blindly — these are two different root causes with different
remedies, and conflating them would hide whichever one turns out to be
real.

## Grounded validation

Once fixed, re-check the exact three data points above (30m MANAGE ~4d
ago, 1H FAIL TEST→FAIL July 30/~13d ago) against the corrected output and
confirm they now read correctly. This is the actual test of whether the
fix worked — not a description of the change.

## Boundary

- Read-only investigation for Problem 2's gap question; only write code
  for Problem 1's fix (and Problem 2's fix too, if it turns out to be the
  same root cause).
- Advisory/dashboard-only — this doesn't touch `paper_execution`'s
  evidence roots directly, though `bracket_suggestions.py`'s support/
  resistance derivation is downstream of this and should be re-verified
  against the fix (does not require re-authorizing that spec, just
  confirming its inputs are now correct).
- Full suite + `git diff --check` clean.
- No deploy/commit/push — hand back for review, same as every task.
- Log a summary to `docs/PAPER_TRADE_DESK_LOG.md` when done.

## What to report back

Per problem: what was found (real gap vs. display bug, or both), what
changed (file/line), new/updated tests, and the three real data points
re-verified against the fix with actual numbers — not a description of
the method.
