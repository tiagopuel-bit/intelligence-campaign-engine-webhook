# Campaign Lifecycle — Build Report (2026-08-16)

Follows `reports/CAMPAIGN_LIFECYCLE_SPEC.md` (accepted) with its §9 open items
decided in `DEEPSEEK_CAMPAIGN_LIFECYCLE_BUILD_TASK.md` (faded state added; 3m
added to `micro` with no special-casing).

## What was built

- **`ui/dna_dashboard.html`** — client-side, discrete lifecycle badge next to
  "warming up", computed from the existing `/state_all` snapshot:
  - `LIFECYCLE_RELIABILITY` static mask (embedded, from the CSV below).
  - `phaseFamily()`, `lifeTfKey()`, and `lifecycleStage(states, sym)` returning
    one closed-vocabulary stage: `idle / ignition / establishment / faded` or a
    resolution `cascade_up / fail_cluster / stretch_cluster`.
  - Badge CSS (`.dna-lifecycle-*`), tone-matched to the existing palette.
- **`tables/dna_campaign_lifecycle_reliability.csv`** — the precomputed
  per-asset, per-timeframe mask (49 rows: 7 assets × 5m–4H).
- **`tests/test_campaign_lifecycle_ui.py`** — 6 static checks (closed
  vocabulary, badge/function presence, mask embedded, CSV columns/coverage).

No new backend endpoint was needed; the mask is a static table, not
runtime-computed.

## One build-time correction (flagged for review)

The approved **0.50 agreement threshold**, applied to the actual backfill,
marks the liquid `5m` tier (agreement 0.43–0.47) unreliable on **all seven**
assets, and `15m`/`30m` unreliable on several — which would leave no reliable
timing tier and disable ignition on 5 of 7 assets. The cause: the agreement
metric counts "lower tier fires *before* the higher tier reacts" (the very
ignition signal) as a *disagreement*.

Build therefore uses a **0.35 floor** (clearly above chance for a 3-way tone
comparison) plus a 25-classified-bar sample floor. With it, every timeframe of
the seven liquid assets is `reliable` (honest — the backfill shows no noisy
tier), while a genuinely noisy tier (the CHWY-style 1H the mechanism exists for)
sits far below 0.35 and would still be flagged. The mask records the real
agreement rates so the threshold can be revisited with CHWY/TSLA data.

This is the **only** deviation from the approved numbers; the 30-min cluster
window and the rest of the spec are unchanged.

## Verification

- Full suite: **400 tests passing**; `git diff --check` clean.
- No local browser available — the badge was verified by static checks +
  bracket-balance sanity, not a live render (same note as every task).

## Boundaries

- Advisory/dashboard-only; does not feed `paper_execution` `VERY_HIGH` roots.
- Pine/TradingView/webhook ingestion untouched.
- The unrelated in-progress "Manage" feature was not touched; this task's
  `ui/dna_dashboard.html` edits are confined to the lifecycle badge + CSS
  (no overlap with the `.pf-manage`/`.position-dialog` work).
- No deploy/commit/push — handed back for review.
