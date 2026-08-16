# Task packet — TSLA historical backfill (full ladder)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek.

## Why

Tiago just added TradingView alerts for TSLA covering 3m through Daily.
Live data will trickle in as each timeframe's bars close (Daily could take
until tomorrow's close, 4H/3H hours), but `/assets` confirms TSLA currently
has only `timeframe_count: 2` (5m, 15m) and zero backfill coverage — compare
to AMC/GME/PYPL/RBLX/SPY/VALE/U, which all have 9-10 timeframes with deep
`backfill_replay` history already.

Concrete motivating case: Tiago spotted a real setup on TSLA today (~90-day
quiet on higher timeframes, then 5m/15m firing `RELOAD`/`STRONG START` with
health 99-100%, clean run since Aug 12) by eyeballing six TradingView panels
by hand. Our dashboard's "warming up" indicator (added 2026-08-15,
`ui/dna_dashboard.html`) requires the campaign tier (180/240) to have data —
it's structurally blind to this exact pattern for TSLA until backfill exists.

## What to do

Same pipeline already used for the other 7 assets — this repo already has
the tooling, this is a scope extension, not new engineering:

1. Run the existing backfill (`webhook/backfill.py` / `POST /backfill`) for
   `TSLA`, full ladder (3m, 5m, 15m, 30m, 1H, 2H, 3H, 4H, D, W — whatever
   the existing pipeline's standard ladder is, match it exactly).
2. Confirm the no-collision rule holds (backfilled rows end where live
   coverage begins, live rows always win on overlap) — same rule the
   original backfill task packet specified, don't re-derive it.
3. Verify via real `/assets` and `/state_all/TSLA` queries post-backfill —
   report actual row counts per timeframe/source, not a description of the
   pipeline running.

## Boundaries

- No changes to the backfill pipeline itself unless something is actually
  broken — this should be a straightforward re-run scoped to a new symbol.
- No changes to Pine, live webhook ingestion, or the alert configuration
  Tiago just set up in TradingView.
- `phase` on backfilled rows is a reconstruction (not fidelity-tested,
  same caveat as every other backfilled asset) — don't present it as
  more certain than that.
- No commit/push required beyond what's naturally produced by the backfill
  writing to the database — this doesn't touch tracked files in the repo
  unless the backfill script itself needs a symbol-list update somewhere.

## What to report back

Real query results post-backfill: row counts per timeframe/source for TSLA,
confirmation the no-collision rule held, and whether the "warming up"
pattern Tiago spotted manually now shows up as a real, data-backed signal
once the campaign tier (180/240) has history.
