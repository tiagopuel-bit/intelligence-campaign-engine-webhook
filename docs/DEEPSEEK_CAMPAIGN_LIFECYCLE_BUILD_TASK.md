# Task packet — Campaign Lifecycle: review decisions + build authorization

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Follows
`reports/CAMPAIGN_LIFECYCLE_SPEC.md` (spec accepted) and its §9 open items.
This packet decides all three and authorizes the dashboard implementation.

## Decisions on the three open items

1. **0.50 reliability threshold / 30-min cluster window** — **approved as
   proposed.** Consistent with the TSLA case (5m/15m fired within minutes
   of each other, well inside the window). No changes.

2. **Unresolved cycles** — **add a `faded` state**, do not silently reset
   to `idle`. Given ~80% of ignitions don't resolve inside the 8h window,
   showing nothing most of the time would make the feature look broken or
   absent rather than working as designed. `faded` is the honest state:
   this attempt didn't develop into a resolution, distinct from `idle`
   (nothing happening at all). Add it as a fourth stage token alongside
   `idle`/`ignition`/`establishment`/`resolved`.

3. **Whether 3m joins `micro`** — **add 3m to the `micro` tier definition,
   but do not special-case it.** Route it through the same per-asset
   reliability mechanism already designed in §7: 3m is live-only with no
   backfill, so it will naturally classify as `unreliable` (< 50 classified
   bars) and get excluded from stage detection for every asset today,
   exactly like any other thin timeframe. As live history accumulates
   (matching the ~50-bar floor), it becomes eligible automatically without
   a code change or a special rule. This resolves the tension without
   forcing a premature call: the TSLA case that motivated the whole
   feature stays representable once it has enough history, and nothing is
   hardcoded to always-include or always-exclude it.

## Authorization to build

Proceed to the dashboard implementation per the spec's closed vocabulary,
stage detection, cluster definition, and per-asset reliability mechanism
(as amended by decision 2 and 3 above). Same pattern as "warming up":

- Client-side synthesis in `ui/dna_dashboard.html` from existing
  `/state_all` data — no new backend endpoint should be needed unless the
  per-asset reliability mask genuinely can't be computed client-side from
  data already exposed (if so, stop and report before adding one).
- The reliability mask itself (§7, precomputed from backfill) needs to
  live somewhere — a static data file/table (matching the CSV pattern
  used for the insight library) is fine; don't compute it at runtime in
  the browser.
- Discrete badge(s), not a score — same visual language as "warming up"
  (a labeled flag with a plain-language explanation on hover/expand, not
  a bar or gauge).

## Boundaries (unchanged)

- Advisory/dashboard-only — does not feed `paper_execution`'s `VERY_HIGH`
  roots or any execution path.
- No Pine/TradingView/webhook ingestion changes.
- Isolate from the unrelated in-progress Manage feature and anything else
  concurrently uncommitted — stop and report on collision, don't resolve
  it yourself.
- Verify the same way "warming up" was verified: real/synthetic data
  through the local server, a live render if you can reach a browser, or
  an explicit note if you can't (same as every task today).
- Full suite + `git diff --check` clean before reporting done.
- No deploy/commit/push required — hand back for review.
