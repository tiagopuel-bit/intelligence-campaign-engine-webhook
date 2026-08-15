# DeepSeek Handoff — AMC Options DNA Calibration Expansion

The 16-anchor pilot is accepted for timestamp/schema fidelity only. It cannot
calibrate guidance. Execute this expansion using the existing Massive free-plan
integration and shared limiter; do not change production, Railway, UI, webhook,
Pine, alerts or secrets.

## Frozen corrections from the pilot

- Exact option `signal_bar_open_utc` is required for a causal component and
  path outcome. Never shift to the next printed option bar.
- The signal bar becomes knowable at `decision_available_utc`.
- Pass full underlying history into `component_ledger`; option activity must be
  measured against the actual underlying bar grid.
- Use `forward_long_premium_path_outcome`, never the close-only helper.
- Missing signal bars are `UNSCORED_SIGNAL_BAR_ABSENT`, not right-censored.
- Future path fields stay exclusively in `forward_outcomes.csv`.

## Plan

Generate and inspect the network-free plan:

```bash
python3 scripts/plan_options_dna_expansion.py
```

Expected plan: 92 balanced anchors—60 DISCOVERY (15 per evidence family) and
32 HOLDOUT (8 per family)—with the same 2026-02-01 chronological seal.

Acquire CALL/PUT contracts near 14 and 30 DTE. Drop the empty 60-DTE target.
For AMC's coarse strike ladder, first use the frozen ±7.5% ATM rule; if no
regular 100-share contract qualifies, take the nearest regular strike and mark
`selection_policy=NEAREST_REGULAR_STRIKE`. Always retain actual moneyness,
distance and band. Do not describe a fallback contract as ATM.

Cache reference chains by `session_date` and aggregate bars by ticker so free
plan requests are not repeated. Use only credentials already configured in the
DeepSeek environment; never print or persist them.

Execute the resumable pull and then the corrected network-free assembly:

```bash
python3 scripts/build_options_dna_expansion.py --fetch
python3 scripts/assemble_options_dna_ledger.py \
  --output reports/options_dna_expansion
python3 scripts/build_options_dna_target_matrix.py \
  reports/options_dna_expansion
python3 scripts/build_options_dna_position_replay.py \
  --output reports/options_dna_expansion
python3 scripts/build_options_dna_catalyst_ledger.py \
  --anchors reports/options_dna_expansion/anchor_plan.csv \
  --filings reports/options_dna_expansion/sec_filing_source.json \
  --output reports/options_dna_expansion
python3 scripts/build_options_dna_catalyst_ledger.py \
  --anchors reports/options_dna_expansion/position_snapshot_anchor_plan.csv \
  --filings reports/options_dna_expansion/sec_filing_source.json \
  --output reports/options_dna_expansion \
  --prefix position_catalyst
python3 scripts/audit_options_dna_pilot.py \
  reports/options_dna_expansion --require-calibration-coverage
```

The acquisition helper verifies that a cached ticker covers the full union of
all anchor windows before reusing it. A narrower cache is refetched rather than
silently reused.

The SEC source file is a separate, network-independent input to the final
builder. It must declare its clock coverage rather than implying that an empty
filing list means no catalyst:

```json
{
  "source": "sec-submissions-and-archives",
  "as_of_utc": "2026-08-14T00:00:00Z",
  "coverage": {
    "PUBLIC_ACCEPTANCE": {
      "complete": true,
      "start_utc": "2024-08-01T00:00:00Z",
      "end_utc": "2026-08-14T00:00:00Z"
    },
    "OPERATIONAL_SEEN": {
      "complete": false,
      "start_utc": null,
      "end_utc": null
    }
  },
  "filings": []
}
```

Populate `filings` with the same normalized fields used by `sec_filings.py`.
Historical backfill must cover `PUBLIC_ACCEPTANCE` across every anchor. Only
declare `OPERATIONAL_SEEN` coverage for a period when the real poller was
running and genuine `first_seen_at` values exist. Never synthesize historical
poll times. The builder is network-free and emits `SOURCE_UNAVAILABLE` rather
than converting incomplete coverage into a false catalyst-negative row.

## Acceptance gates

After exact-signal filtering, require at least:

- 20 independent DISCOVERY anchors in every CALL/PUT × 14/30-DTE cell;
- 10 independent HOLDOUT anchors in every such cell;
- separate coverage by evidence family and moneyness band;
- explicit zero-cohort, missing-signal, sparse, and censored ledgers;
- the provider-neutral structural gate at exit 0.

If any comparable cell misses its minimum, report the deficit and stop. Do not
fit outcome labels or feature thresholds. More contracts from one anchor never
increase independent-event counts.

The audit exits 3 when the artifacts are structurally reviewable but any
frozen independent-event minimum remains unmet.

## Required outputs

Write under `reports/options_dna_expansion/`:

- `anchor_plan.csv`, `manifest.json`, `cohort_ledger.csv`;
- `component_ledger.csv.gz`, `forward_outcomes.csv`;
- `forward_outcome_windows.csv` for H1/D1/D3/D5/D10 underlying-clock paths;
- `future_target_matrix.csv`, `target_hypotheses_v1.json` (future-only);
- `position_episode_ledger.csv`, `position_snapshot_ledger.csv.gz` (causal);
- `position_snapshot_anchor_plan.csv`, `position_catalyst_ledger.csv`,
  `position_catalyst_manifest.json`;
- `position_snapshot_outcome_windows.csv` (future-only),
  `position_future_target_matrix.csv`, `position_snapshot_rejections.csv`,
  `position_replay_manifest.json`;
- `sec_filing_source.json`, `catalyst_ledger.csv`, `catalyst_manifest.json`;
- `coverage_by_cell.csv`, `quality_rejections.csv`, `failures.json`;
- `DEEPSEEK_EXECUTION_REPORT.md`.

Preserve the planner-generated `shadow_acceptance_criteria_v1.json` and the
matching `shadow_acceptance_design` hashes in `manifest.json`. This file is
frozen before expansion outcomes and is not a provider output or a threshold
for DeepSeek to tune.

Stop after acquisition, causal assembly, tests and coverage verification. No
HOT/WEAK/ENTRY/MANAGE/PROTECT/EXIT wording or thresholds in this stage.

The position replay is mandatory because isolated signal cohorts cannot test
navigation for an already-open contract. It may open only ENTRY_FORMING or
CONTINUATION episodes with an option aggregate exactly at the decision
timestamp; that bar's open is the research entry proxy. It follows the same
contract for 21 calendar days at exact later DNA event bars. Never shift a
missing entry or snapshot to a later print. Require 20 independent ready
DISCOVERY episodes and 10 HOLDOUT episodes in each CALL/PUT × 14/30-DTE cell.
Snapshots are causal and future path windows remain in a separate artifact.
