# Task packet — Campaign Lifecycle model (Ignition → Establishment → Resolution)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. **Spec-then-build**,
same as the insight-library pattern — write the design doc, stop for
review, only implement after it's approved. This is a bigger, more
consequential feature than "warming up" (one flag); get the definitions
right on paper first.

## Origin — three real chart walkthroughs, not a theory

This spec comes directly from a conversation where Tiago traced the same
shape across two real tickers by hand. Use both as grounding/validation
cases, and treat any third case he finds as an additional check before
freezing thresholds:

**TSLA (2026-08-12 onward, verified live via `/state_all/TSLA` where data
existed):** a fail cleared the floor, then 5m/15m ran clean (5m
`IGNITION TEST`, 15m `STRONG START` + `RELOAD`) with full alignment down to
3m, up to a `PEAK`/`PREMIUM` zone, resolving in **3 simultaneous MANAGE
tags across 3m/5m/15m** — not a breakdown, an extension/stretch cluster.
Price continued afterward, consistent with "this leg is done, not the
campaign."

**CHWY (not in our tracked assets — manual TradingView read only, cannot
be cross-checked against real data yet):** 2H lagged behind the other
tiers in printing its start; 3H/2H/30m held a clean run from ~$19 to
~$23.9; 1H was noisy the entire time while 30m was clean; resolved in a
`STRONG FAIL` on 4H with a quick recovery.

**The key generalizable insight from comparing the two:** *which*
timeframes are clean/reliable is not the same set on every ticker. TSLA's
signal was clean on 3m-15m; CHWY's was clean on 30m/2H/3H but noisy on 1H.
A model that hardcodes one fixed tier-weighting for every asset will be
wrong for some of them.

## The three-stage shape to formalize

1. **Ignition** — a lower/timing tier fires a fresh entry-type
   `signal_event` (STRONG START/RELOAD/ADD/etc.) while the higher
   campaign/backbone tier is still quiet (WAIT/neutral, not yet reacting).
   This is one level *earlier* and *broader* than the existing "warming
   up" flag (`ui/dna_dashboard.html`, shipped 2026-08-15) — "warming up"
   requires the campaign tier to already be constructive; ignition doesn't
   require that yet.
2. **Establishment** — the lower tiers settle into a sustained clean run:
   normal texture along the way (occasional FAIL/FAIL TEST = shakeouts,
   PEAK/PREMIUM = extension warnings) without the run actually breaking.
   This is where Tiago said the actual entry opportunity is — not the
   first flicker, but once there's enough evidence it's real.
3. **Resolution** — three distinct, mutually exclusive outcomes, not two:
   - **Cascade-up**: a higher tier (owner/backbone) actually confirms —
     the campaign graduates to a real higher-timeframe read.
   - **Fail-cluster**: multiple lower tiers hit FAIL/FAIL TEST together —
     breakdown, the move never reached higher-tier confirmation.
   - **Stretch-cluster**: multiple lower tiers hit MANAGE/PEAK/PREMIUM
     together — take-profit territory, *not* necessarily campaign-ending
     (the campaign may resume for another leg afterward, per the TSLA
     case).

## The per-asset reliability requirement (the hard part, don't skip it)

Do not hardcode a single fixed tier-weighting scheme applied uniformly to
every symbol. Design (in the spec, decide the actual mechanism — options
to evaluate, not a prescription):
- tracking each timeframe's historical signal consistency per asset
  (e.g., how often does this tier's readings align with the tiers above
  and below it, versus flip-flop/contradict), using the backfilled
  history already available for AMC/GME/PYPL/RBLX/SPY/VALE/U;
- whether "reliable timeframe set" should be a per-asset, periodically
  recomputed profile, or something simpler for v1 — state the tradeoff
  explicitly rather than picking silently;
- how a new/thin asset (like TSLA before its backfill, or a future asset
  with little history) degrades gracefully instead of producing a
  confident-sounding read with no real basis — same `no-basis` discipline
  already established in the insight library.

## Required spec contents (before any implementation)

Same rigor as `reports/DNA_POSITION_VOCABULARY_RESEARCH.md` §9's
integration-contract pattern:
- exact, closed vocabulary for each of the three stages and three
  resolution types (no free text, no synthesized score — discrete
  conditions, matching "warming up"'s own design principle);
- exact fields read from `/state_all` and how "cluster" is defined
  precisely (how many tiers, what counts as "simultaneous" given bars
  close at different times per timeframe);
- precedence rules for when multiple conditions could apply at once;
- the per-asset reliability mechanism, decided and justified;
- grounded validation: run the spec's exact rules against the real
  backfilled history for the 7 covered assets and report which real
  historical moments it would have flagged as ignition/establishment/each
  resolution type — this is the same "grounded validation" step the
  vocabulary research did, and it's what actually tests whether the
  thresholds are sane before writing a line of dashboard code.

## Boundaries

- Design/spec phase: read-only against existing data, no code changes.
- Advisory/dashboard-only, same as "warming up" — this does not feed
  `paper_execution`'s `VERY_HIGH` evidence roots or any execution path
  unless separately authorized later.
- Don't touch Pine, TradingView, webhook ingestion, or paper_execution/.
- Stop after the spec and grounded-validation report. Wait for review
  before building the dashboard implementation.

## What to report back

The spec document itself, plus the grounded-validation results (real
flagged moments per asset, not a description of the method) — this is
what Tiago and Claude will actually review before authorizing the build.
