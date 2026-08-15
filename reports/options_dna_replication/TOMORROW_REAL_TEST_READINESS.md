# Multi-Asset External Replication — Result Report (2026-08-15)

Frozen protocol, no refits. This report documents the outcome of the one
authorized fetch → assemble → evaluate run against the frozen AMC
`CONFIRMATION_FAILURE` / `CALL/14` candidate
(`contract__close_location <= 0.3333` AND `underlying__campaign_health <=
31.6`), unchanged from `acceptance_criteria_v1.json`.

> **Assembly correction note:** an earlier assemble pass wrote a
> `component_ledger.csv.gz` whose CSV writer dropped the per-contract feature
> columns (`close_location`, `option_return`, …) because the writer inferred
> columns from the first row, which was a signal-bar-absent row. That
> defect-made the candidate appear to trigger zero groups on every asset. The
> assemble script was fixed to emit a union of all row keys, the ledger was
> re-assembled, and this report reflects the corrected ledger only.

## Headline result

```
replication_status: EXTERNAL_REPLICATION_NOT_CONFIRMED
pooled_pass: false
promotion_forbidden: true
passing_assets: [] (0 of 8)
assets_with_direction: 2 (GME, TSLA)   — pooled gate requires >= 5
scored_rows: 228 of 370
```

**No threshold was refit, no minima were relaxed, and no shadow/production
promotion occurred.** This is a terminal research finding for the frozen
candidate as specified.

## Fetch summary (provider access)

- `manifest.json` status: `FETCHED_WITH_FAILURES`.
- 384 anchors planned → **370 cohort rows resolved (96.4%)**, 14 failures.
- 337 unique tickers; 350 reference requests, 337 option-bar requests, 0 cache
  hits (first run, cold cache).
- **Failures (14, `failures.json`)**:
  - 7× `SPY` — "rate limited after retries" at the `contracts` stage
    (session dates 2025-04-29, 2026-03-18/25, 2026-04-09/15, 2026-08-07/11).
  - 7× "no CALL/14 regular contract within DTE tolerance" at the `selection`
    stage: `LULU-0013`, `LULU-0038`, `LULU-0042`, `GME-0044`, `RBLX-0043`,
    `RBLX-0044`, `U-0044`.
  - These are provider/liquidity limitations, not pipeline defects, and are
    within the pre-registered tolerance (the protocol does not require 100%
    anchor resolution).

## Assemble summary

| Metric | Count |
| --- | --- |
| Component rows | 370 |
| Outcome rows | 370 |
| Window-outcome rows | 1,850 |
| Quality-rejection rows | 196 |
| Coverage cells | 8 |

### Quality-rejection reasons (196 total, `quality_rejections.csv`)

| Reason | Count |
| --- | --- |
| signal option bar absent | 125 |
| insufficient matched history | 33 |
| sparse option activity | 26 |
| zero or insufficient underlying variance | 12 |

Per `acceptance_criteria_v1.json` failure semantics, "insufficient matched
history" and "sparse option activity" map to `CONTRACT_DATA_UNRELIABLE`;
"signal option bar absent" maps to `UNSCORED_SIGNAL_BAR_ABSENT`. Neither
status counts toward the scored sample. 212 component rows are `ready=True`;
228 rows receive a scored frozen-cutoff target label.

## Per-asset results (`replication_evaluation.json`, `per_asset`)

Per-asset minimums required (from `acceptance_criteria_v1.json`):
`min_scored_discovery_anchors=20`, `min_scored_holdout_anchors=10`,
`min_active_print_triggered_holdout_anchors=3`, `min_positive_holdout_anchors=2`.

| Asset | Discovery scored | Holdout scored | Holdout positive | Holdout active-print triggered | Candidate holdout triggered groups | Candidate holdout lift | Direction preserved | Control superior | Counter clear | Asset passes |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| SPY | 28 | 10 | 1 | 1 | 1 | 0.00 | false | false | false | **false** |
| TSLA | 32 | 14 | 2 | 1 | 1 | 7.00 | **true** | true | true | **false** |
| GME | 26 | 15 | 2 | 2 | 2 | 3.75 | **true** | true | **false** | **false** |
| U | 18 | 5 | 1 | 0 | 0 | — | false | false | false | **false** |
| RBLX | 12 | 6 | 2 | 0 | 0 | — | false | false | false | **false** |
| PYPL | 22 | 11 | 2 | 0 | 0 | — | false | false | false | **false** |
| LULU | 16 | 1 | 1 | 0 | 0 | — | false | false | false | **false** |
| VALE | 7 | 5 | 0 | 0 | 0 | — | false | false | false | **false** |

The candidate fires on **14 of 228 scored anchors** overall (10 discovery + 4
holdout). In holdout the four triggered groups are GME (2), SPY (1), TSLA (1);
no other asset triggers at all.

**Insufficient-data cells (below the frozen per-asset minimums), reported
explicitly — these assets are not evaluated further even before the
direction/control checks:**

- `U`: holdout scored 5 < 10 required.
- `RBLX`: discovery scored 12 < 20 required; holdout scored 6 < 10 required.
- `LULU`: holdout scored 1 < 10 required.
- `VALE`: discovery scored 7 < 20 required; holdout scored 5 < 10 required;
  holdout positive groups 0 < 2 required.

**Assets that meet the minimum sample-size gate but still fail:**

