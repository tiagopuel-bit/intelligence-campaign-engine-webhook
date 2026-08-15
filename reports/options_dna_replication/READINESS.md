# Options DNA — Readiness Report (2026-08-15)

## Status summary

The Options DNA tree is a research-only pipeline: underlying DNA, contract
response, SEC catalyst and position context are separate causal layers; no
production guidance, order, price, quantity or imperative action is emitted
anywhere. The entry-confirmation finding is frozen at `R0_PLAN_ONLY` and the
multi-asset external replication is fully specified but not yet executed.

- Full suite: **373 tests, all passing** (`python3 -m unittest discover -s tests`).
- Options DNA subset: **145 tests** across 25 test files.
- New this round: insight library, replication evaluation + acquisition/assembly
  scripts, and 33 additional tests (all passing).

## Modules and coverage

| Module | Purpose |
| --- | --- |
| `options_dna.py` | exact-timestamp alignment, causal component ledger |
| `options_dna_research.py` | contract selection, forward path outcomes |
| `options_dna_dataset.py` | replay anchors, deterministic sampling, client |
| `options_dna_catalyst*.py` | SEC public-acceptance / first-seen clocks |
| `options_dna_position*.py` | position scope + exact-entry replay episodes |
| `options_dna_targets.py` | future-only multi-window target matrix |
| `options_dna_calibration*.py` | discovery-only freeze, immutable holdout labels |
| `options_dna_rule_search.py` | transparent conjunction search + validation |
| `options_dna_shadow*.py` | shadow journal, runner, acceptance |
| `options_dna_guidance.py` | shadow-only advisory bundle destination |
| `options_dna_insight.py` | **new** contract-specific insight library |
| `options_dna_replication.py` | **new** multi-asset replication evaluation |
| `options_dna_replication_acquisition.py` | **new** multi-asset fetch + selection |

## New: contract-specific insight library (`options_dna_insight.py`)

Maps causal evidence — underlying DNA, premium activity, liquidity/unchanged
prints, DTE, campaign pressure and catalyst risk — into a research advisory
action (`WATCH / MANAGE / PROTECT / REDUCE / CLOSE / ROLL`). It never repeats
visible position facts, never issues orders, and never reads outcomes.
Deterministic precedence: catalyst veto → broken campaign → deep-ITM roll →
DTE pressure → weakening → unchanged/illiquid → conflicting → constructive →
fallback WATCH. 22 unit tests + 1 real-ledger end-to-end scenario test.

## New: multi-asset external replication

Frozen object (unchanged from Checkpoint B): `CONFIRMATION_FAILURE`, `CALL/14`,
`contract__close_location <= 0.3333` AND `underlying__campaign_health <= 31.6`,
active-print liquidity gate, exact next-bar open. Eight non-AMC assets
(`SPY, TSLA, GME, U, RBLX, PYPL, LULU, VALE`), 384 anchors, four pre-registered
controls, per-asset + asset-balanced pooled gates.

`options_dna_replication.py` implements the deterministic evaluation (candidate
+ 4 controls, per-asset minimums, direction preservation, control superiority,
countertarget audit, asset-cluster bootstrap, promotion gate). 14 tests cover
the frozen constants, dataset join/labeling, contract selection, and
enriching/non-enriching/failed scenarios.

## Replication execution status (updated 2026-08-15, post-fetch)

- `R0_PLAN_ONLY` artifacts complete: `PROTOCOL.md`,
  `acceptance_criteria_v1.json`, `anchor_plan.csv` (384 anchors),
  `manifest.json`, `request_budget.json`, `position_replay_coverage_protocol.md`.
- Execution scripts built and network-free until `--fetch`:
  `scripts/build_options_dna_replication.py` (fetch),
  `scripts/assemble_options_dna_replication.py` (assemble),
  `scripts/evaluate_options_dna_replication.py` (evaluate).
- **Fetch executed** in the authorized DeepSeek environment:
  `manifest.json` status `FETCHED_WITH_FAILURES` — 370/384 anchors resolved
  to a cohort row (14 failures: 7 `SPY` rate-limit exhaustions on the
  `contracts` stage, 7 `no CALL/14 regular contract within DTE tolerance`
  selection failures across `LULU`, `GME`, `RBLX`, `U`). 337 unique tickers,
  350 reference requests, 337 option-bar requests, 0 cache hits.
- **Assemble executed**: 370 component rows, 370 outcome rows, 1,850
  window-outcome rows, 196 quality-rejection rows, 8 coverage cells.
- **Evaluate executed**: `replication_evaluation.json`,
  `replication_status: EXTERNAL_REPLICATION_NOT_CONFIRMED`, `pooled_pass:
  false`, `promotion_forbidden: true`, `passing_assets: []` (0 of 8),
  `assets_with_direction: 2` (GME, TSLA). See
  `TOMORROW_REAL_TEST_READINESS.md` for the full per-asset breakdown,
  control results, and cluster-bootstrap evidence.
- **Root cause of the non-confirmation**: the frozen candidate condition
  (`contract__close_location <= 0.3333` AND `underlying__campaign_health <=
  31.6`) fires on only **14 of 228 scored anchors** (4 weighted holdout
  groups total across all 8 assets: GME 2, SPY 1, TSLA 1). Two assets show a
  positive holdout lift (GME +3.75, TSLA +7.0) but fail the remaining gates
  (GME fails the countertarget audit; TSLA has only 1 active-print triggered
  holdout group, below the required 3). Four assets are below the frozen
  per-asset sample minima (LULU, RBLX, U, VALE). The asset-balanced pooled
  lift is 0.72 (< 1.0) with cluster-bootstrap `prob_above_one: 0.32`. The
  candidate is a rare, low-coverage rule that does not generalize externally;
  no threshold was refit in response.

## Position-replay coverage (frozen finding)

After the 70-anchor supplement (162 total), all eight isolated-entry cells pass.
Open-position replay remains structurally incomplete: `DISCOVERY PUT/30` is
5/20 and `HOLDOUT PUT/14` is 6/10 — an AMC PUT liquidity limitation, not a
pipeline defect. Entry-only target-freeze is authorized; all position-management
/ exit / roll guidance stays blocked. The liquidity-aware multi-asset coverage
protocol is drafted at `position_replay_coverage_protocol.md` (design only).

## Next steps

1. ~~Run `python3 scripts/build_options_dna_replication.py --fetch` in the
   authorized environment, then assemble and evaluate.~~ Done 2026-08-15.
2. ~~Report the per-asset + pooled replication result against the frozen
   gates; do not fit thresholds or relax minima on failure.~~ Done — see
   `TOMORROW_REAL_TEST_READINESS.md`. Result: `EXTERNAL_REPLICATION_NOT_
   CONFIRMED`, promotion forbidden, no threshold refit performed.
3. Keep position-management/exit guidance blocked until its cells pass.
4. No further replication action is authorized under the frozen protocol:
   refitting the candidate on this data would violate the no-refit boundary.
   Any next iteration requires a newly pre-registered candidate/threshold
   set treated as a fresh, unproven hypothesis — not a patch to this one.
