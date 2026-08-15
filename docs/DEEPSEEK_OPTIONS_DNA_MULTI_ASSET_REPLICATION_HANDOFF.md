# DeepSeek handoff — Options DNA multi-asset external replication

## Authorization boundary

Checkpoint B is closed as
`HISTORICAL_RESEARCH_FINDING_NEEDS_EXTERNAL_REPLICATION`. This handoff
authorizes **protocol design and deterministic anchor planning only**. Stop at
Checkpoint R0 before any new option-chain or option-bar provider requests.

Do not refit AMC, change the frozen target, build a shadow bundle, emit guidance,
or modify production/runtime files.

## Frozen candidate under replication

- target: `CONFIRMATION_FAILURE`;
- scope: `OBSERVE_ENTRY`;
- contract cell: CALL / 14 target DTE / unchanged moneyness policy;
- condition 1: `contract__close_location <= 0.33333333333333354`;
- condition 2: `underlying__campaign_health <= 31.600000000000005`;
- active-print definition: non-zero causal `contract__option_return` using the
  exact Checkpoint B epsilon;
- target semantics and numeric cutoffs: use the frozen v1 definitions without
  modification;
- execution clock: exact next option-bar open, with no shifted or synthetic
  fill;
- AMC evidence is provenance only and cannot enter the replication sample.

The candidate is not shadow-eligible: Discovery rank 12, three active-print
Holdout triggers, and one supported cell only.

## Checkpoint R0 — pre-register before fetching outcomes

Create a versioned protocol and deterministic anchor plan for the eight existing
non-AMC assets: `SPY`, `TSLA`, `GME`, `U`, `RBLX`, `PYPL`, `LULU`, and `VALE`.
Do not remove an asset because its expected result looks inconvenient.

### Asset and liquidity handling

Pre-register two reporting layers:

1. **Per-asset replication:** every asset remains separately visible.
2. **Pooled generalization:** allowed only through an asset-balanced estimator
   where each asset contributes equal total weight. Contract rows or anchors
   cannot let SPY dominate the result.

Liquidity eligibility must be causal and fixed before future outcomes are
read. Use only signal-time information such as exact signal-bar presence,
matched causal history, activity ratio, actual signal-bar movement, volume,
range geometry, standard-contract status and the existing selection policy.
Missing or unreliable cells must resolve to `CONTRACT_DATA_UNRELIABLE`, never a
negative outcome or delayed fill.

### Chronology and independence

- Freeze chronological Discovery and Holdout boundaries per asset before option
  outcomes are fetched.
- Keep the existing global historical seal and document any asset-specific data
  start limitation.
- The independent unit is one underlying anchor per asset. Multiple contracts
  cannot inflate it.
- Deterministically deduplicate clustered underlying events before contract
  selection.
- Hash the exact anchor plan, source ledgers, frozen candidate, target
  definitions, selection policy and acceptance criteria.

### Required controls

Report the unchanged candidate alongside these pre-registered controls:

- underlying-only condition: `campaign_health <= 31.6`;
- contract-only condition: `close_location <= 0.333333...`;
- unconditional cell base rate;
- active-print-only base rate.

The combined rule must add value beyond both single-root controls. Do not search
new thresholds, substitute event families, or rank alternatives in this stage.

### Acceptance criteria to freeze at R0

Define exact numeric gates before fetching outcomes, including at minimum:

- minimum scored Discovery/Holdout anchors per asset and pooled layer;
- minimum active-print triggered anchors;
- direction preservation and minimum lift/precision improvement versus both
  single-root controls;
- asset-balanced confidence interval or deterministic asset-cluster bootstrap;
- maximum concentration in any one asset;
- minimum number of assets showing the same direction;
- failure status for insufficient liquidity or coverage;
- countertarget audit against `EARLY_PREMIUM_CONFIRMATION`;
- no promotion based only on pooled success when most assets fail individually.

Choose and justify the values using the already frozen research-governance
standards, not observed replication outcomes. Include an immutable machine-
readable criteria file.

### Request-budget preview

Using only existing underlying ledgers and provider metadata/cache inventory,
estimate:

- eligible planned anchors by asset and partition;
- expected reference and option-bar requests;
- cached versus new requests;
- feasibility under the Massive free-plan rate and history limits;
- a deterministic stop rule for excessive missing signal bars.

No provider request is permitted during R0.

## Separate position-replay track

Design, but do not execute, a second pre-registered coverage protocol for
open-position navigation. It must cover CALL/PUT × 14/30 DTE, preserve each
asset independently, and define liquidity gates before outcomes. It must not
borrow the CALL/14 entry candidate as an exit, roll, protect or manage rule.

## R0 outputs and stop

Write under a new research-only directory, without overwriting the AMC stage:

- protocol Markdown;
- machine-readable acceptance criteria;
- deterministic anchor plan;
- input/candidate hashes;
- request-budget and feasibility report;
- position-replay coverage protocol draft;
- tests for determinism, chronological separation, AMC exclusion, asset
  balancing, deduplication and no-outcome access during planning.

Report planned counts, gates, hashes, expected requests, blockers, tests and
changed files. Then stop for review before any Massive call or outcome build.

## Prohibited

- no AMC refit or inclusion in replication;
- no threshold or target changes;
- no outcome-aware asset/anchor/contract selection;
- no pooling that hides per-asset failures;
- no delayed/synthetic fill;
- no shadow bundle, dashboard copy or production guidance;
- no Pine, webhook ingestion, Railway, deployment or alert changes.
