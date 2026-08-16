# Insight Library Wording Pass — 2026-08

Copy/presentation pass only. No logic, fact, field, or confidence change: the
closed-vocabulary, no-Greeks, fact-only discipline is unchanged and the
invariant tests still pass (32 insight-library + position-insight tests).

## What was actually wrong

The `tables/dna_position_insight_library.csv` conclusions were already specific
and were **not** the problem (verified row by row; the CMP-\* composition rows
already say *why*, not just *what*). The "same-y + jargon" rendering came from
the runtime path: `webhook_receiver.py` `/positions/<id>/insight` renders
`dna_insight_library.compose()`, whose `conclusion` was a fill-in-the-blank
formula (`long call in a constructive campaign -> hold`) and whose `evidence`
was raw field names (`profitable · moneyness · dte_pressure · age`).

The fix is therefore entirely in `dna_insight_library.py`, not the CSV and not
the dashboard.

## Evidence-bullet decision — option (a), human phrases

Chose **option (a)**: `evidence` now emits short human phrases instead of raw
field-name tokens, so no dashboard change and no endpoint response-shape change
were needed. Grounded only in the existing categorical holding state (no new
fields, no raw numbers added):

- `profitable` → "up on the position" / "down on the position"
  (short-aware: "the short is winning" / "the short is losing")
- `moneyness` → "in the money" / "out of the money"
- `dte_pressure` → "near expiry" / "moderate time left" / "comfortable time left"
- `age` → "held a while" / "recently opened"

## Before / after — one row per composition cell (long and short)

### shares

| condition | before (formula) | after |
|---|---|---|
| broken | shares in a broken campaign -> reduce | A broken campaign puts open shares at downside risk, not at an entry; scale down. |
| weakening | shares in a weakening campaign -> reduce | Momentum is rolling over under open shares, so tightening the stop matters more than chasing; scale down. |
| expanding | shares in a expanding campaign -> add after confirmation | A building campaign supports shares; add only after the next event confirms. |
| repairing | shares in a repairing campaign -> hold | A recovery is rebuilding the structure, so an early add is premature; hold. |
| constructive | shares in a constructive campaign -> hold | Lower tiers are supportive but the campaign tier is still unconfirmed; hold. |
| uncertain | shares in a uncertain campaign -> wait | There is no dominant reading to act on; wait for the next classified event. |

### long call

| condition | before (formula) | after |
|---|---|---|
| broken | long call in a broken campaign -> close / stand aside | A broken campaign works against a long call — decay now compounds the loss; exit the position. |
| weakening | long call in a weakening campaign -> reduce | A weakening structure and time decay both work against a long call; scale down. |
| expanding | long call in a expanding campaign -> consider roll | An expanding campaign supports a long call; consider rolling. |
| repairing | long call in a repairing campaign -> hold | A repair is underway, but decay still sets the clock on a long call; hold. |
| constructive | long call in a constructive campaign -> hold | The setup is constructive but unproven, leaving decay as the only pressure; hold. |
| uncertain | long call in a uncertain campaign -> monitor time decay | With no structural edge, time decay is the only live factor on a long call; monitor time decay. |

### long put

| condition | before (formula) | after |
|---|---|---|
| broken | long put in a broken campaign -> hold | A broken campaign is doing its job as downside protection for a long put; hold. |
| weakening | long put in a weakening campaign -> hold | A weakening structure supports a long put; hold. |
| expanding | long put in a expanding campaign -> close / stand aside | An expanding campaign invalidates the downside thesis behind a long put; exit the position. |
| repairing | long put in a repairing campaign -> reduce | A repair is underway against a long put, so the downside thesis is fading; scale down. |
| constructive | long put in a constructive campaign -> reduce | A constructive setup argues against a long put; scale down. |
| uncertain | long put in a uncertain campaign -> monitor time decay | With no structural edge, decay is the only live factor on a long put; monitor time decay. |

### short shares

| condition | before (formula) | after |
|---|---|---|
| broken | short shares in a broken campaign -> hold | A broken campaign is working for the short; hold. |
| weakening | short shares in a weakening campaign -> hold | A weakening structure is working for the short; hold. |
| expanding | short shares in a expanding campaign -> protect | An expanding campaign is moving against the short; protect the position. |
| repairing | short shares in a repairing campaign -> reduce | A recovery is moving against the short; scale down. |
| constructive | short shares in a constructive campaign -> protect | A constructive setup is building against the short; protect the position. |
| uncertain | short shares in a uncertain campaign -> wait | There is no dominant reading on the short; wait for the next classified event. |

### short call

| condition | before (formula) | after |
|---|---|---|
| broken | short call in a broken campaign -> hold | Decay and falling price both work for a short call; hold. |
| weakening | short call in a weakening campaign -> hold | Decay and a rolling-over structure both work for a short call; hold. |
| expanding | short call in a expanding campaign -> protect | Rising price brings assignment risk on a short call; protect the position. |
| repairing | short call in a repairing campaign -> reduce | A recovery raises assignment risk on a short call; scale down. |
| constructive | short call in a constructive campaign -> protect | A constructive setup raises assignment risk on a short call; protect the position. |
| uncertain | short call in a uncertain campaign -> monitor time decay | With no structural edge, decay is the only live factor on a short call; monitor time decay. |

### short put

| condition | before (formula) | after |
|---|---|---|
| broken | short put in a broken campaign -> protect | Falling price brings assignment risk on a short put; protect the position. |
| weakening | short put in a weakening campaign -> protect | A weakening structure raises assignment risk on a short put; protect the position. |
| expanding | short put in a expanding campaign -> hold | An expanding campaign is working for a short put; hold. |
| repairing | short put in a repairing campaign -> hold | A recovery is working for a short put; hold. |
| constructive | short put in a constructive campaign -> hold | A constructive setup supports a short put; hold. |
| uncertain | short put in a uncertain campaign -> monitor time decay | With no structural edge, decay is the only live factor on a short put; monitor time decay. |

## Verification

- `python3 -m unittest tests.test_dna_insight_library tests.test_position_insight` → 32 passed (invariants unchanged: closed vocabulary, deterministic, fact-only, no Greeks).
- Full suite → 394 passed; `git diff --check` clean.
- Browser: no local browser available; the endpoint output shape is unchanged, so a live render was not performed (only the `conclusion` and `evidence` strings changed).

## Notes

- No new facts, fields, or confidence levels were invented; `navigation_intent`,
  `campaign_condition`, `tf_relationship`, `holding_state`, `confidence`, and
  `decision_change` are unchanged.
- The CSV was left as-is (already specific). `paper_execution/`, TradingView/
  Pine/webhook ingestion were not touched.
