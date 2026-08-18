# Task packet — TP/SL recommendation: build (both specs)

**Requested by:** Tiago, 2026-08-17/18. **For:** DeepSeek. Build authorized
following `reports/TP_SL_RECOMMENDATION_SPEC.md` and
`reports/OPTION_NATIVE_TPSL_SPEC.md` (both reviewed, k=2.2 correction
applied). All open items from both specs' §8/§6 are answered below — build
directly, no further spec pass needed.

## Answers to open items — nothing left to guess

**From `TP_SL_RECOMMENDATION_SPEC.md` §8:**
1. `k=2.2` — confirmed.
2. Fatigue caps (≥0.5% material change, 1/ticker/day, 3/experiment) — confirmed as proposed.
3. Option-bracket scope split (DNA levels attach to share brackets directly; for options, the same underlying level surfaces as reference-only, human sets the actual option bracket price) — confirmed.
4. **Always include a target** — never stop-only. Additionally, in scope now: DNA should also be able to suggest **raising the target** (not just the stop) as a campaign develops favorably — a "trailing target," symmetric to the already-scoped trailing stop (§1a). Design it the same way: while a ticker has an ACTIVE bracket, if the primary target mechanism (nearest stretch-event level above price) finds a *higher* valid level than the bracket's current `target_price`, emit a `set_bracket` proposal reusing the ticker with the raised target and the existing stop preserved — same reuse of `upsert_bracket`'s supersede-the-active-bracket semantics as the trailing-stop case, same "never lower" direction rule mirrored for target (raise-only). Still requires human approval, same as every bracket change.
5. Clamp to **`single_contract_max_pct`** (15%), not `max_daily_paper_loss_pct` — confirmed, overrides the spec's original assumption. Update §3's cap formula accordingly and re-verify the worked cap-check numbers in §7 against the corrected cap.

**From `OPTION_NATIVE_TPSL_SPEC.md` §6:**
6. Minimum-history floor ≥30 bars of the option's own series — confirmed.
7. Lookback window 20 bars — confirmed.
8. Target priority order (option recent-high → breakeven → R:R 2.2 fallback) — confirmed.
9. **DELAYED Massive OHLCV is an allowed fallback**, not LIVE-heartbeat-only. Label it `DELAYED` in the reasoning string exactly as the rest of the project already labels delayed data (FINRA short-volume, ADV bands) — never silently presented as live. LIVE heartbeat data is preferred whenever it's actually fresh; DELAYED is the fallback so the feature isn't fully dormant while the option-heartbeat infra gap remains unresolved. This does not relax the trigger/fill path — `bracket_decision`/`apply_bracket_trigger` stay strictly LIVE-only and fail-closed, unchanged; this decision only affects whether a *suggestion* can be generated.
10. Cap math uses **total portfolio value (positions + cash)**, not just the bracketed position's own notional — confirmed as the base spec already assumed.

## What to build

Per both specs' full designs (§0-§7 of each), now unblocked:

1. `recent_resistance_price` field (base spec §2) — the structural-target
   mirror of `recent_support_price`.
2. Initial stop + target suggestion (base spec §1, §2) reusing
   `suggest_trailing_stop`'s discipline for the no-existing-stop case.
3. Trailing stop **and trailing target** updates (§1a + item 4 above) —
   both raise-only, both go through `set_bracket` re-proposals against the
   existing ACTIVE bracket.
4. The `single_contract_max_pct` cap-clamp rule (§3, corrected per item 5).
5. On-tick trigger with the stated fatigue guards (§4).
6. Option-native derivation (`recent_option_support`/`recent_option_resistance`,
   §1 of the option spec) with the ≥30-bar floor, 20-bar lookback, and the
   DELAYED-Massive fallback (item 9) clearly labeled.
7. Option-notional cap math using `single_contract_max_pct` and total TPV
   (items 5 + 10).

## Hard boundary — unchanged from every prior task

A DNA-suggested bracket (initial, trailing-stop-raise, or trailing-target-raise)
is an ordinary `set_bracket` proposal: `PENDING_APPROVAL` → human approval →
`upsert_bracket`. Nothing here ever auto-sets or auto-raises a bracket without
approval, and `set_bracket` stays out of `VERY_HIGH_AUTO_ACTIONS`. The
trigger/fill mechanism's LIVE-only, fail-closed behavior is unchanged.

## Boundaries (standard)

- No changes to `paper_execution`'s evidence-root functions, the 30% AMC
  floor, or any other existing cap beyond the scoped clamp-target change.
- Full suite + `git diff --check` clean.
- No deploy/commit/push — hand back for review, same verify-then-commit
  pass as every task.
- Log a summary to `docs/PAPER_TRADE_DESK_LOG.md` when done.

## What to report back

What was built per item, new/updated tests and their names, full suite
result, and a live/real grounded check the same way the specs did (a real
AMC state pull showing what would actually be suggested right now, and
explicit confirmation of what the option-native path outputs given the
option heartbeats are still unresolved — should be the same honest
`NO_SUGGESTION_INSUFFICIENT_OPTION_HISTORY` unless DELAYED Massive data
changes that, in which case say so explicitly).