- `SPY` (28/10): the single holdout trigger is not a `CONFIRMATION_FAILURE`
  positive, so candidate precision/lift is 0.0.
- `TSLA` (32/14): direction preserved (lift 7.0) and controls/counter clear,
  but `holdout_active_triggered_groups = 1 < 3` required — fails the
  active-print trigger minimum.
- `GME` (26/15): direction preserved (lift 3.75) and controls clear, but the
  countertarget audit fails — the same triggered anchors also enrich
  `EARLY_PREMIUM_CONFIRMATION`, so the candidate is ambiguous, not a clean
  failure predictor.
- `PYPL` (22/11): zero candidate triggers (lift/precision 0.0).

## Control comparison detail (`controls`, per asset)

The combined candidate (`contract_only` ∧ `underlying_only`) triggers in
holdout only for GME (2 groups, precision 0.50, lift 3.75), SPY (1 group,
precision 0.00, lift 0.0) and TSLA (1 group, precision 1.00, lift 7.0). The
single-factor controls trigger more often:

- `underlying_only` (`campaign_health <= 31.6`): GME 5/15 (lift 1.50),
  TSLA 5/14 (lift 2.80), PYPL 2/11 (lift 2.75), U 3/5 (lift 1.67),
  SPY 1/10 (lift 0.00), RBLX 1/6 (lift 0.00), VALE 1/5 (lift 0.00),
  LULU 0/1.
- `contract_only` (`close_location <= 0.3333`): fires only in holdout where
  the candidate also fires; on its own it triggers the same GME/SPY/TSLA
  holdout anchors without the `campaign_health` conjunct (its lift is not
  separately superior on the 4-trigger sample).
- `active_print_only_base_rate`: 212 of 228 scored rows are active-print, so
  this base rate is close to the unconditional base rate.

`control_superior` is `true` only for TSLA and GME; the combined rule does not
beat both single-root controls on any other asset.

## Countertarget audit (`EARLY_PREMIUM_CONFIRMATION`)

- `TSLA`: `counter_clear: true` — the candidate's single triggered anchor is
  a `CONFIRMATION_FAILURE` positive and not an early-confirmation positive.
- `GME`: `counter_clear: false` — the two triggered holdout anchors also
  enrich `EARLY_PREMIUM_CONFIRMATION`, so the candidate is ambiguous on GME.
- `SPY`: `counter_clear: false` — the single trigger is not a candidate
  positive, so the comparison is not cleared.
- All other assets: zero candidate triggers, so the countertarget comparison
  cannot be satisfied (failure-closed).

## Pooled / asset-cluster bootstrap evidence

```
pooled.base_rate: 0.2614
pooled.groups: 67
pooled.triggered_groups: 4
pooled.coverage: 0.0381
pooled.precision: 0.1875
pooled.lift: 0.7172          (< 1.0 → not direction-preserving)
pooled_active_print.lift: 0.7103
pooled_lift_ci.low: 0.1334
pooled_lift_ci.high: 1.9626
pooled_lift_ci.prob_above_one: 0.323
assets_with_direction: 2      (gate: >= 5 required)
max_single_asset_weight: 0.125 (gate: <= 0.40, satisfied)
```

The asset-cluster bootstrap lift CI spans `[0.13, 1.96]` with
`prob_above_one: 0.32` — no evidence of a stable above-unity lift. The pooled
lift is pulled down because four of the eight assets have zero candidate
triggers, so their asset-balanced contribution to precision is 0.0.

## Insufficient-data cells (explicit)

| Asset | Gate failed | Value | Required |
| --- | --- | --- | --- |
| RBLX | discovery scored anchors | 12 | ≥ 20 |
| RBLX | holdout scored anchors | 6 | ≥ 10 |
| VALE | discovery scored anchors | 7 | ≥ 20 |
| VALE | holdout scored anchors | 5 | ≥ 10 |
| VALE | holdout positive anchors | 0 | ≥ 2 |
| U | holdout scored anchors | 5 | ≥ 10 |
| LULU | holdout scored anchors | 1 | ≥ 10 |
| TSLA | holdout active-print triggered anchors | 1 | ≥ 3 |
| SPY / PYPL / U / RBLX / LULU / VALE | holdout active-print triggered anchors | 0 | ≥ 3 |

## Conclusion

The frozen `CONFIRMATION_FAILURE` / `CALL/14` candidate does **not**
replicate on this 8-asset external holdout sample. The candidate is a rare,
low-coverage rule (14 fired anchors of 228 scored, 4 holdout triggered
groups); only 2 of 8 assets show a positive holdout lift, well below the
pooled gate of 5. The asset-balanced pooled lift is 0.72 with a cluster
bootstrap `prob_above_one` of 0.32, four assets are below the frozen sample
minima, and the two assets that do show direction each fail a remaining gate
(GME: ambiguous countertarget; TSLA: 1 active-print trigger < 3).

Per the frozen protocol boundary: no refitting, no threshold changes, no
relaxation of minima, no live guidance, and no production/shadow promotion
follow from this result. `promotion_forbidden: true` stands. The finding is
recorded as `EXTERNAL_REPLICATION_NOT_CONFIRMED` and the research loop for
this specific frozen candidate is complete — any further iteration requires a
newly pre-registered candidate treated as an unproven hypothesis, not a patch
to this one.
