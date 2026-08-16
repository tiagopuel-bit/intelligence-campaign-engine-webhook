# Follow-up — Portfolio Multi-Asset Spec is missing item 8 (auto-entry policy)

**For:** DeepSeek. `reports/PORTFOLIO_MULTI_ASSET_SPEC.md` was reviewed —
items 1-7 are solid and verified (the audit findings check out exactly
against the actual code, the eligibility-gate numbers match the committed
reliability CSV, and the R1/R2 30% floor split is well-justified by the
501/501-day buy-and-hold finding). Good work on those.

But **item 8 from `docs/DEEPSEEK_PORTFOLIO_MULTI_ASSET_SPEC_TASK.md`
("Auto-entry policy — open question, address last") is entirely absent**
from the spec document. It's not deferred or flagged as skipped in your
report — it's just not there. Since it was explicitly scoped as its own
section needing separate sign-off, the spec isn't complete without it.

## What to add

A new section in `reports/PORTFOLIO_MULTI_ASSET_SPEC.md`, per the original
task's item 8:

- Today, `VERY_HIGH_AUTO_ACTIONS = ("partial_reduce", "close")` in
  `paper_execution/engine.py` — auto-execution exists only for
  risk-*reducing* actions; every new position (`open`/`add`) requires
  manual approval, no exception.
- Propose 2-3 concrete options for whether/how that changes once the
  multi-asset model is live, e.g.:
  1. Stay manual-only for entries — no change.
  2. Auto-entry scoped to AMC only, top confidence tier, hard cap
     (size and/or per-day count).
  3. Auto-entry across all 7 in-scope assets, with per-asset caps.
- State the risk tradeoff of each plainly — this is a real safety-relevant
  decision, not a preference call. Recommend one, but make clear in the
  doc that this needs explicit sign-off separate from the rest of the
  spec, even though it lives in the same document.

## Boundary (unchanged)

Still read-only, still spec-only — do not activate anything or write
execution code. Add this as an additional section (e.g. "§11 — Auto-entry
policy") and report back once it's in the document; the rest of the spec
does not need to be redone.
