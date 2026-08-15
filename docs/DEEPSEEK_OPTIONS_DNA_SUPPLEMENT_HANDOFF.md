# DeepSeek handoff — Options DNA exact-execution coverage supplement

## Boundary

The 92-anchor expansion is structurally accepted but below frozen coverage
minimums. This supplement is coverage-only. Do not fit thresholds, inspect
future labels to choose anchors, relax exact timestamps, change the holdout
date, alter the contract-selection policy, or touch production/UI/runtime.

The base evidence remains identifiable in `anchor_plan_base_v1.csv` and the
supplement metadata embedded in `manifest.json`. The supplement selects only
unused `ENTRY_FORMING` and `CONTINUATION` underlying events because those are
the only permitted origins for simulated open-position episodes.

## Why 70 anchors

Add 20 anchors per entry family in DISCOVERY and 15 per entry family in
HOLDOUT: 40 discovery + 30 holdout. Selection is deterministic and evenly
spaced inside the unchanged 2026-02-01 chronological seal. It uses no option
availability or future outcome.

Based only on observed missingness/execution coverage, this should clear the
two isolated-entry deficits and likely clear every position cell except
DISCOVERY PUT/30. That cell currently has 2/20 exact episodes; the observed
yield implies ordinary anchor expansion may be structurally insufficient.
This is a feasibility warning, not permission to lower the gate.

## Commands

From the webhook repository:

```bash
PYTHONPYCACHEPREFIX=/tmp/options_dna_supplement_pycache \
  python3 -m unittest tests.test_options_dna_supplement -v

# Read-only preview. Confirm 70 additions and base hash.
python3 scripts/plan_options_dna_supplement.py

# Explicitly freeze/apply the combined 162-anchor plan.
python3 scripts/plan_options_dna_supplement.py --apply

# Resumable fetch reuses the existing reference/bar caches.
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

Run the full test suite and `git diff --check` after assembly.

## Required checkpoint

Report:

1. base/supplement/combined anchor counts and hashes;
2. new vs cached provider-request counts;
3. isolated-entry coverage for all eight partition/type/DTE cells;
4. exact position-episode coverage for all eight cells;
5. rejection counts by reason;
6. whether DISCOVERY PUT/30 remains structurally deficient;
7. exact commands and test count;
8. changed files and confirmation that production/runtime were untouched.

If any cell remains deficient, stop. Do not create a delayed-fill arm, choose
contracts by their future prints, reduce minimums, fit targets/rules, or emit
guidance. The next design decision belongs to the calibration review.
