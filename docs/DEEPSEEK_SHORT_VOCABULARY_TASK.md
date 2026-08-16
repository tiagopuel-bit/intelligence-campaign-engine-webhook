# Task packet — Extend the DNA insight library to short positions

**Requested by:** Tiago, 2026-08-15. **For:** DeepSeek.

## Why

The known gap flagged in `reports/amc_paper_execution` / the insight-library
integration work: `dna_insight_library.py` only models `shares`/`long call`/
`long put`. `webhook_receiver.py`'s new `/positions/<id>/insight` endpoint
currently maps every holding by `instrument_type` alone, ignoring
`direction` — a short position gets long vocabulary applied to it, which is
wrong, not just incomplete. Tiago's said achieving the portfolio milestones
will likely require short trades, so this needs to be real vocabulary, not a
placeholder.

**This is advisory-only, same as the rest of the insight library** — it does
not touch order execution, `paper_execution/`, or open/close any position
by itself. It's still a real research task, not a quick patch: same rigor
as the original vocabulary research (§9 integration contract, closed
vocabulary, grounded validation, no forbidden wording).

## The core asymmetry (starting point, verify against real data before freezing)

§6 of the research doc already states the deliberate asymmetry for longs:
*"broken/weakening helps a long put and hurts a long call and shares."*
Short positions mirror this a second time:

- **short shares** — profits when price falls. Mirror of `shares`:
  broken/weakening is favorable (hold/consider covering into strength later),
  expanding/constructive is the risk condition (protect/reduce — the shares
  you're short are working against you).
- **short call** — profits when price stays flat or falls (theta + no
  assignment). Mirror of `long call`: expanding is the risk condition
  (protect/close before assignment risk), broken/weakening is favorable
  (hold, decay working for you).
- **short put** — profits when price stays flat or rises. Mirror of
  `long put`: broken/weakening is the risk condition (assignment risk,
  protect/close), expanding/constructive is favorable (hold, decay working
  for you).

**Also inverted, not just the campaign-condition mapping:**
- ITM/OTM meaning: an ITM short option is the *bad* state (real assignment
  risk), OTM is *good* (likely expires worthless, which is the short
  seller's win condition) — opposite of the long-side framing already in
  §7's modifiers.
- Profit/loss direction: "profitable" for short shares means price is
  *below* entry, not above — don't reuse the long-side profit/loss check
  as-is.

Verify these against real held/synthetic short scenarios before freezing —
don't just invert the CSV rows mechanically without checking the resulting
wording still reads correctly and doesn't contradict itself.

## What to build

1. **Extend `tables/dna_position_insight_library.csv`** with `short shares`/
   `short call`/`short put` composition rows (new column, not a new file —
   keep the single source of truth), following the same 7-required-attributes
   structure (status label, conclusion, evidence, decision-change,
   prohibited, fields, confidence) and the same precedence-ordered
   deterministic approach as the existing rows.
2. **Extend `holding_state()` and `compose()` in `dna_insight_library.py`**
   to handle the inverted ITM/OTM and profit/loss semantics for short
   instruments — don't just add new instrument labels while reusing the
   long-side mechanics functions unchanged, since that would silently
   produce backwards readings.
3. **Fix `webhook_receiver.py`'s instrument mapping** in
   `GET /positions/<id>/insight` to actually branch on the position's
   `direction` field — `SHARE` + `LONG` → `shares`, `SHARE` + `SHORT` →
   `short shares`, `CALL`/`PUT` + `LONG` → `long call`/`long put`,
   `CALL`/`PUT` + `SHORT` → `short call`/`short put`. This is the actual
   bug fix — right now direction is ignored entirely.
4. **Update the research doc** (`reports/DNA_POSITION_VOCABULARY_RESEARCH.md`)
   — extend §6's table with the new rows, document the ITM/OTM and P&L
   inversions explicitly (don't leave them implicit), and add a grounded
   validation pass if there's a way to check the new rows against real or
   synthetic short scenarios (even a synthetic short AMC position, since a
   real one may not exist in the portfolio yet).

## Verification

- New composition rows: same test rigor as the existing suite —
  deterministic, closed vocabulary, no-Greeks, and specifically a test
  proving the mirror-asymmetry itself (e.g. assert `short shares`'s intent
  for `expanding` equals `shares`'s intent for `broken`, and vice versa,
  for the conditions where that symmetry is supposed to hold — call out any
  condition where it doesn't and why).
- Endpoint test: a `SHORT` direction position now gets short vocabulary, not
  long vocabulary silently mislabeled — this is the regression test for the
  actual bug being fixed.
- Full suite + `git diff --check` clean.
- If you can get to a browser locally, a live render check the same way
  Claude verified the long-side wiring (real position via `POST /positions`
  with a `SHORT` direction, screenshot or described render, DELETE cleanup)
  — if not, say so explicitly rather than skipping mention of it, same as
  last time.

## Boundaries

- Still advisory-only — this does not authorize opening a real short
  position, does not touch `paper_execution/`, order proposals, or
  execution logic.
- Don't touch TradingView/Pine/webhook ingestion structure.
- Isolate your diff from the unrelated in-progress partial-close "Manage"
  feature and the options-replication coverage-protocol work, both still
  sitting uncommitted in overlapping files — stop and report on collision,
  don't resolve it yourself.
- No deploy/commit/push required — hand back for review same as always.
