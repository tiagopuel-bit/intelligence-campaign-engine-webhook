# Task packet — Kill-switch API route + Finding A fix (build together)

**Requested by:** Tiago, 2026-08-15. **For:** DeepSeek.

## Why these two are one task, not two

`reports/amc_paper_execution/P3_ASSET_PAGE_REPORT.md` found the dashboard's
Cancel-auto button has no backing route — `set_kill_switch` exists in
`paper_execution/store.py` but `api.py` never calls it.
`reports/amc_paper_execution/AUDIT_PASS_2026-08.md` Finding A (MEDIUM,
verified by Claude directly against the code) found that even when a
per-position kill switch *is* set, it's never actually enforced — both
claim paths in `store.py` (`claim_due_proposal` around line 233,
`claim_approved_proposal` around line 281) call `kill_switch_active(conn,
row["experiment_id"])` without passing `position_ref`, so only the branch
is dead code today.

Building the route without also fixing the enforcement gap would ship a
control that *looks* like it protects one position but silently doesn't.
Do both together so it's correct the first time.

## What to build

1. **Add the missing route.** Something like
   `POST /paper/experiments/<id>/kill-switch` (follow whatever's most
   consistent with the existing `/paper/proposals/<id>/approve` etc.
   naming), authenticated, accepting `scope` (`GLOBAL`/`POSITION`),
   `position_ref` (required if scope is `POSITION`), and `enabled`. Calls
   the existing `set_kill_switch(conn, experiment_id, scope, position_ref,
   enabled)` — that function itself doesn't need to change.
2. **Fix the two call sites** so `position_ref` actually flows through:
   `kill_switch_active(conn, row["experiment_id"], position_ref=row["position_ref"])`
   at both claim paths (verify the exact row/column name for the proposal's
   position reference — Finding A's audit already confirmed `row` has this
   data available, just not currently passed).
3. **Wire the dashboard's Cancel-auto button** to the new route — same
   async-fetch pattern already used elsewhere (`loadInsight`, `loadChain`).
   Global cancel button already exists per the P3 report; check whether a
   per-position cancel control needs adding too, or whether the existing
   button covers both (your call based on what's actually there).

## Verification

- New/updated tests proving: (a) the route actually creates/updates a row
  in `pe_auto_switches` via `set_kill_switch`; (b) a `POSITION`-scoped
  switch, once set, actually blocks that position's due/approved proposal
  from claiming (the regression test for Finding A — a proposal for a
  *different* position_ref should still claim normally); (c) `GLOBAL`
  scope still works exactly as before (don't regress the one enforcement
  path that already works).
- Full suite + `git diff --check` clean.
- If you can reach a browser locally: confirm the Cancel-auto button
  actually calls the new route and updates state. If not, say so
  explicitly, same as every task today.

## Boundaries

- This is the one task today that legitimately touches `paper_execution/`
  write paths — that's expected and authorized here specifically, unlike
  the audit/design-only tasks. Still: no broker path, no live execution,
  no change to the freshness/evidence/approval-window gates themselves —
  only the kill-switch plumbing.
- Isolate from the unrelated in-progress Manage feature and anything else
  concurrently uncommitted — stop and report on collision.
- No deploy/commit/push required — hand back for review.

## Also unblocked, separate task

The insight-library wording pass (`docs/DEEPSEEK_INSIGHT_WORDING_PASS_TASK.md`)
was sequenced to wait for the short-vocabulary work, which is now done and
committed (`d3160d4`). It's ready to start — pick it up whenever, in
parallel with this or after, your call.
