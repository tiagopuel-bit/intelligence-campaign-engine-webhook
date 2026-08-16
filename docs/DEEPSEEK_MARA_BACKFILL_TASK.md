# Task packet — MARA backfill (6-month scope) + reliability mask

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Scope extension of
the existing backfill pipeline (same pattern as `DEEPSEEK_TSLA_BACKFILL_TASK.md`),
not new engineering.

## Why

Tiago spotted a live setup on MARA today by eyeballing six TradingView
panels (30m/1h/2h/4h/15m/1D) — lower stack (30m-4H) building on
RELOAD/ACCUMULATE while 2H specifically lags/goes quiet, similar shape to
the CHWY case that motivated the per-asset reliability mechanism. MARA is
an equity (Massive-covered, unlike ARB — no data-source question here).

## Scope — deliberately smaller than the original 7-asset backfill

Budget-conscious: **6 months of history, not 2 years.** Per the reliability
mechanism's own 50-classified-bar floor (§7 of `reports/CAMPAIGN_LIFECYCLE_SPEC.md`),
6 months clears every timeframe through 4H with real margin above the
floor (4H lands ~200 bars, not a bare minimum) and Daily lands ~125 bars.
Weekly will fall short of the 50-bar floor at 6 months (~26 weekly bars) —
that's expected and fine; Weekly is a slow backbone check, not decisive for
the ignition/timing reads Tiago is actually watching. Do not extend the
pull to cover Weekly's floor without being asked — that's the tradeoff
being deliberately made here to control cost.

## What to do

1. Run the existing backfill (`webhook/backfill.py` / `POST /backfill`) for
   `MARA`, ladder 3m/5m/15m/30m/1H/2H/3H/4H/D/W same as other assets, but
   **window the pull to 6 months back from today (2026-08-16)**, not full
   history. If the backfill tool doesn't support a date-bounded pull
   directly, do the minimal adaptation needed to bound it — don't pull full
   history and discard the rest, that defeats the cost-saving point.
2. Confirm the no-collision rule holds (backfilled rows end where live
   coverage begins, live always wins on overlap) — same rule as every prior
   backfill task.
3. Compute MARA's reliability mask the same way
   `tables/dna_campaign_lifecycle_reliability.csv` was built for the other
   7 assets (agreement_rate, classified_bars, reliable flag per timeframe),
   using the 0.35 floor + 25-bar sample floor already established as this
   build's working threshold (see `reports/CAMPAIGN_LIFECYCLE_BUILD_REPORT.md`
   for why 0.35 not the originally-proposed 0.50). Append MARA's rows to
   the existing CSV and to the embedded `LIFECYCLE_RELIABILITY` object in
   `ui/dna_dashboard.html`.
4. Verify via real `/assets` and `/state_all/MARA` queries post-backfill —
   report actual row counts per timeframe/source and the actual computed
   agreement rates, not a description of the process.

## Boundaries

- No changes to the backfill pipeline itself unless something is actually
  broken.
- No changes to Pine, live webhook ingestion, or alert configuration.
- No changes to the 0.35/25-bar thresholds themselves — those are the
  build's existing working values, not something to re-tune per-asset.
- `phase` on backfilled rows is a reconstruction, not fidelity-tested —
  same caveat as every other backfilled asset, don't overstate certainty.
- Full suite + `git diff --check` clean before reporting done. No
  deploy/commit/push — hand back for review.

## What to report back

Real row counts per timeframe/source for MARA, confirmation of the
no-collision rule, MARA's actual agreement-rate table (all timeframes,
same format as the existing CSV), and which timeframes land reliable vs.
unreliable/thin under the 0.35+25-bar rule — Weekly is expected to be thin,
report whether anything else surprisingly falls short too.
