# Task packet — ADV bands + VIX vol-regime (spec-then-build)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Tiago is low on
tokens and stepping away — this packet is self-contained; work
independently and hand back for Claude's verify-then-commit pass, same
discipline as every task tonight. Spec-then-build for the VIX piece
(touches decision logic); the ADV piece is small enough to build directly
with tests, no separate spec stage needed.

Follows `reports/ADDITIONAL_DATA_SOURCE_RESEARCH_2026-08.md` — read it
first, especially §3 (shortlist) and §2.4/§2.6 (the two items' full
evaluation rows). Two items, authorized to proceed on both:

## Item 1 — ADV bands (build directly, no spec stage)

**What:** Average Daily Volume bands, derived purely from OHLC data
already in the DB (Massive daily bars, already wired). Zero new source,
zero new credential.

**What it's for:** a position-sizing / carry-cost modifier + a liquidity
veto — i.e., a discrete flag like `LIQUIDITY: THIN` when current volume is
far below an asset's own historical ADV band, usable to avoid sizing into
illiquid conditions. Closed-vocabulary output, not a score — same
discipline as every other feature this project has shipped (`warming up`,
lifecycle badges, reliability mask).

**Scope:** the 7 deep-backfilled assets (AMC, GME, PYPL, RBLX, SPY, VALE,
U) — same scope as the reliability mask and multi-asset spec.

**Build:**
1. Compute each asset's ADV distribution (e.g., 20-day rolling average
   volume, plus a band — median/p10/p90 or similar, your call, state the
   choice) from existing backfilled daily OHLC.
2. Store as a precomputed table, same pattern as
   `tables/dna_campaign_lifecycle_reliability.csv` and
   `tables/dna_campaign_silence_baseline.csv` — don't invent a new
   storage pattern.
3. Surface a discrete flag (e.g., `LIQUIDITY: THIN` / `NORMAL`) wherever
   current volume falls outside the normal band, wired into
   `ui/dna_dashboard.html` the same way the silence-baseline badge was
   added.
4. Tests covering the computation and the flag threshold, same rigor as
   every prior task.

**Boundaries:** advisory/dashboard-only — does not feed
`paper_execution`'s evidence roots. Read-only against existing data, no
new provider/credential/spend.

## Item 2 — VIX vol-regime + sector/SPY benchmark (spec-then-build)

**First, a blocking prerequisite check — do this before anything else:**
per the research report, free-tier eligibility of Massive's index OHLC
endpoint is *unverified*. Check `https://massive.com/dashboard` (or the
Massive docs under the existing `MASSIVE_API_KEY`) for whether index
tickers (VIX, sector ETFs) are actually reachable on the current plan.
**If they are not free-tier eligible, stop and report — do not proceed to
the build, and say so plainly rather than working around it with a paid
call.**

If confirmed free-tier eligible, write a short spec (doesn't need the
full rigor of the Campaign Lifecycle spec, but state the same things
plainly):

1. **Vol-regime vocabulary**: closed set, e.g. `LOW / NORMAL / ELEVATED /
   HIGH`, derived from VIX level and/or its own recent range — state the
   exact thresholds and justify them (percentile-based against VIX's own
   history, not arbitrary round numbers).
2. **What it gates**: the report proposes a "high-vol veto" — define
   precisely what that vetoes (e.g., blocks new entries, not exits/risk
   reduction — consistent with tonight's principle of never auto-blocking
   risk-reducing actions) and where it plugs in (advisory dashboard flag
   first; do NOT wire it into `paper_execution`'s evidence roots or
   auto-execution without a separate, later, explicit authorization — same
   category of decision as the multi-asset auto-entry question).
3. **Relative-strength read**: how the sector/SPY benchmark folds in —
   e.g., "AMC vs SPY relative strength: OUTPERFORM/UNDERPERFORM/INLINE" as
   a discrete modifier, not a beta score.
4. **Scope**: this one is genuinely useful across all 7 tracked assets
   (not AMC-specific), unlike most features tonight — note that
   explicitly in the spec as the reason it's structured asset-agnostic
   from the start rather than per-asset like the reliability mask.

Stop after the spec for this item and report back — Claude will review
before authorizing the build, same pattern as Campaign Lifecycle and the
multi-asset spec.

## Boundaries (both items)

- No new provider, no signup, no spend, no credential beyond the
  already-in-use `MASSIVE_API_KEY`.
- Advisory/dashboard-only. Neither item touches `paper_execution/`,
  Pine, or webhook ingestion.
- Full suite + `git diff --check` clean before reporting done (item 1).
- No deploy/commit/push — hand back for review, same as every task
  tonight.

## What to report back

**Item 1:** the ADV table, the flag logic, test results, and a live
example (which asset/day would have flagged thin liquidity, if any, from
real backfilled data).

**Item 2:** the result of the Massive free-tier check (explicit yes/no,
not assumed), and — only if eligible — the spec document. If not
eligible, report that clearly and stop; don't substitute FRED VIXCLS or
another source without checking back first, since the report's shortlist
was built around the zero-new-credential framing specifically.
