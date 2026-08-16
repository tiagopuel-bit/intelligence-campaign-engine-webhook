# Task packet — finish the AMC-hardcode audit (activation wiring)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Follow-on to
`docs/DEEPSEEK_PORTFOLIO_MULTI_ASSET_BUILD_TASK.md`, which was reviewed
and verified tonight (420 tests, all new gates confirmed no-op for AMC,
migration confirmed data-preserving). Good work — this closes the one gap
found: 2 of the audit's 4 hardcoded-AMC sites were generalized
(`cloud_state.py`'s `cloud_readiness`/`cloud_state_provider`); the other 2
— `activation.py:26` and `webhook_receiver.py:521` — weren't touched.

## Same critical constraint as before — read first

**Do not activate the multi-symbol experiment. Do not change which
experiment is currently `ACTIVE`. AMC's live behavior must be unaffected
tomorrow (Monday 2026-08-17) and until Tiago explicitly authorizes
activation separately.** This task generalizes the *code path*, not the
*live state* — the multi-symbol experiment stays uncreated/inactive after
this task, exactly as it is now.

## What to finish

1. **`paper_execution/activation.py:26`** — `activate_if_ready(paper_db_path,
   webhook_db_path, symbol="AMC")`. Generalize to accept the tracked
   symbol set (anchor + additional symbols) the same way
   `cloud_readiness`/`cloud_state_provider` now do, defaulting to
   `("AMC",)` so existing single-symbol callers are unaffected. The
   experiment-creation path inside should populate `pe_experiment_symbols`
   for any additional symbols passed, alongside the existing
   `pe_experiments.symbol` anchor write.
2. **`webhook_receiver.py:521`** — `activate_if_ready(PAPER_DB_PATH,
   DB_PATH, "AMC")`. This is the actual call site that runs on every
   webhook tick. **Do not change what it passes.** Leave it calling with
   `"AMC"` only (or the equivalent default) — generalizing *this specific
   call* to pass a multi-symbol tuple is the actual activation trigger
   Tiago hasn't authorized yet. The point of this task is making the
   *function* capable of multi-symbol, not making the *live call* use it.
3. Add tests proving: (a) calling `activate_if_ready` with the old
   single-symbol default behaves byte-identical to before, (b) calling it
   with a multi-symbol tuple correctly populates `pe_experiment_symbols`,
   in a fresh/inactive DB — not against any live state.

## Boundaries

- No deploy, no commit/push, no calls against the live Railway DB for
  this task — this is pure code generalization, verified with local/temp
  DBs only, same as the rest of tonight's build.
- Full suite + `git diff --check` clean before reporting done.
- If anything about this task seems like it would require touching
  `webhook_receiver.py`'s actual call behavior to test properly, stop and
  report rather than improvise — that boundary is intentional.

## What to report back

What changed, the new/updated tests, full suite result, and the same
explicit confirmation as before: "AMC's currently-active experiment path
is unmodified; `webhook_receiver.py`'s activation call still passes only
AMC." I'll do the same verification pass on this as the rest of tonight's
work before committing.
