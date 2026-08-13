# Task Packet — Historical Backfill (AMC + GME, full ladder)

**Requested by:** Tiago, 2026-08-13. **For:** DeepSeek.

## Goal

Live webhook data is forward-only — a symbol/timeframe only has rows from
whenever its TradingView alert was actually turned on. For slow timeframes
(Daily, Weekly, 4H) that means real coverage would take months to
accumulate naturally. Backfill closes that gap immediately using data and
tooling that already exist, so the dashboard has a full spectrum view (long
term → short term) on day one instead of waiting it out.

**Scope: AMC and GME only, full timeframe ladder** (3m, 5m, 15m, 30m, 1H,
2H, 3H, 4H, D, W) — not the other 7 assets, matching the existing "don't
expand past AMC/GME until the ladder is clean" rollout discipline. Not
"only the slow timeframes" — the full ladder, so short-term readings also
get real history instead of starting from a single live data point.

## What already exists (don't rebuild)

- `research/lib/pine_replay_v12_6_19.py` — fidelity-tested (Checkpoint 2B)
  engine that replays DNA's phase/health/score/confidence/momentum logic
  over historical OHLC bars. This is the hard part and it's already proven.
- `massive_ohlc.py` / the Massive pipeline already used for `/ohlc` — real
  historical OHLC for AMC and GME, sufficient depth for this.
- `webhook_receiver.py`'s `alerts` table schema (`init_db()` /
  `_ALERT_MIGRATION_COLUMNS`) — the target shape to write into.

## What's needed

1. **Bridge, not a rebuild**: run `pine_replay_v12_6_19.py` over Massive
   historical bars for AMC and GME, across the full ladder, and shape the
   output to match the `alerts` table's columns.
2. **Provenance tagging — required, not optional.** Add a `source` column
   to `alerts` (`'live_webhook'` for real rows, `'backfill_replay'` for
   these) via a new migration. Every existing row defaults to
   `'live_webhook'` (backfill compat, never guess). This mirrors the
   project's own discipline elsewhere (RTH/ETH tagging, Research Overlay
   vs. Production in the Pine dashboard itself) — a replayed reading must
   never be indistinguishable from a real TradingView alert. `/state_all`
   and `/assets` should expose `source` so the frontend can show it.
3. **Version gap, handle explicitly, don't fake it**: the replay engine is
   frozen at v12.6.19. Fields that didn't exist yet in that version
   (`session`, `active_trade`, `active_entry`, `active_stop`,
   `active_target`, `active_trade_source`, `active_trade_open_pct`) must be
   `NULL` on backfilled rows — never invented or defaulted to a live-looking
   value.
4. **No collision with live rows**: backfilled history should end where
   live coverage for that symbol/timeframe actually begins (or slightly
   before, with live rows always winning on overlap) — don't overwrite or
   duplicate real webhook rows.

## Explicitly not in scope

- The other 7 original assets (LULU, PYPL, RBLX, TSLA, U, VALE, SPY) —
  separate decision later, not this packet.
- Any frontend changes to *display* the `source` tag distinctly — that's
  Claude Code's side, once the data exists.
- Re-validating the replay engine's correctness — Checkpoint 2B already did
  that; this is a plumbing task, not a research task.

## What to report back

Real query results from the live `alerts` table post-backfill (e.g. row
counts per symbol/timeframe/source, a handful of actual backfilled rows),
not a description of the pipeline running.
