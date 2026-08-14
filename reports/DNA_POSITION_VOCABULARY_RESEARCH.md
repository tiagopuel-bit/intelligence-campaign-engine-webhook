# DNA Position Vocabulary & Insight Library — Research

**Status:** research-only. No production code, Pine, signals, alerts, database
rows, or trading logic were changed. This document, the two tables, and the
`tests/` fixtures are the full deliverable.

**Companion artifacts:**

- `tables/dna_term_dictionary.csv` — canonical terms, synonyms, forbidden wording
- `tables/dna_position_insight_library.csv` — the rule matrix (families + composition)
- `tests/dna_insight_library.py` — reference rule engine (pure functions)
- `tests/test_dna_insight_library.py` — fixtures proving fact-only, deterministic output

---

## 1. Purpose and scope

The Position Manager needs deterministic, evidence-bound "decision copy" — a
short status label plus a plain-language conclusion plus the observable facts
that produced it — for any selected holding. This library is the single source
of that copy.

It is **not** a signal engine. It composes facts the API already returns; it
never predicts returns, direction, or probability.

Hard boundaries enforced everywhere in this library:

1. **Separate market structure from contract mechanics.** A bullish campaign
   does not make an expiring option safe; a broken campaign does not invalidate
   a long put.
2. **Separate evidence from action.** Every intent states the evidence that
   triggered it and the condition that would change it.
3. **No invented data.** No Greeks, IV, quotes, news, or probability. The free
   data plan has none that are trustworthy.
4. **Retain DNA event vocabulary** (Ignition, Reload, Add, Manage, Peak, Fail)
   when referring to an actual engine event; use established market language
   elsewhere.

---

## 2. Data contract (exact fields the library may read)

The library may read **only** these fields. Any field not listed is out of
scope and must never be referenced.

### Campaign / state — `GET /state_all/<symbol>` → `states[]`

| field | meaning |
|---|---|
| `timeframe` | `"3" "5" "15" "30" "60" "120" "180" "240" "D" "W"` |
| `phase` | DNA phase label (see §3) |
| `health` | 0–100 smoothed campaign health |
| `confidence` | 0–100 |
| `recent_event` | last classified event (e.g. `"PEAK"`, `"FAIL TEST"`, `"RELOAD"`) |
| `exhaustion_warning` | bool — leading divergence flag |
| `close` | latest close |
| `bar_time` | epoch-ms or ISO timestamp of the reading |
| `active_trade`, `active_entry`, `active_stop`, `active_target` | Trade Box levels (nullable) |

### Position / valuation — `GET /positions/<id>/valuation`

| field | meaning |
|---|---|
| `underlying.current`, `underlying.prev` | freshest close / prior close |
| `stock.shares`, `stock.avg_cost`, `stock.current_price`, `stock.first_entry`, `stock.total_pnl`, `stock.total_return_pct` | share leg |
| `options[].contract.{type,strike,expiration}` | CALL / PUT leg identity |
| `options[].contracts`, `.avg_cost`, `.current_price`, `.first_entry`, `.breakeven`, `.itm`, `.total_pnl`, `.total_return_pct`, `.leg_ids` | option leg |

### Position identity — `GET /positions`, `GET /positions/<id>`

| field | meaning |
|---|---|
| `symbol`, `direction` (LONG/SHORT), `status` (OPEN/CLOSED) | position header |
| `instruments[].instrument_type` (`SHARE`/`CALL`/`PUT`), `.strike`, `.expiration`, `.quantity`, `.entry_price`, `.entry_time` | manual legs |

---

## 3. Vocabulary → campaign condition (deterministic)

### 3.1 Phase/event → tone

```
neg   <- BROKEN   {FAILED, FAIL, MODERATE FAIL, STRONG FAIL, CATASTROPHIC FAIL}
         STRESSED {FAIL TEST}
warn  <- STRETCH  {PREMIUM, PEAK, MANAGE}
pos   <- BUILDING {EXPANSION, IGNITION, STRONG START, CAMPAIGN START,
                   FIRE ADD, ADD, RELOAD, ACCUMULATE, ACCUMULATION}
neu   <- everything else (WAIT, RESOLVING, no event)
```

