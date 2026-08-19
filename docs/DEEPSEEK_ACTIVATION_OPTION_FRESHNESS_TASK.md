# Task packet — option heartbeat freshness gate is blocking activation on real, correctly-configured data

**Requested by:** Tiago, 2026-08-18/19. **For:** DeepSeek. **Priority: needs
to land before tomorrow's market open** — this is the last confirmed blocker
keeping AMC's paper experiment from activating.

## Confirmed root cause

`activate_if_ready()` in `paper_execution/activation.py` requires every open
option instrument to have a heartbeat inside `MAX_AGE_MS = 2 * 60 * 1000`
(2 minutes) — same threshold used for the underlying. The underlying trades
continuously so 2 minutes is fine there. Options do not.

**Confirmed today (2026-08-18, all 4 alerts verified correctly configured —
`kind:"OPTION_HEARTBEAT"`, correct `position_ref`/`instrument_ref`, webhook
200s, real trade-driven prints) — actual gaps between real prints on each
contract:**
- Dec18 (instrument_ref 8): 08:30 → 09:11 (41 min) → 11:19 (128 min)
- Jan2027 (instrument_ref 6): 09:53 → 09:57 → 10:59 (62 min) → 12:10 → 12:11
- Aug21 (instrument_ref 10): 08:59 → 09:26 → 09:47 → 10:59 (72 min) → 11:48

These are deep-ITM, long-dated $1.5 strike calls on a ~$2.35 stock — real
trades only print every 20-130 minutes on TradingView's delayed OPRA feed.
A 2-minute activation freshness requirement can essentially never be
simultaneously satisfied across all 4 legs, no matter how correctly the
alerts are configured. This is a threshold/design bug, not a setup bug —
alert config was independently verified correct against real TradingView
delivery logs before escalating this.

**Supporting precedent:** `paper_execution/cloud_state.py` (which drives
*ongoing* valuation after activation) already reads "most recent
`option_heartbeats`/`underlying_heartbeats` row" with **no hard freshness
cutoff at all** — the ongoing system already tolerates this kind of
staleness by design. Only the one-time `activate_if_ready` gate enforces the
mismatched 2-minute rule.

## Fix

Split the freshness requirement: keep `MAX_AGE_MS` (2 min) for the
underlying heartbeat in `activate_if_ready()` (`activation.py:53`) — that's
correct and working. For the option heartbeat check (`activation.py:79`),
replace the 2-minute cutoff with something that reflects real option print
cadence instead of the underlying's. Two implementation options — evaluate
and recommend one, don't just pick silently:

1. **Same-session freshness**: require the option heartbeat's `session`
   field (already sent in the payload) to match the current session
   (e.g. today's date + RTH/PRE/POST), rather than an absolute minute
   cutoff. Bounds staleness to "real data from today," consistent with
   Principle 011 (silence over fabrication) — a 90-minute-old real print
   from today is real information, not fabricated.
2. **Wide fixed window**: raise the option-specific max age to something
   like 3-4 hours (covers observed gaps with margin, still bounded).
   Simpler, but the exact number is an arbitrary guess unless backed by a
   wider sample of real print gaps across more than one day.

Recommend option 1 unless there's a concrete reason it's harder to
implement correctly — it doesn't require guessing a number and matches the
project's existing "verify real data, don't invent thresholds" discipline.
Whichever is chosen, add a short comment explaining *why* options get a
different rule than the underlying (so a future editor doesn't "fix" it
back to matching).

## Grounded validation

1. Add/update tests in whatever test file covers `activate_if_ready`
   (check `tests/` for existing activation tests first) — at minimum:
   underlying fresh + all 4 options within the old 2-min window still
   activates (regression); underlying fresh + options real-but-stale
   (e.g. 90 min old, same session) now activates under the new rule;
   options from a *prior* session/day still correctly block.
2. Full suite green, `git diff --check` clean.
3. Report back the exact before/after: re-run (or simulate) the activation
   check against the real gap data above and confirm it now passes.

## Boundary

- Only touch the option-branch of `activate_if_ready()`
  (`activation.py:69-87`). Do not change the underlying's `MAX_AGE_MS`
  check, do not touch `join_symbol_if_ready()`'s underlying-only check
  (that one's fine as-is), do not touch `cloud_state.py` (already correct).
- No deploy/commit/push — hand back for review like every task.
- Log a summary to `docs/PAPER_TRADE_DESK_LOG.md` when done, including the
  exact rule chosen and why.

## What to report back

Which of the two options was implemented (or a third, if a better one
occurred to you — explain the tradeoff), the diff, new/updated tests, and
confirmation the real gap data above would now pass the gate.
