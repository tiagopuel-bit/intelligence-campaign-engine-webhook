# Runner / Uptime Monitoring — Design (read-only detection)

**Scope:** design the *detection* of a silently-stopped paper runner, not the
delivery. Notification delivery is already handled by Claude's
`scripts/paper_alert_check.py` + local `/loop`; this document defines only the
data it would need. **Design-only** — the proposed change touches
`paper_execution/` write paths (schema + runner) and therefore requires
separate authorization before implementation.

## Problem

After P4 activates, the runner is event-driven: every accepted heartbeat calls
`_paper_tick_safely()` → `run_paper_once()`. There is currently no persistent
record that a tick actually completed, so if the runner raises, the worker
stalls, or the DB lock wedges, the system can go silent on its 10-minute clock
with no way to distinguish "healthy but idle" from "dead".

## What "runner is healthy" means (precise)

A runner is healthy during market hours when, for the active experiment:

1. the latest underlying `bar_time` is fresh (already surfaced as
   `authoritative_provider_ready`);
2. a `run_paper_once` tick **completed** (returned, with or without proposals)
   within the last `STALE_AFTER_MINUTES` minutes; and
3. `global_auto_disabled` is `false` (auto path actually eligible).

"Idle" (no proposals due) must still count as a completed tick — silence is
only abnormal when *no tick completed*, not when *no proposal executed*.

## Proposed data (write-path change, needs authorization)

Add a single-row, per-experiment table (or a column set on `pe_experiments`):

```sql
CREATE TABLE IF NOT EXISTS pe_runner_state (
    experiment_id INTEGER PRIMARY KEY REFERENCES pe_experiments(id),
    last_tick_at  TEXT NOT NULL,       -- ISO UTC, updated on every completed tick
    last_tick_ok  INTEGER NOT NULL,    -- 1 = returned, 0 = raised (caught)
    updated_at    TEXT NOT NULL
);
```

`_paper_tick_safely()` (or the tail of `run_paper_once`) upserts
`last_tick_at` / `last_tick_ok` on **every** tick, including zero-proposal ticks
and the caught-exception path (`last_tick_ok=0`). This is a single
`INSERT ... ON CONFLICT ... DO UPDATE`, no scheduler, no sleeping.

## Proposed read-only exposure

Extend `health_summary` (already read-only) with:

```json
{
  "runner_last_tick_at": "2026-08-18T13:45:12.000000+00:00",
  "runner_last_tick_ok": true,
  "runner_stale": false,
  "runner_stale_after_minutes": 10
}
```

`runner_stale` is computed read-only:

- `false` when `last_tick_at` is within `STALE_AFTER_MINUTES` (suggest 10, i.e.
  comfortably more than the longest inter-heartbeat gap of ~2 minutes and the
  10-minute approval window), or when the market is closed (no freshness
  expectation);
- `true` otherwise (no completed tick in the window during market hours).

`runner_stale` must **never** affect execution — it is telemetry only. The
existing `runner_ready` gate continues to be the only execution gate.

## Detection handoff (no delivery built here)

Claude's `scripts/paper_alert_check.py` can add a single rule: alert when
`/paper/health` returns `runner_stale == true` (or, pre-implementation, when
`authoritative_provider_ready` is true but `runner_last_tick_at` is missing/
old). No new endpoint is required — `/paper/health` already exposes no secrets
and needs no auth.

## Alternatives considered

- **Derive from heartbeats alone:** insufficient — heartbeats can keep flowing
  while the runner is dead; "heartbeats fresh" ≠ "runner ran".
- **Derive from proposal-events gap:** insufficient when there are zero
  proposals (idle is healthy).
- **Separate endpoint:** unnecessary; `/paper/health` is the natural,
  already-read location.

## Boundary

This is a design document. Implementing it changes `schema_v1.sql` (or
`db.py`), `runner.py`, and `health_summary` — all `paper_execution/` write
paths — so it is stopped here pending authorization, consistent with the
standing boundary. No notification-delivery code, no scheduler, and no
deployment is designed or built.