### 3.2 Tier model

| tier | timeframes | role |
|---|---|---|
| backbone | D, W | Direction |
| owner | 180, 240 | Campaign |
| confirm | 60, 120 | Confirmation |
| timing | 15, 30 | Timing |
| micro | 3, 5 | Right now |

A tier's read = the **worst** tone among its timeframes (neg > warn > pos > neu).

### 3.3 Campaign condition (precedence order — first match wins)

1. **broken** — any of backbone/owner/confirm is `neg`
2. **weakening** — any tier is `warn`, or `exhaustion_warning` is true
3. **expanding** — owner tier is `pos`
4. **repairing** — any `recent_event` is RELOAD / RECOVERY / RECOVERY WATCH
5. **constructive** — confirm or timing is `pos`, owner is not `neg`
6. **uncertain** — fallback (WAIT, no data, stale, or conflicting)

`repairing` is deliberately checked *after* `expanding`: a RELOAD on a lower
timeframe while the campaign tier is already EXPANDING means the campaign is
expanding, not still repairing.

### 3.4 Timeframe relationship (independent axis)

- **weakness contained** — micro/timing weak, backbone/owner intact
- **weakness propagating** — neg moves up into confirm/owner
- **higher-TF intact** — backbone/owner pos/healthy above mixed lower tiers
- **multi-TF confirmation** — two or more tiers agree (esp. owner + confirm)
- **conflicting evidence** — pos on one tier, neg on another (slower tier wins)

---

## 4. Ambiguous terms (summary)

The term dictionary resolves these ambiguities; full table in the CSV.

| ambiguous | canonical | note |
|---|---|---|
| trend / setup | **campaign** | campaign = multi-TF structure; trend = single-TF slope |
| bullish | **constructive** | structural, not directional |
| recovered / reload | **repairing** | repair is unconfirmed until the next event holds |
| ITM/OTM | **in/out of the money** | prose, not abbreviations |
| theta / decay | **time decay** | never quantified; no Greeks on the free plan |
| entry | **average cost** (`avg_cost`) vs **first entry** (`first_entry`) | price vs timestamp — never conflate |
| quiet | **uncertain** | silence is not safety |

**Forbidden wording** (overconfidence / invented data): "guaranteed",
"certain", "will", "predicted", "safe", "risk-free", "house money",
"let winners run", "average down", "it will come back", "the top is in",
any Greek name, "implied volatility", "probability of profit", "fair value",
"target price" as a prediction.

---

## 5. Insight library structure

The matrix (`tables/dna_position_insight_library.csv`) has five families:

- `campaign` — 6 rows: structure read per condition (instrument-agnostic)
- `holding` — 8 rows: contract-mechanics read (shares profit/loss; call/put
  ITM/OTM; DTE pressure; multi-leg future-ready)
- `tf` — 5 rows: timeframe-relationship read
- `intent` — 8 rows: the navigation-intent vocabulary
- `composition` — 20 rows: `campaign × instrument → default intent` plus the
  composed conclusion/evidence/decision-change/prohibited/fields/confidence

Every row carries the seven required attributes: **status label**, **one-line
conclusion**, **2–3 evidence bullets**, **decision-change condition**,
**prohibited wording**, **exact API fields**, **confidence label**.

### Confidence labels

| label | meaning |
|---|---|
| `confirmed` | multi-TF agreement |
| `structural` | single-tier DNA read |
| `structural-unconfirmed` | recovery/building read awaiting the next event |
| `mechanical` | contract math only (moneyness/DTE/P&L) |
| `confirming` | lower-vs-higher TF relationship |
| `inferred` | conflict resolution (slower tier wins) |
| `no-basis` | cannot be determined from supplied facts |

---

## 6. Composition rules (campaign × instrument → intent)

Deterministic, precedence-ordered. Holding state and TF relationship act as
**modifiers** on the default intent (see §7).

