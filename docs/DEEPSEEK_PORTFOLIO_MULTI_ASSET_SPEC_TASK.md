# Task packet — Portfolio Challenge: multi-asset expansion (spec-then-build)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. **Spec-then-build**,
same discipline as `reports/CAMPAIGN_LIFECYCLE_SPEC.md` — write the design
doc, stop for review, only implement after explicit authorization. This
touches real paper-capital allocation logic; get the model right on paper
first.

**Bundled with this packet:** also finish
`docs/DEEPSEEK_TSLA_BACKFILL_RETRY_TASK.md` (TSLA backfill still hasn't
landed on the live Railway volume as of this writing — verify against the
real `/assets` endpoint, not a local DB, same gap as before). Independent
of this spec — do it in whichever order makes sense, just don't report
either done without the other.

## This consciously supersedes a documented boundary

`docs/DEEPSEEK_AMC_PAPER_AUTO_EXECUTION_HANDOFF.md` states adding assets to
paper-execution "requires a separate pre-registered study, not ad hoc
addition." This packet **is** that study being commissioned — Tiago has
explicitly decided to move past AMC-only, with the reasoning stated
plainly: the North Star goal is far more achievable diversified across the
7 assets with deep DNA coverage than concentrated in one, and AMC stays the
anchor rather than being replaced. This is not scope-creep from chasing a
hot setup (the thing the original boundary guarded against) — it's a
deliberate portfolio-construction decision. State this reasoning in the
spec's own boundary section so the "why now" isn't lost.

## The decision, as given

- **Scope: the 7 deep-backfilled assets** — AMC, GME, PYPL, RBLX, SPY,
  VALE, U. Not MARA/TSLA/ARB — those remain separate watchlist candidates
  with their own thinner data (see `docs/DEEPSEEK_MARA_BACKFILL_TASK.md`,
  `docs/DEEPSEEK_TSLA_BACKFILL_RETRY_TASK.md`) and are explicitly out of
  scope for this expansion until they earn the same depth of coverage.
- **AMC stays the anchor: minimum 30% of portfolio value at all times.**
  The other 6 assets amplify opportunity around that floor, not replace it.
- **DNA Trader watches all 7 simultaneously, live**, for entries and exits
  — not sequential, not one-at-a-time.

## What the spec must decide (this is the actual hard part — don't skip)

1. **Experiment/portfolio model.** Current architecture is one
   `pe_experiments` row = one symbol, one cash pool, one `GLOBAL`-scoped
   kill switch (`paper_execution/activation.py`, `pe_paper_cash`,
   `pe_auto_switches`). A single shared North Star goal across 7 assets
   needs either (a) one experiment spanning multiple symbols under a
   shared cash pool, or (b) 7 linked experiments under a shared portfolio
   rollup. State the tradeoff explicitly and recommend one — don't pick
   silently.
2. **The 30% AMC floor — precise mechanics.** Define exactly: is it
   checked against total portfolio value at the moment of every proposed
   non-AMC trade (block the trade if it would breach the floor)? Does
   natural price drift that pushes AMC below 30% trigger anything, or only
   get flagged (the system should almost certainly *not* auto-force-sell
   other assets to top AMC back up — that's a real execution action with
   its own risk, out of scope unless explicitly decided). Write this as a
   closed rule, not prose.
3. **Per-symbol kill switch, in addition to GLOBAL.** A problem in one
   asset (e.g., a bad fill, a stuck approval) should be stoppable without
   killing the other 6. Keep `GLOBAL` as the full-stop; add per-symbol
   scope.
4. **`cloud_state.py`'s hardcoded `AMC` filters** (lines 69, 75 — heartbeat
   and open-position queries) need to generalize to the tracked symbol
   set. Audit `paper_execution/engine.py`'s evidence-root functions
   (`_root_underlying_dna`, `_root_contract_response`,
   `_root_execution_quality`, `_root_portfolio_risk`) for any other
   implicit AMC-only assumption — report what you find even if nothing
   needs to change.
5. **Per-asset eligibility gate.** Reuse the campaign-lifecycle
   reliability mechanism's own discipline: an asset with insufficient
   backfill/reliability depth shouldn't be live-tradable just because it's
   in the tracked-7 list. Decide whether `tables/dna_campaign_lifecycle_reliability.csv`
   (or an equivalent per-asset check) should gate real trade eligibility,
   not just the dashboard badge.
6. **Capital allocation across the remaining 70%.** With AMC floored at
   30%, how is the rest sized across the other 6 — equal weight, DNA
   confidence-weighted, or something else? State the model and its
   tradeoff.

7. **Design for "adding an asset" to be a checklist, not a rebuild.**
   Today, each asset (TSLA, MARA) has needed its own one-off scoping pass —
   backfill window decisions, manual reliability-mask computation, ad hoc
   `cloud_state.py` edits. That's acceptable for a one-time architecture
   change, but the end state of this spec should make onboarding the
   *next* asset a repeatable, mostly-mechanical sequence: run backfill →
   reliability mask crosses the eligibility floor → symbol appears in the
   tracked set → done, no bespoke code change per asset. State plainly in
   the spec which parts are now fully data-driven (config/table-driven)
   versus which will still need a human decision each time (e.g., the
   30%-floor logic should never change, but *which* 6 assets fill the
   other 70% is a portfolio-construction call, not something to
   auto-decide). Don't overpromise zero-touch — be honest about what's
   still a deliberate decision each time versus what's now free.

8. **Auto-entry policy — open question, address last.** Today
   `VERY_HIGH_AUTO_ACTIONS = ("partial_reduce", "close")` in
   `paper_execution/engine.py` — the system already auto-executes
   risk-*reducing* actions on high-confidence signals, but every new
   position (entry) requires manual approval, with no exception. Tiago is
   open to changing this but wants it decided deliberately, not bolted on
   separately from the portfolio model above (it changes the *meaning* of
   "achieving the goal proactively" once assets other than AMC are live).
   Address this **after** items 1-7 are settled, as its own section:
   propose 2-3 concrete options (e.g., stay manual-only; auto-entry scoped
   to AMC only at the top confidence tier with a hard cap; auto-entry
   across all 7 with per-asset caps), state the risk tradeoff of each
   plainly, and recommend one — but do not treat this as decided. It needs
   explicit sign-off separate from the rest of the spec, even if bundled
   in the same document.

## Grounded validation (same discipline as Campaign Lifecycle spec)

Before this goes to review, run the proposed allocation/eligibility rules
read-only against the 7 assets' real backfilled history and report what it
would have actually done — same kind of table as
`reports/CAMPAIGN_LIFECYCLE_SPEC.md` §8. This is what actually tests
whether the 30% floor and allocation model are sane before writing
execution code.

## Boundaries

- Design/spec phase only: read-only against existing data, no code
  changes, no experiment activation.
- Still fail-closed: nothing in the spec should weaken the existing
  `authoritative_provider_ready` gate, evidence-root validation, or kill
  switch discipline — this expands *which assets* the existing safety
  model covers, not the model itself.
- Stop after the spec and grounded-validation report. Wait for explicit
  review before any implementation.

## What to report back

The spec document, plus the grounded-validation table — same bar as the
original Campaign Lifecycle spec. This is what Tiago and Claude review
before authorizing the build.
