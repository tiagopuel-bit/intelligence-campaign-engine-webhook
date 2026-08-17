# Task packet — Entry discovery: DNA Trader surfaces new candidate positions

**Requested by:** Tiago, 2026-08-17. **For:** DeepSeek. Spec-then-build —
this is a new capability class (proposing positions that don't exist yet,
not managing held ones), touching real paper-execution proposal creation.
Write the design doc, stop for review, same discipline as Campaign
Lifecycle and the multi-asset spec.

## What's being asked, precisely

Today, `paper_execution`'s evidence-root/proposal system only evaluates
actions on **already-held** positions (the frozen starting holdings from
activation). There is no mechanism that scans for and surfaces **new**
candidate positions worth opening. Tiago wants DNA Trader to actively look
for entry opportunities — starting with AMC only (matching today's
activation scope), designed to extend to the other 6 assets once
tomorrow's multi-asset expansion activates (per
`reports/PORTFOLIO_MULTI_ASSET_SPEC.md`, already built, not yet
activated).

## Hard boundary — read first, this is not negotiable without separate sign-off

**This surfaces candidates as proposals requiring manual approval. It does
NOT open positions automatically.** §11 of the multi-asset spec locked
entries to manual-only (Option A) tonight, specifically because
auto-entry is a real capital-deployment decision that needs its own
explicit authorization. This task is about *discovery*, not *execution* —
a candidate surfaced by this feature still goes through the exact same
`open`/`add` approval path (evidence roots, 30% AMC floor, eligibility
gate, the 600-second approval window) as if a human had typed it in
manually. If anything in the design would let a discovered candidate skip
that path, stop and report — don't build it.

## What to design (spec, not code yet)

1. **Where candidates come from.** The options chain data is already
   wired (`massive_options.py`). Define exactly what makes a strike/
   expiration worth surfacing — reuse the existing DNA state machinery
   (campaign lifecycle stage, evidence roots, reliability-mask
   eligibility) rather than inventing a new scoring system. A candidate
   should be describable the same way everything else in this project is:
   a closed-vocabulary condition (e.g., "ignition detected + timing tier
   entry + underlying eligible"), not an opaque rank/score.
2. **Reuse, don't duplicate.** `decision_engine.py` /
   `poll_and_recommend.py` already do multi-timeframe DNA synthesis for a
   symbol (currently a manual CLI tool, not live). State explicitly
   whether entry discovery should call into that existing logic or if
   it needs new logic, and why.
3. **What "surfacing" means concretely.** Does it create an actual
   `pe_order_proposals` row (status `PENDING_APPROVAL`, same table
   everything else uses), or a separate lighter-weight "candidate" object
   that a human promotes to a real proposal? State the tradeoff — the
   former reuses all existing approval/evidence-root machinery for free;
   the latter is a smaller blast radius if the discovery logic is wrong
   early on. Recommend one.
4. **Symbol scope, designed for tomorrow.** Build this AMC-only today, but
   parametrize by symbol from the start (reusing `tracked_symbols()` from
   tonight's multi-asset work) so extending to the other 6 assets
   tomorrow is the "checklist, not a rebuild" experience item 7 of the
   multi-asset spec already committed to — not a second scoping exercise.
5. **Frequency/triggering.** When does discovery actually run — on every
   webhook tick (like the existing runner), on a slower cadence, or
   on-demand? State the tradeoff (a scan on every tick could be noisy;
   too slow could miss windows).
6. **Rate/volume limiting.** How many candidates can surface at once
   without becoming alert-fatigue? A discrete cap or throttling rule,
   stated explicitly.

## Grounded validation

Before this goes to review, run the proposed discovery logic read-only
against AMC's real backfilled/live history and report what it would have
actually surfaced — same discipline as Campaign Lifecycle's §8 and the
multi-asset spec's §8. Real candidates, not a description of the method.

## Boundaries

- Design/spec phase: read-only against existing data, no code changes,
  no proposal creation, no activation.
- Does not weaken `authoritative_provider_ready`, evidence-root
  validation, the 30% AMC floor, the eligibility gate, or the approval
  window — this expands *what gets proposed*, not how proposals get
  approved.
- Stop after the spec and grounded-validation report. Wait for explicit
  review before any implementation.

## What to report back

The spec document, plus the grounded-validation table (real AMC
candidates the logic would have surfaced, with the evidence behind each).
This is what Claude and Tiago review before authorizing the build — same
bar as every other spec tonight.
