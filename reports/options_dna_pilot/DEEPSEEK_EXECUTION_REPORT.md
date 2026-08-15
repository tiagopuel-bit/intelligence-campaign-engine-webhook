# DeepSeek Execution Report — Options DNA AMC 15m Pilot

> **Independent audit correction:** The original assembly facts below were
> generated before the exact-signal/path-outcome correction. The authoritative
> current interpretation is `INDEPENDENT_ACCEPTANCE_AUDIT.md`. Current ledgers
> contain 11 signal-bar rejections (not 3), 33 scored next-open/high-low path
> outcomes, and 11 `UNSCORED_SIGNAL_BAR_ABSENT` rows. No calibration is allowed.

Provider-data stage only. No thresholds were calibrated; the verified cohort is
the deliverable. Production code, routes, the position DB, the SEC poller, Pine
and the DNA engine were not modified.

## 1. Commands and test results

```bash
# step 1 — network-free plan (no provider calls)
python3 scripts/build_options_dna_dataset.py
#   -> anchor_count 16, replay SHA-256 a0a26ce9...ac5edc (matches frozen)

# step 3 — bounded provider pull (MASSIVE_API_KEY from the configured env)
python3 scripts/build_options_dna_dataset.py --fetch
#   -> status FETCHED, failure_count 0, cohort_count 44

# step 4-7 — assembly (component ledger, forward outcomes, coverage, rejections)
python3 scripts/assemble_options_dna_ledger.py
#   -> component_rows 44, outcome_rows 44, rejection_rows 3, coverage_cells 32

# step 8 — tests
PYTHONPYCACHEPREFIX=/tmp/options_dna_ds_pycache \
  python3 -m unittest tests.test_options_dna \
    tests.test_options_dna_research tests.test_options_dna_dataset -v
#   -> Ran 16 tests ... OK

PYTHONPYCACHEPREFIX=/tmp/options_dna_ds_pycache python3 -m unittest discover -s tests
#   -> Ran 164 tests ... OK
```

## 2. Provider entitlement observed (no secret values)

The Massive free-plan `as_of` parameter on `/v3/reference/options/contracts`
returns historical chains back to the earliest anchor (2024-08-23): 314
contracts for that anchor. Historical 15m option aggregate bars are available
for expired contracts (e.g. 357 bars for `O:AMC240906C00005000`). The entire
pilot date range (2024-08-23 → 2026-08-11) falls inside the entitlement, so
no anchor is left-censored by provider entitlement. Only free-plan aggregates
and reference endpoints were used — no Greeks, IV, quotes, OI or snapshots.

## 3. Request count, unique tickers, cache reuse

- 44 provider requests total: 16 contracts-reference + 28 option-bar pulls.
- 28 unique contract tickers.
- 16 cache hits (repeated contracts reused from the on-disk per-ticker cache).
- The shared 5-requests-per-minute limiter was used throughout; no 429s.

## 4. Anchors / cohorts planned vs acquired

- Planned: 16 anchors (8 families × 2 partitions), theoretical max 96 contracts.
- Acquired: 11 anchors, 44 contract cohorts.
- 5 anchors produced **zero** eligible ATM contracts (recorded as a coverage gap,
  not silently moved): `AMC15-005/006/007/011/013`. All five have spot in
  $1.3–1.7, where 0.5-wide strikes are ~15–30% away from ATM, so nothing falls
  inside the frozen ±7.5% moneyness tolerance.

## 5. Coverage by partition, family, CALL/PUT, DTE cell

- Partitions: DISCOVERY 5/8 anchors, HOLDOUT 6/8.
- Families: THESIS_PRESSURE 3, ENTRY_FORMING 3, CONTINUATION 3,
  RISK_OR_EXHAUSTION 2 (across both partitions).
- Types: CALL 22, PUT 22.
- DTE cells: 14 → 22 contracts, 30 → 22, **60 → 0** (no ATM 60-DTE contract
  exists in any anchor's chain within the tolerance).

## 6. Missing / sparse / censored cases

- 5 zero-cohort anchors (low spot, see §4).
- 60-DTE cell empty everywhere (sparse expiration ladder).
- 3 contracts rejected as `insufficient matched history` (< 13 matched bars):
  `O:AMC260904P00002500`, `O:AMC260911P00002500` (×2) — near-expiry PUTs.
- All 44 forward outcomes are right-censored (14/30-DTE contracts expire before
  the 21-day outcome horizon) — expected and labeled, not inferred.
- No left-censoring (every anchor's signal bar exists in the audited replay:
  44/44 `signal_bar_exists=true`).

## 7. Causal timestamp proof (anchor AMC15-001)

- `signal_bar_open_utc` = 2024-08-23T15:15:00Z → 1724426100000 ms.
- `decision_available_utc` = 2024-08-23T15:30:00Z → 1724427000000 ms
  (= bar open + 900000 ms = 15m).
- The option bar at `decision_available_utc` exists on the identical 15m grid
  (`1724425200000, 1724426100000, 1724427000000, 1724427900000`).
- The component ledger's `bar_time` == 1724427000000 (evaluated at the decision
  bar, never at signal-bar open).
- Forward outcomes begin after the decision bar (247 observed bars, MFE +65.0%,
  terminal −95.0%) — future information, research-only.

## 8. Files changed

Written under `reports/options_dna_pilot/` (outputs only):

- `cohort_ledger.csv`, `component_ledger.csv.gz`, `forward_outcomes.csv`,
  `coverage_by_cell.csv`, `quality_rejections.csv`, `failures.json`,
  `manifest.json` (status FETCHED, cohort_count 44), plus 28 files under `bars/`.

One new research script:

- `scripts/assemble_options_dna_ledger.py` (reads the fetched cohort + audited
  replay, emits the four ledgers; makes no provider calls).

No frozen module, test, dashboard file, route, or replay artifact was modified.

## 9. Production / runtime untouched

Confirmed: no change to `webhook_receiver.py`, the dashboard, `options_dna*.py`,
`massive_*.py`, Pine, the DNA engine, alerts, the positions DB, the SEC poller,
or deployment config. No credential was printed, returned, persisted, or
committed; the provider key was read from the configured environment only.

## Stop condition

This stage stops at the verified data/feature ledger. HOT / WEAK / ENTRY WINDOW /
MANAGE / PROTECT / EXIT WINDOW thresholds are **not** calibrated until this
cohort is reviewed and explicitly accepted.
