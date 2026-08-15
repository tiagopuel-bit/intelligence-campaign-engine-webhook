# DeepSeek Handoff — Options DNA AMC 15m Pilot

## Objective

Execute the bounded provider-data portion of the Options DNA calibration loop.
Do not design guidance thresholds yet. The immediate result is a verified,
causally aligned AMC option-contract cohort that can be scored against the
already-audited underlying DNA replay.

## Authority and boundaries

- You own Massive API execution and data-quality verification for this stage.
- Use the existing free-plan integration and configured Railway/provider
  credentials. Never print, return, persist or commit a credential.
- Do not modify the dashboard, webhook routes, position database, SEC poller,
  Pine, DNA production engine, alerts or deployment configuration.
- Do not upgrade a plan or use paid-only snapshots, Greeks, IV, quotes or OI.
- Do not synthesize missing option bars. Massive documents an empty interval as
  no qualifying option trade; preserve it as missing.
- No entry/exit recommendation or combined Options DNA score in this stage.

## Frozen local inputs

- Protocol: `docs/OPTIONS_DNA_CALIBRATION_PROTOCOL.md`
- Component ledger: `options_dna.py`
- Cohort/outcome helpers: `options_dna_research.py`
- Acquisition contract: `options_dna_dataset.py`
- Runner: `scripts/build_options_dna_dataset.py`
- Plan: `reports/options_dna_pilot/anchor_plan.csv`
- Manifest: `reports/options_dna_pilot/manifest.json`
- Audited replay source:
  `../_deepseek_expanded_rerun_stage/audited_output/replay/AMC_events_15m.csv.gz`
- Frozen replay SHA-256:
  `a0a26ce9f70a0da75436c0065bebe374d52af5220c8dfdecd43c02c3e1ac5edc`

The pilot contains 16 anchors: two per evidence family in discovery and two
per family in holdout. Each anchor requests standard ATM CALL and PUT cohorts
near 14, 30 and 60 DTE. The maximum theoretical anchor-contract count is 96,
but repeated contracts should be fetched once and reused.

## Required execution

1. Re-run the network-free plan and verify the replay hash and 16-anchor
   balance before any provider call:

   ```bash
   python3 scripts/build_options_dna_dataset.py
   ```

2. Audit the `--fetch` implementation against the current Massive API contract.
   Corrections are allowed only in the Options DNA research files and tests.
   Preserve the five-requests-per-minute shared limiter and resumable per-ticker
   cache.

3. Run the bounded pull in the environment where `MASSIVE_API_KEY` is already
   configured:

   ```bash
   python3 scripts/build_options_dna_dataset.py --fetch
   ```

4. If the earliest anchor is outside the provider entitlement on execution
   day, record it as left-censored. Do not silently move it or replace it.

5. Join every option bar only to the identical audited underlying 15m bar-open
   timestamp. `decision_available_utc` is the first time the event is knowable;
   forward outcomes must begin after it, never at `signal_bar_open_utc`.

6. For every selected contract, run `options_dna.component_ledger` through its
   available bars and record:
   - matched bar count and activity ratio;
   - every explicit quality-rejection reason;
   - coverage before/at/after the anchor;
   - whether the signal bar exists;
   - right/left censoring;
   - optional `vw`/`n` availability without requiring either field.

7. Keep factual components separate from forward targets. Forward targets may
   include next-bar-open MFE/MAE, decision-close MFE/MAE, terminal premium
   return, signal-close gap, bars to premium peak/trough, peak-before-trough,
   peak-to-terminal giveback and gain retention. Use
   `forward_long_premium_path_outcome`; all fields must remain clearly labeled
   research-only/future information.

8. Run all tests. At minimum:

   ```bash
   PYTHONPYCACHEPREFIX=/tmp/options_dna_ds_pycache \
     python3 -m unittest tests.test_options_dna \
       tests.test_options_dna_research tests.test_options_dna_dataset -v
   ```

9. Before reporting completion, run the provider-neutral acceptance gate:

   ```bash
   python3 scripts/audit_options_dna_pilot.py
   ```

   Exit 0 means the artifact set is ready for human/research review, not that
   any navigation threshold is validated. Exit 2 means acquisition or derived
   ledgers are still incomplete; exit 1 means a structural fidelity error was
   found. Signal-bar absence is recorded as sparse-activity evidence and is not
   filled or silently moved.

## Required outputs

Write only beneath `reports/options_dna_pilot/` (plus narrowly scoped research
code/tests if a verified correction is needed):

- `cohort_ledger.csv`
- `component_ledger.csv.gz`
- `forward_outcomes.csv`
- `coverage_by_cell.csv`
- `quality_rejections.csv`
- `failures.json`
- updated `manifest.json`
- `DEEPSEEK_EXECUTION_REPORT.md`

The execution report must state:

1. exact commands and test results;
2. provider entitlement observed, with no secret values;
3. request count, unique ticker count and cache reuse count;
4. anchors/cohorts planned vs acquired;
5. coverage by discovery/holdout, family, CALL/PUT and DTE cell;
6. missing/sparse/censored cases;
7. exact causal timestamp proof for at least one anchor;
8. all files changed;
9. confirmation that production/runtime were untouched.

## Stop condition

Stop after the verified data/feature ledger. Do not calibrate HOT, WEAK,
ENTRY WINDOW, MANAGE, PROTECT or EXIT WINDOW thresholds until this cohort is
reviewed and explicitly accepted.
