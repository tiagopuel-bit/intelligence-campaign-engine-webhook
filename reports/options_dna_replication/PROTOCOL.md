# Options DNA — Multi-Asset External Replication Protocol v1 (R0)

**Status:** pre-registration only. No option-chain or option-bar provider
requests are authorized at R0. This document, the acceptance criteria, the
deterministic anchor plan, the request-budget estimate and the position-replay
draft are the deliverables. Execution (fetch → assemble → evaluate) is a later,
separately-authorized round.

## 1. Object under replication

The single surviving AMC entry finding from Checkpoint B, frozen and unchanged:

- **Target:** `CONFIRMATION_FAILURE` (v1 frozen DISCOVERY quantile cutoffs).
- **Scope:** `OBSERVE_ENTRY`.
- **Cell:** CALL / 14 target DTE / nearest-regular-strike moneyness policy.
- **Conditions:**
  - `contract__close_location <= 0.33333333333333354`
  - `underlying__campaign_health <= 31.600000000000005`
- **Active print:** non-zero causal `contract__option_return` (epsilon 1e-9).
- **Execution clock:** exact next option-bar open; no shifted/synthetic fill.

AMC evidence is provenance only and is excluded from the replication sample.
The candidate is not shadow-eligible (Discovery rank 12, three active-print
holdout triggers, one supported cell) and is being tested for external
replication, not promoted.

## 2. Assets and sampling

Eight non-AMC assets, each kept separately visible: `SPY`, `TSLA`, `GME`, `U`,
`RBLX`, `PYPL`, `LULU`, `VALE`. No asset may be removed because its result looks
inconvenient.

The deterministic anchor plan samples, per asset and per evidence family
(`ENTRY_FORMING`, `CONTINUATION`, `RISK_OR_EXHAUSTION`, `THESIS_PRESSURE`):

- DISCOVERY: 8 anchors/family (32 per asset);
- HOLDOUT: 4 anchors/family (16 per asset).

The independent unit is one underlying anchor per asset; multiple contracts
never inflate it. Clustered underlying events are deterministically deduplicated
before selection, and the global `2026-02-01` chronological seal is unchanged.

## 3. Liquidity eligibility (causal, frozen before outcomes)

A contract row is eligible only from signal-time information:

- exact signal-bar presence (no shift to a later print);
- sufficient matched causal history and activity ratio;
- actual signal-bar movement (active-print definition above);
- observed signal-bar volume and range geometry;
- standard 100-share contract status and the existing selection policy.

Missing or unreliable cells resolve to `CONTRACT_DATA_UNRELIABLE`, never to a
negative outcome or a delayed fill.

## 4. Reporting layers

1. **Per-asset:** every asset is reported separately and must pass individually.
2. **Pooled:** asset-balanced estimator — each asset contributes equal total
   weight, so no single asset (e.g. SPY) can dominate.

## 5. Controls

The unchanged candidate is reported alongside four pre-registered controls:

- underlying-only: `campaign_health <= 31.6`;
- contract-only: `close_location <= 0.333…`;
- unconditional cell base rate;
- active-print-only base rate.

The combined rule must add value beyond both single-root controls. No new
thresholds, event-family substitution, or ranking is performed in this stage.

## 6. Acceptance criteria

Frozen in `acceptance_criteria_v1.json`. In summary, each asset must have ≥20
scored Discovery and ≥10 scored Holdout anchors, ≥3 active-print triggered
holdout anchors, direction preservation (full and active-print lift > 1.0),
strict lift+precision superiority over both single-root controls, and a clear
countertarget audit versus `EARLY_PREMIUM_CONFIRMATION`. Pooled generalization
requires ≥5 of 8 assets to show the same direction, ≤40% weight in any one
asset, and an asset-cluster bootstrap lift CI above 1.0. Promotion is forbidden
when most assets fail individually.

## 7. Request budget (estimate only)

Computed from the plan without any provider call: 384 planned anchors across 8
assets → an upper bound of ~384 contract-reference + ~384 option-bar requests
(≈768 requests), ~2.6 hours at the shared 5/minute limiter, plus per-ticker
cache reuse that reduces the real bar count. A deterministic stop rule flags
`CONTRACT_DATA_UNRELIABLE` for excessive missing signal bars rather than
retrying or widening.

## 8. Immutability

The manifest hashes the frozen candidate, the acceptance criteria, and each
asset's source 15m replay. Any change after R0 is rejected by hash.

## 9. Position-replay track (separate)

A second pre-registered coverage protocol (draft only) covers CALL/PUT × 14/30
DTE open-position navigation with per-asset independence and liquidity gates.
It must not borrow the CALL/14 entry candidate as an exit/roll/protect/manage
rule. See `position_replay_coverage_protocol.md`.