| instrument | broken | weakening | repairing | expanding | constructive | uncertain |
|---|---|---|---|---|---|---|
| **shares** | protect | protect | hold | add after confirmation | hold | wait |
| **long call** | close / stand aside | reduce | hold | consider roll (ITM) / hold (OTM) | hold | monitor time decay |
| **long put** | hold | hold | reduce | close / stand aside | reduce | monitor time decay |
| **multi-leg** | wait (future-ready) | wait | wait | wait | wait | wait |

Note the deliberate asymmetry: **broken/weakening helps a long put and hurts a
long call and shares.** The matrix never reuses a share read for an option or
vice-versa.

---

## 7. Holding-state and TF-relationship modifiers

Modifiers refine the default intent, never override the *evidence*:

- **profitable** + broken/weakening → bias `reduce` (lock gains) instead of
  `protect` for shares/calls.
- **at a loss** + broken → bias `protect` (cap downside).
- **high DTE pressure** (≤10 days) on an option → `monitor time decay` becomes
  the dominant concern unless the condition is broken.
- **weakness propagating** → escalates `hold` → `protect`/`reduce`.
- **higher-TF intact** / **multi-TF confirmation** → supports `hold` /
  `add after confirmation` for longs.
- **conflicting evidence** → slower tier is authoritative; if it is neutral,
  treat as `uncertain`.

---

## 8. Grounded validation (read-only, live Railway data, 2026-08-14)

`GET /state_all/<symbol>` was fetched for each required symbol; stored data was
not modified. Campaign condition computed with §3.3.

| symbol | computed condition | evidence (events / tiers) |
|---|---|---|
| AMC | repairing | RELOAD + ADD; owner WAIT, confirm/timing EXPANSION |
| SPY | weakening | PEAK on 240; FAIL TEST on 3m; confirm/timing EXPANSION |
| U | constructive | EXPANSION on 15m/5m; no campaign tier |
| GME | broken | FAILED on 240; FAIL TEST present |
| LULU | uncertain | all WAIT / no events |
| PYPL | expanding | EXPANSION on 180; STRONG START, FIRE ADD, ADD |
| RBLX | broken | FAILED on 180, FAIL TEST on 60, MANAGE on 15 |
| TSLA | constructive | EXPANSION on 15m/5m; no campaign tier |
| VALE | broken | FAILED on 180/60/30/3 |

All six conditions are exercised; the classifier is deterministic and uses only
fields in §2. The `tests/` fixtures encode these nine cases so the matrix is
regression-checked.

---

## 9. Integration contract (for Claude/GPT)

**Inputs** (all optional unless noted; missing → `no-basis`):

```json
{
  "instrument": "shares | long_call | long_put | multi_leg",
  "states": [{ "timeframe": "240", "phase": "EXPANSION", "recent_event": "ADD",
               "exhaustion_warning": false }],
  "holding": { "avg_cost": 1.52, "current_price": 2.0,
               "total_return_pct": 31.6, "itm": true, "strike": 1.5,
               "expiration": "2026-09-18", "first_entry": "2026-04-20T07:17:00Z" }
}
```

**Deterministic pipeline:**

1. `campaign_condition(states)` → one of 6 conditions (§3.3).
2. `holding_state(holding, instrument)` → {profitable|loss, ITM|OTM|n/a,
   DTE pressure low|medium|high, new|mature}.
3. `tf_relationship(states)` → one of 5 (§3.4).
4. `compose(condition, instrument, holding_state, tf_relationship)` → lookup
   the `composition` row, apply §7 modifiers.

**Output** (a single record, no free text):

```json
{
  "status_label": "Time pressure",
  "conclusion": "Under about 10 days to expiration, time decay is the dominant factor.",
  "evidence": ["days-to-expiration <= 10"],
  "decision_change": "the position is closed or rolled",
  "prohibited": ["it still has time"],
  "confidence": "mechanical"
}
```

**Invariants:** output references only §2 fields; intent is one of the 8; the
decision-change condition is stated; overconfident wording is absent; missing
required fields yield `confidence: "no-basis"` rather than a fabricated read.
