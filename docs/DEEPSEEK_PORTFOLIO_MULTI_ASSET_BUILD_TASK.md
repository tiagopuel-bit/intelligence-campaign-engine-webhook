# Task packet — Portfolio Multi-Asset Expansion: build (not activate)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Build authorized
following `reports/PORTFOLIO_MULTI_ASSET_SPEC.md` (§1-9, reviewed and
accepted). **§11 (auto-entry policy): implement Option A only** — entries
(`open`/`add`) stay manual-approval-only for all 7 assets, no change to
`VERY_HIGH_AUTO_ACTIONS`. Option B/C are not authorized.

## Critical timing constraint — read first

This is going out the same night as Monday 2026-08-17's market open, a few
hours away. **Do not activate the multi-symbol experiment as part of this
task, and do not deploy anything that changes AMC's current solo-trading
behavior for tomorrow.** AMC keeps running exactly as it does today,
unaffected, through tomorrow's session regardless of how this build goes.
The build must be reviewable and mergeable without going live — activation
is a separate, later, explicit decision from Tiago after his own review of
the spec, not something this task triggers.

If anything in the implementation risks touching AMC's live path (e.g., a
migration that must run before AMC's existing experiment continues
working), stop and report before proceeding — that needs explicit sign-off
given the timing, not a judgment call.

## What to build (per spec §1-9)

1. **Schema**: add `pe_experiment_symbols(experiment_id, symbol)` join
   table (§1). Keep `pe_experiments.symbol` as-is (the anchor) for
   backward compatibility with the existing single-symbol validation path.
2. **`_validate_experiment`**: accept any symbol in the experiment's
   tracked set, not just the experiment's anchor symbol.
3. **30% AMC floor (§2)**: implement R1 (deployment-time block on
   non-AMC `open`/`add` that would breach 30% projected weight) and R2
   (flag-only on drift, no auto-rebalance). Use the projected-weight
   variant per the spec's open-item resolution (§9.1 — projected, not
   current).
4. **Per-symbol kill switch (§3)**: add `scope='SYMBOL'` to
   `pe_auto_switches`, reusing `position_ref` for the symbol per the
   spec's proposal (§9.2 resolved in favor of reuse, no new column).
5. **AMC-hardcode fixes (§4)**: generalize the 4 audited sites
   (`cloud_state.py:69,75`, `activation.py:26`, `webhook_receiver.py:521`)
   to loop over the tracked symbol set instead of hardcoding `AMC`.
6. **Eligibility gate (§5)**: wire the reliability-mask check
   (`tables/dna_campaign_lifecycle_reliability.csv`, ≥25 classified bars +
   `reliable=1` on timing/confirm/owner tiers) as a real proposal-rejection
   gate (`ASSET_NOT_ELIGIBLE`), not just a dashboard read.
7. **Allocation (§6)**: equal-weight caps, 70%/6 ≈ 11.7% per non-anchor
   asset, enforced alongside the existing per-trade caps.
8. **Auto-entry (§11)**: confirm `VERY_HIGH_AUTO_ACTIONS` stays
   `("partial_reduce", "close")` — no code change needed here, just verify
   nothing in the multi-symbol work accidentally widens it.

## Boundaries

- No activation of the multi-symbol experiment. No changes to which
  experiment is currently `ACTIVE`. AMC's existing experiment keeps
  running untouched.
- Fail-closed throughout: `authoritative_provider_ready`, evidence-root
  validation (`engine.py`'s four root functions, confirmed symbol-agnostic
  in the spec's audit — verify that's still true after your changes), and
  existing kill-switch behavior must not weaken.
- Full suite + `git diff --check` clean before reporting done.
- No deploy/commit/push — hand back for review, same as every task
  tonight. Given the timing, I will personally verify this against real
  `/assets`/`/state_all` queries and the full test suite before any commit
  happens, same rigor as everything else tonight.

## What to report back

What was built per item, test results, and an explicit confirmation
statement: "AMC's currently-active experiment is unmodified and will
continue trading solo tomorrow exactly as before this task." If that
statement isn't true for any reason, stop and say so clearly rather than
reporting success.
