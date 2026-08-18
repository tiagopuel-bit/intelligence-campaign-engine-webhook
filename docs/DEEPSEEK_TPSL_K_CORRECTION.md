# Correction — use k=2.2, not k=2, in both TP/SL specs

**For:** DeepSeek. Small, targeted correction to
`reports/TP_SL_RECOMMENDATION_SPEC.md` §2 and
`reports/OPTION_NATIVE_TPSL_SPEC.md`'s R:R fallback. Both specs otherwise
reviewed and in good shape — this is the only change needed before
build authorization.

## What changed

You proposed `k=2` (2:1) for the risk-reward-derived target fallback,
explicitly flagged as "a declared policy constant, not a validated edge."
That flag was correct at the time — you didn't have this yet:

A full read of the CIF Engineering Bible
(`Documents/AMC DNA Project/Bible/Claude/filesUPDATED by CLAUDE/Volume_VI_Validation_Statistical_Framework.md`
§3) turned up a real backtest: the Trade Box engine's **2.2:1** target,
run against 17 real trades on AMC 2H replay data — 56.25% win rate against
a 31.25% breakeven requirement, +0.87R average per closed trade. This is
not a guess, it's the one actual validated number in the whole
codebase for this exact question.

## What to do

Update both specs' fallback constant from `k=2` to `k=2.2`. Nothing else
in either spec's structure needs to change — the target-priority logic
(structural resistance primary, R:R fallback secondary) already treats
this as a swappable constant. Re-run §7/§4's worked examples with the
corrected multiple if the exact numbers matter for the review, otherwise
just note the constant change and the source.

## Boundary

Spec-only correction, same as before — no code, nothing wired.
