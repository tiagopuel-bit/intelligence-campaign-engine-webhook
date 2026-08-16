# Task packet — Insight library wording pass (do after the short-vocabulary task)

**Requested by:** Tiago, 2026-08-15. **For:** DeepSeek. **Sequencing: after**
`DEEPSEEK_SHORT_VOCABULARY_TASK.md` is done and reviewed — both touch
`tables/dna_position_insight_library.csv`, don't run them in parallel.

## What prompted this

Live-rendered insight text (via the endpoint shipped in
`a056c3c`) reads too same-y across different options holdings, and the
evidence line surfaces near-raw field names — e.g.
`profitable · moneyness · dte_pressure · age` — which is jargon, not
something a reader parses at a glance. Example noted: a long call in a
constructive campaign renders as "hold," documented per the composition
row, with that evidence-key styling.

## What this is and isn't

This is a **copy/presentation pass, not a logic change.** The fact-only,
no-fabricated-confidence, closed-vocabulary discipline in §2–§7 of
`reports/DNA_POSITION_VOCABULARY_RESEARCH.md` stays exactly as-is — every
word still has to trace back to a real field the API actually returned.
The problem isn't that the evidence is fact-only; it's that "fact-only"
got implemented as "show the field name" instead of "show the fact in
words." Nothing here should let a row start claiming something it can't
prove, add a Greek, or invent confidence that isn't there.

## What to do

1. **Read every `conclusion` in `tables/dna_position_insight_library.csv`
   (all campaign/composition rows, long instruments now, short instruments
   once the previous task lands) side by side.** Flag any that are
   generic/interchangeable across rows — if you could swap two rows'
   `conclusion` text and it would still basically make sense, that row's
   wording isn't doing its job.
2. **Rewrite `conclusion` copy to be specific to that exact row's
   condition** — still one line, still no forbidden wording, still
   referencing only §2 fields, but written so a holder immediately
   understands *why*, not just *what*. Compare against real narrative
   examples already in the codebase for tone (`shareInsight`/
   `optionInsight` in `ui/dna_dashboard.html` read more naturally — use
   that as a rough bar, not a template to copy).
3. **Decide the evidence-bullet question and implement it:** either (a)
   turn `evidence` into short human phrases instead of raw field-name
   tokens (e.g. `profitable · moneyness · dte_pressure · age` →
   "up on the position · in the money · 6 days to expiry · held 12 days"),
   or (b) keep `evidence` as the exact-field debug trace it is today but
   stop rendering it directly in the dashboard's visible copy — render
   only `status_label` + `conclusion` there, and expose evidence via a
   collapsed/secondary UI element or not at all for now. Pick whichever
   is actually less work and more honest; report which you chose and why.
4. If you touch the dashboard rendering for this (option b), keep it
   scoped to how `populatePositionInsights()` displays the fields it
   already receives — don't change the endpoint response shape itself
   unless genuinely necessary.

## Verification

- Existing invariant tests still pass unchanged (closed vocabulary,
  no-Greeks, fact-only, deterministic) — this proves the rewrite didn't
  quietly break the discipline while improving the words.
- A side-by-side before/after table (old `conclusion` vs new, one row per
  composition cell, long **and** short) in your report — this is the
  actual review artifact, make it easy to skim.
- Full suite + `git diff --check` clean.
- If you can reach a browser locally: a live render of at least 2-3
  different holdings side by side, proving they now read distinctly
  rather than interchangeably. If not, say so explicitly.

## Boundaries

- No new facts, fields, or confidence levels invented.
- Don't touch `paper_execution/`, TradingView/Pine/webhook ingestion.
- Isolate from the unrelated in-progress "Manage" feature and anything
  else concurrently uncommitted in the same files — stop and report on
  collision.
- No deploy/commit/push required — hand back for review.
