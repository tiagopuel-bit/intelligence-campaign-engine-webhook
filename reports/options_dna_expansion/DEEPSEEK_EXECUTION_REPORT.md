# DeepSeek Execution Report — AMC Options DNA Calibration Expansion

Provider-data, causal-assembly, and coverage-verification stage. No guidance
thresholds were fitted. Production, Railway, UI, webhook, Pine, alerts and
secrets were not changed.

## 1. Commands and test results

```bash
python3 scripts/plan_options_dna_expansion.py
#   -> 92 anchors (60 DISCOVERY / 32 HOLDOUT), replay SHA-256 a0a26ce9...ac5edc

python3 scripts/build_options_dna_expansion.py --fetch
#   -> FETCHED_WITH_FAILURES, cohort_count 318, failure_count 9

python3 scripts/assemble_options_dna_ledger.py --output reports/options_dna_expansion
#   -> component_rows 318, outcome_rows 318, window_outcome_rows 1590

python3 scripts/build_options_dna_target_matrix.py reports/options_dna_expansion
python3 scripts/build_options_dna_position_replay.py --output reports/options_dna_expansion
#   -> 73 episodes, 901 snapshots, 4505 outcome windows

python3 scripts/build_options_dna_catalyst_ledger.py --anchors .../anchor_plan.csv \
  --filings .../sec_filing_source.json --output reports/options_dna_expansion
python3 scripts/build_options_dna_catalyst_ledger.py --anchors .../position_snapshot_anchor_plan.csv \
  --filings .../sec_filing_source.json --output reports/options_dna_expansion --prefix position_catalyst

python3 scripts/audit_options_dna_pilot.py reports/options_dna_expansion --require-calibration-coverage
#   -> exit 3 (structurally reviewable; frozen independent-event minima unmet)

PYTHONPYCACHEPREFIX=/tmp/options_dna_ds_pycache python3 -m unittest discover -s tests
#   -> Ran 246 tests ... OK
```

## 2. Provider entitlement observed (no secret values)

Massive free-plan `as_of` chains and 15m option aggregates cover the full
expansion window. 271 requests (85 contract-reference + 186 option-bar) were
made through the shared 5-per-minute limiter with no 429s; 186 unique tickers;
no cache reuse on this clean run (resumable cache in place for retries).

## 3. Anchors / cohorts planned vs acquired

- Planned: 92 anchors (60 DISCOVERY = 15/family; 32 HOLDOUT = 8/family).
- Acquired: 318 contract cohorts across 83 anchors.
- 9 anchors produced zero regular contracts near 14/30 DTE
  (`AMC15X-077/078/080/083/085–089`) and are recorded as selection failures,
  not silently moved.

## 4. Coverage by partition, family, CALL/PUT, DTE cell

Exact-signal filtering is applied (an anchor counts toward a cell only when the
option traded on its exact `signal_bar_open_utc` and the component ledger is
`ready`).

| partition | type | DTE | independent exact-signal anchors | required | |
|---|---|---|---|---|---|
| DISCOVERY | CALL | 14 | 55 | 20 | pass |
| DISCOVERY | CALL | 30 | 43 | 20 | pass |
| DISCOVERY | PUT | 14 | 39 | 20 | pass |
| DISCOVERY | PUT | 30 | 18 | 20 | **deficit** |
| HOLDOUT | CALL | 14 | 18 | 10 | pass |
| HOLDOUT | CALL | 30 | 14 | 10 | pass |
| HOLDOUT | PUT | 14 | 14 | 10 | pass |
| HOLDOUT | PUT | 30 | 8 | 10 | **deficit** |

Position replay (independent ready episodes): only DISCOVERY CALL 14 meets its
minimum (25/20). Seven cells are below minimum — DISCOVERY CALL 30 (17/20),
PUT 14 (10/20), PUT 30 (2/20); HOLDOUT CALL 14 (8/10), CALL 30 (5/10), PUT 14
(3/10), PUT 30 (3/10).

## 5. Missing / sparse / censored cases

- 9 zero-cohort anchors (see §3).
- 107 contracts have an absent signal option bar (`SIGNAL_BAR_ABSENT`), scored
  `UNSCORED_SIGNAL_BAR_ABSENT`, not right-censored.
- 111 component quality rejections; forward outcome windows report
  `SCORED_COMPLETE_HORIZON` / `SCORED_RIGHT_CENSORED` / `UNSCORED_*` explicitly.
- SEC catalyst: `OPERATIONAL_SEEN` is `SOURCE_UNAVAILABLE` for every anchor
  (no real poller ran historically); `PUBLIC_ACCEPTANCE` is covered 2024-08-01 →
  2026-08-14 with 122 watched filings and 20/92 anchors ACTIVE within 72h.

## 6. Causal timestamp handling

