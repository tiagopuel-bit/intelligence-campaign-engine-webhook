# DeepSeek handoff — Options DNA entry-only calibration

## Calibration-review decision

The 162-anchor combined acquisition passes all eight isolated-entry cells but
does not pass the frozen position-replay gate. Proceed with an **entry-only**
research track. Do not fit, label, imply or promote open-position management,
protect, reduce, roll or exit guidance.

This is a scope split caused by timestamp/liquidity coverage, not by observed
returns. The six v1 semantic target hypotheses were frozen before outcomes.
Their numeric cutoffs may now be frozen from eligible DISCOVERY entry paths and
applied unchanged to HOLDOUT entry paths.

## Evidence boundary

Isolated-entry coverage passes:

| partition | CALL/14 | CALL/30 | PUT/14 | PUT/30 |
|---|---:|---:|---:|---:|
| DISCOVERY | 90 | 74 | 63 | 31 |
| HOLDOUT | 32 | 33 | 20 | 18 |

Position replay remains blocked:

| partition | CALL/14 | CALL/30 | PUT/14 | PUT/30 |
|---|---:|---:|---:|---:|
| DISCOVERY | 55 | 41 | 24 | 5 |
| HOLDOUT | 19 | 21 | 6 | 10 |

Only CALL/14 and CALL/30 pass both partitions for position replay. Neither PUT
maturity has a complete Discovery+Holdout seal. Do not call position replay
"6/8 ready" without this paired-cell qualification.

## Checkpoint A — implement a separate entry-only freeze stage

Preserve `run_target_freeze_stage()` and its all-track fail-closed behavior.
Add a separate entry-only function/CLI whose gate requires:

- artifact status `READY_FOR_REVIEW`;
- `calibration_coverage_ready == true`;
- no requirement that `position_replay_coverage_ready` be true;
- the frozen input hashes for `cohort_ledger.csv`,
  `component_ledger.csv.gz`, `future_target_matrix.csv`,
  `catalyst_ledger.csv` and the acquisition `manifest.json`.

The entry-only stage must:

1. build only the entry calibration dataset;
2. exclude rows not explicitly `calibration_eligible == true`;
3. freeze the six predeclared v1 target definitions using DISCOVERY only;
4. apply the definitions unchanged to HOLDOUT;
5. write to `reports/options_dna_expansion/entry_calibration_v1/`;
6. export causal features and future labels into physically separate files;
7. record `scope: OBSERVE_ENTRY`, `rules_fitted: false`,
   `guidance_emitted: false`, and
   `position_management_status: BLOCKED_INSUFFICIENT_REPLAY_COVERAGE`;
8. reject input changes after the freeze by hash.

Do not use the existing all-track CLI to bypass its position gate. Do not
write empty position files that imply position calibration occurred.

Stop after Checkpoint A and report the numeric target definitions, per-cell
eligible counts, censoring exclusions, file hashes, tests and changed files.
Numeric targets remain research-only and must not enter the dashboard or a
live observation.

## Checkpoint B — entry candidate search, only after review

### Checkpoint A review decision — PASS

Independent review confirmed 361 eligible entry rows, exact causal/future file
separation, immutable source hashes, the entry-only gate, and the unchanged
all-track position gate. The full test suite passes 253/253. Checkpoint B is
authorized under the restrictions below.

Search only the predeclared entry scopes:

- `EARLY_PREMIUM_CONFIRMATION`;
- `CONFIRMATION_FAILURE`;
- `RETAINED_EXPANSION`.

Candidate conditions are selected on DISCOVERY only and evaluated unchanged on
HOLDOUT. Report every searched candidate, preservation status and countertarget
audit, including null results. Require CALL/PUT and 14/30-DTE evidence unless a
candidate is explicitly cell-restricted. No broad candidate may borrow support
from a different contract cell.

Implement a separate entry-only rule-search function/CLI. Preserve the existing
all-track `run_rule_stage()` gate and search plan. The new stage must accept only
an `ENTRY_TARGET_FREEZE_ONLY` manifest with `scope: OBSERVE_ENTRY`, validate its
input hashes, join only `entry_causal.csv.gz` and
`entry_future_labels.csv.gz`, and search only the three entry targets above. It
must not read or emit position-management artifacts.

Before interpreting preserved candidates, publish by partition and contract
cell: target base rate, scored groups, positive groups, triggered groups, and
unchanged/zero-return print incidence. In particular, PUT/30 has frozen zero
cutoffs in parts of `EARLY_PREMIUM_CONFIRMATION`; this is a valid frozen label,
but not automatically evidence of a responsive contract. Run an additive
active-print sensitivity audit using the already-causal activity, volume,
coverage and range fields. Do not change the frozen target or refit on this
subset. A candidate whose apparent enrichment disappears when inactive prints
are identified must be reported as `LIQUIDITY_SENSITIVE` and cannot advance.

Even a passing candidate remains research-only and, at most, eligible for the
existing frozen live-shadow process. It cannot emit exact trade prices,
quantities, orders or production guidance.

### Checkpoint B independent review — CORRECTION REQUIRED

The first Checkpoint B run is methodologically useful but is not yet eligible
for shadow promotion. Preserve its outputs as a preliminary audit and correct
these issues without changing the frozen targets or inspecting new outcomes:

