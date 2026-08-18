# Option-native TP/SL — spec extension, blocks TP/SL implementation start

**For:** DeepSeek. Follows `reports/TP_SL_RECOMMENDATION_SPEC.md` (Tiago
signed off on all 5 open items in §8 tonight) and
`docs/DEEPSEEK_TPSL_RECOMMENDATION_TASK.md`.

## Why this blocks, not just extends

Tiago flagged something real after signing off: that spec's §6 scope
decision — DNA-suggested stop/target levels attach to **share** brackets
only; option brackets get the underlying's levels as reference-only,
translation declined because it needs synthesized delta/gamma — is correct
reasoning, but it means the spec as written **doesn't actually cover most
of what gets traded**. The AMC challenge portfolio is already
majority-options (4 of 5 open positions are calls). "DNA suggests
brackets" that can't actually suggest a usable level for an option position
isn't the feature Tiago asked for — it's a partial version of it.

**Do not start implementing the existing spec's share-only version yet.**
Spec this extension first so the two ship together, covering the actual
trade mix from day one.

## The actual ask

Design (spec-only, same discipline as before — no code, no proposal
created) an option-native trailing-stop / initial-stop suggestion that:

- Derives its level from **the option's own price structure** — its own
  recent high/low, its own volume-confirmed pullback/support — the same
  causal discipline `contract__close_location` and the existing
  `option_return`/`activity_ratio`/`unchanged_print` fields already use
  elsewhere in this codebase for contract-level reasoning.
- **Does not** attempt to translate an underlying support/resistance level
  into an option price via delta/gamma or any other synthesized Greek —
  that constraint from the original spec's §6 stays exactly as strict.
  This is a genuinely different derivation, not a workaround for the
  translation problem.
- Reuses the same `set_bracket` proposal → `APPROVAL_REQUIRED` →
  `upsert_bracket` lifecycle already shipped — no new action type, no new
  approval model. The only new thing is *what evidence produces the
  suggested price* when the ticker is an option instead of a share.

## Ground it in what's actually available

Before designing the derivation, go verify exactly what live, causal,
non-invented option-price history is actually available to compute from —
same "verified in code, not assumed" discipline as the original spec's §0.
Relevant starting points, don't assume any of these without checking:

- `option_heartbeats` table (webhook DB) — what's the real bar-time
  granularity and history depth actually available at decision time, not
  in theory?
- The contract-response evidence root fields already computed elsewhere
  (`options_dna.py`, `options_dna_research.py`) — is there already a
  "recent option support/resistance"-shaped signal being computed for a
  different purpose that could be reused here, or does this need a new
  derived field the same way the original spec added
  `recent_resistance_price`?
- Whether there's enough real bar history per contract for this to be a
  causal, evidenced level (not a guess from 2 data points) — options are
  thinner than the underlying; say plainly if the data doesn't support a
  reliable option-native level for some/all of the currently-held
  contracts, rather than forcing a number out of thin data. A fail-closed
  "no suggestion, insufficient option history" outcome is an acceptable
  and expected output, same as the original spec's "no bullish-support
  event → no suggestion."

## Caps and challenge-fit

Same discipline as the original spec §3: a suggested option stop must not
let a single stop-out breach `max_daily_paper_loss_pct` (5% × TPV) — but
compute the cap check in **option-contract notional terms**
(`qty × price × 100`), not underlying notional, since that's what actually
governs paper P&L exposure for that specific bracket.

## Report back

A spec document (same location/style as `TP_SL_RECOMMENDATION_SPEC.md`,
e.g. `reports/OPTION_NATIVE_TPSL_SPEC.md`) covering: the grounded data
check above, the derivation method, worked examples against Tiago's
actual currently-held AMC option positions if live data supports it (same
"grounded validation" discipline as before — real numbers, not
hypotheticals), open items for Tiago's review, and an honest statement of
which currently-held contracts (if any) don't have enough history for a
reliable suggestion yet. Read-only, no code, no proposal created — stop
for review, same as always.