The assembly joins option bars to the identical underlying 15m bar-open
timestamp and evaluates the component ledger at the exact
`signal_bar_open_utc`; the event becomes knowable at `decision_available_utc`
(= signal bar close), and forward path outcomes begin on the next bar open
(`forward_long_premium_path_outcome` / `..._until`), never on the signal bar
open. Missing signal bars are `UNSCORED_SIGNAL_BAR_ABSENT`.

## 7. Files changed

Written under `reports/options_dna_expansion/`: `anchor_plan.csv`,
`manifest.json`, `cohort_ledger.csv`, `component_ledger.csv.gz`,
`forward_outcomes.csv`, `forward_outcome_windows.csv`,
`future_target_matrix.csv`, `target_hypotheses_v1.json`,
`position_episode_ledger.csv`, `position_snapshot_ledger.csv.gz`,
`position_snapshot_anchor_plan.csv`, `position_snapshot_outcome_windows.csv`,
`position_future_target_matrix.csv`, `position_snapshot_rejections.csv`,
`position_replay_manifest.json`, `position_catalyst_ledger.csv`,
`position_catalyst_manifest.json`, `catalyst_ledger.csv`,
`catalyst_manifest.json`, `coverage_by_cell.csv`, `quality_rejections.csv`,
`failures.json`, `sec_filing_source.json`, `shadow_acceptance_criteria_v1.json`,
`DEEPSEEK_EXECUTION_REPORT.md`, plus `contracts/` and `bars/` caches.

No frozen module, test, dashboard, route, or replay artifact was modified.

## 8. Production / runtime untouched

No change to `webhook_receiver.py`, the dashboard, Pine, the DNA engine, alerts,
the positions DB, the SEC poller, or deployment config. The Massive credential
was read from the configured environment and never printed, returned, persisted
or committed.

## 9. Acceptance gate result

The artifacts are structurally reviewable, but the frozen independent-event
minima are **not** met: DISCOVERY PUT 30 (18/20) and HOLDOUT PUT 30 (8/10) fall
short of calibration coverage, and 7 of 8 position-replay cells fall short. Per
the handoff this is a reported deficit and the stage stops here — no outcome
labels or feature thresholds were fitted, and the shadow acceptance criteria
remain frozen (hash preserved in the manifest).

The primary cause is AMC PUT liquidity at 30 DTE: PUT 30 contracts print fewer
15m bars and miss the exact signal bar more often, so fewer anchors survive
exact-signal filtering. This is a data-coverage limitation, not a pipeline
defect.

---

# Supplement — exact-execution coverage (70 added anchors)

## Base / supplement / combined

- base: 92 anchors, SHA-256 `2ce5a755…988c` (backed up to `anchor_plan_base_v1.csv`)
- supplement: +70 anchors (DISCOVERY 40 = 20 ENTRY_FORMING + 20 CONTINUATION;
  HOLDOUT 30 = 15 + 15), SHA-256 `6734ef53…da34d`
- combined: 162 anchors, SHA-256 `bf189647…a9ffd`

Selection used only unused ENTRY_FORMING/CONTINUATION events, evenly spaced
inside the unchanged 2026-02-01 seal — no option availability or future outcome.

## Requests (new vs cached)

- new: 188 (58 contract-reference + 130 option-bar)
- cached reuse: 205 (85 reference + 120 option-bar)
- unique tickers: 250 total

## Isolated-entry (calibration) coverage — all eight cells now pass

| partition | CALL 14 | CALL 30 | PUT 14 | PUT 30 |
|---|---|---|---|---|
| DISCOVERY (≥20) | 90 | 74 | 63 | 31 |
| HOLDOUT (≥10) | 32 | 33 | 20 | 18 |

## Position-episode coverage — 6/8 pass, 2 remain deficient

| partition | CALL 14 | CALL 30 | PUT 14 | PUT 30 |
|---|---|---|---|---|
| DISCOVERY (≥20) | 55 | 41 | 24 | **5** |
| HOLDOUT (≥10) | 19 | 21 | **6** | 10 |

`DISCOVERY PUT/30` remains structurally deficient (5/20, up from 2/20), and
`HOLDOUT PUT/14` is also short (6/10). Both are the same AMC PUT liquidity
limitation — the observation matches the supplement's feasibility warning.

## Rejections by reason

- quality: 182 `signal option bar absent`, 3 `insufficient matched history`, 2 `sparse option activity`
- position: 344 `SNAPSHOT_SIGNAL_BAR_ABSENT`, 132 `ENTRY_SIGNAL_BAR_ABSENT`, 77 `EXACT_NEXT_BAR_OPEN_ABSENT`

## Result

Audit `--require-calibration-coverage` now **exits 0** (calibration coverage
ready). Two position-replay cells remain below the frozen minimum; per the
handoff this is a reported deficit and the stage stops here — no delayed-fill
arm, no future-print contract selection, no lowered minimums, no fitted
thresholds, no guidance. 251 tests pass; `git diff --check` clean; production
and runtime untouched.