1. `audit_liquidity_sensitivity()` currently labels every candidate from the
   presence of a zero target cutoff. That is a cutoff heuristic, not the
   requested active-print sensitivity analysis. Emit the promised partition ×
   contract-cell base rates, scored/positive/triggered groups and unchanged
   print incidence. Re-evaluate each frozen candidate on a deterministic causal
   active-print slice using the existing activity, volume, option-return and
   range fields. If that slice has fewer than the frozen group/trigger minima,
   report `INSUFFICIENT_ACTIVE_PRINT_COVERAGE`; never call it supported.
2. Deduplicate candidates by their triggered independent-anchor fingerprint in
   DISCOVERY and HOLDOUT. Six CALL/14 survivors reduce to only two distinct
   HOLDOUT fingerprints; five fire on the same three holdout anchors. Report
   signal families, not six independent confirmations.
3. A required evidence root must contribute discrimination. Conditions such as
   `close_location <= 1` and `close_location >= 0` are tautological over valid
   bars and cannot satisfy the contract-evidence requirement. Reject a
   candidate when removing its contract condition leaves the same triggered
   independent groups, and add a deterministic test.
4. The current CALL/14 survivors have only three or four triggered holdout
   anchors. Report this fragility prominently and do not describe them as ready
   for live shadow until the corrected active-print audit and equivalence
   collapse pass. No threshold, candidate condition or target may be refit.

Stop again after rewriting the Checkpoint B artifacts and tests. Report both
the original candidate count and the number of unique, non-tautological,
active-print-supported signal families. A valid null result is acceptable.

### Checkpoint B corrected-run review — ONE BUG REMAINS

The causal active-print audit, tautology rejection and historical validation
now behave as intended, but the fingerprint implementation is not cell-scoped.
`_triggered_fingerprint()` currently filters only partition and conditions. It
must also filter to the candidate's `contract_type`, `dte_target`, target name,
required `*_status == SCORED_FROZEN_DISCOVERY_CUTOFFS`, and non-empty group
identity. Pass the candidate rather than only its conditions.

This bug makes the narrative count wrong: the surviving CALL/14 candidate's
frozen validation reports four full-sample HOLDOUT triggers, and the causal
active-print audit reports three active HOLDOUT triggers. The reported list of
five anchors includes rows outside the exact candidate evaluation cell and may
not be used.

Add a regression fixture containing the same anchor across another DTE and/or
contract type and prove it cannot enter the fingerprint. Re-run the artifacts,
emit `supported_signal_families.json` with the exact cell-scoped Discovery and
Holdout anchor IDs, and report the full-sample and active-print trigger counts
separately. Also replace ambiguous manifest wording with:

- `holdout_used_for_candidate_generation: false`;
- `holdout_used_for_validation: true`;
- `holdout_used_for_promotion: false`.

Do not start shadow observation yet. Stop after this deterministic correction.

### Final Checkpoint B review — RESEARCH FINDING, NOT SHADOW-ELIGIBLE

The cell-scoped correction passes. The surviving family is
`CONFIRMATION_FAILURE`, CALL/14, with `contract__close_location <= 0.333333...`
and `underlying__campaign_health <= 31.6`. It has nine Discovery triggers,
four full-sample Holdout triggers, and three active-print Holdout triggers.

The exact Holdout membership is:

- active/scored: `AMC15X-063`, `AMC15X-064`, `AMC15SUP-051`;
- scored but unchanged print: `AMC15X-084`.

`AMC15X-092`, not `AMC15SUP-051`, is the unscored row excluded by the corrected
fingerprint. Correct this prose in any generated report; the machine-readable
family counts are already correct.

Do not build a shadow bundle from this family. It rests at the three-trigger
active-print minimum and has Discovery rank 12, outside the pre-registered
`max_discovery_rank=3` promotion boundary. The frozen four-cell shadow gate also
cannot be satisfied by a CALL/14-only rule. Lowering or bypassing either gate
after seeing this result is prohibited.

Record the result as `HISTORICAL_RESEARCH_FINDING_NEEDS_EXTERNAL_REPLICATION`.
The next evidence step is a separately pre-registered multi-asset replication
study. The candidate conditions, target semantics, activity definition and
accept/reject criteria must be frozen before inspecting the new assets. No AMC
refit, production guidance or Asset Page wording is authorized.

## Position-management next study

Do not request another ordinary AMC supplement. The Discovery PUT/30 yield
improved from 2 to 5 despite 40 added discovery entry-origin anchors, confirming
the predeclared structural-liquidity warning.

Prepare a separate, pre-registered multi-asset position-replay protocol later.
It must define assets, liquidity eligibility, chronological partitions,
contract selection, execution and per-asset/generalization tests before new
outcomes are inspected. Sparse AMC contracts should be allowed to resolve to
`CONTRACT_DATA_UNRELIABLE` rather than receiving borrowed PUT exit guidance.

## Prohibited changes

- no lowered independent-event minima;
- no delayed or synthetic fills;
- no future-print contract selection;
- no pooling PUT/14 and PUT/30 after seeing the deficit;
- no pooling Discovery and Holdout;
- no CALL rule presented as PUT evidence;
- no production, Pine, webhook ingestion, dashboard, Railway or alert changes.
