# Task packet — Per-timeframe silence baseline (event-cadence outlier flag)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Independent of the
multi-asset build and TSLA work already in flight — pick this up whenever,
no rush.

## Why

Tiago's been manually noticing, across MARA/AMC/BB chart reads tonight,
that one specific timeframe often goes conspicuously quiet for an unusual
stretch while the tiers around it keep building (MARA's 2H, specifically).
The dashboard's ignition detector already has a binary "are higher tiers
quiet" gate baked in (`lifecycleStage()` in `ui/dna_dashboard.html`, fixed
thresholds: confirm 4h, owner 6h, backbone 12h), but nothing surfaces
*how* quiet a given tier's current silence is relative to its own typical
behavior. This task adds that baseline.

## What to build

1. **Compute, per `(asset, timeframe)`, from the existing backfilled event
   history** (same source rows used for
   `tables/dna_campaign_lifecycle_reliability.csv`): the distribution of
   gaps between consecutive classified events on that tier — not just a
   flat mean/median. Report median gap **and** a percentile marker (e.g.,
   p90) so a single number doesn't flatten regime differences (quiet
   consolidation vs. active campaign have very different natural cadence).
2. **Store it** the same way the reliability mask is stored — a static,
   precomputed table (new CSV or an added column set, your call — state
   the choice), recomputed manually when backfill refreshes, not
   runtime-computed. Match the existing pattern, don't invent a new one.
3. **Surface it**: for each tracked asset/timeframe currently showing on
   the dashboard, compare live time-since-last-event against that tier's
   baseline. Flag when current silence exceeds the tier's own p90 (i.e.,
   "this is longer than 90% of this tier's historical gaps for this
   asset") — a discrete flag, not a synthesized score, same design
   principle as every other badge on this dashboard (`warming up`,
   lifecycle stages).
4. Decide and document explicitly: is this a good enough proxy on its own,
   or does it need a minimum-sample floor per tier the same way the
   reliability mask needed the 25-bar floor (a tier with too few
   historical events doesn't have a meaningful "typical gap" to compare
   against — apply the same `no-basis` discipline rather than showing a
   number with no real basis).

## Scope

The 7 deep-backfilled assets (AMC, GME, PYPL, RBLX, SPY, VALE, U) — same
scope as the reliability mask and the multi-asset spec. Don't include
MARA/TSLA/BB/ARB; they don't have the backfill depth for a meaningful
baseline yet.

## Boundaries

- Advisory/dashboard-only, same as every lifecycle feature — does not feed
  `paper_execution`'s evidence roots or any execution path.
- Read-only against existing backfilled data; no new data collection, no
  Pine/webhook changes.
- No changes to the existing ignition/establishment detection logic —
  this is an additional, separate signal, not a replacement for the
  existing "higher tiers quiet" gate.
- Full suite + `git diff --check` clean before reporting done. No
  deploy/commit/push — hand back for review, same as every task.

## What to report back

The actual computed baseline table (median + p90 gap per asset/timeframe),
which tiers hit the sample floor vs. which don't, and — if you can check
it against a real current example (e.g., MARA's 2H silence tonight, even
though MARA itself is out of scope for the badge, or a comparable case on
one of the 7) — whether the baseline would have actually flagged it as an
outlier. That's the real test of whether this is useful, not just built.
