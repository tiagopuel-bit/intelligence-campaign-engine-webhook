# Option-native TP/SL — Spec extension

**Status:** spec-only, read-only. No code, no proposal created. Follows
`reports/TP_SL_RECOMMENDATION_SPEC.md` (base spec, signed off §8) and
`docs/DEEPSEEK_OPTION_NATIVE_TPSL_TASK.md`. Blocks implementation of the
share-only version so both ship together.

## 0. Data grounding — verified, not assumed

### 0.1 The live decision-time source: `option_heartbeats`
Schema (webhook_receiver.py:236-253): per instrument, 1-minute bars storing
only `close` plus `option_return`, `matched_bars`, `activity_ratio`, `volume`
— **no high/low/open/vwap**.

**Live reality for the held book:** the four held option instruments
(6/8/9/10) have **never had a fresh heartbeat** — `BLOCKED_NO_FRESH_OPTION_HEARTBEAT:6/8/9/10`
has persisted since before the weekend through the live polls today.
Consequence (code-verified, cloud_state.py:143-144): `reconstruct_cloud_state`
returns `None` for a CALL/PUT instrument with no heartbeat, so these positions
have **no authoritative state at decision time today**. Therefore an
option-native level derived from `option_heartbeats` **fails closed right now:
"insufficient option history."** This is the expected, honest output the task
anticipates — it is not a gap to paper over.

### 0.2 The alternative source: Massive option OHLCV bars (research path)
`options_dna.component_ledger` (options_dna.py) already computes contract-level
fields from matched option+underlying OHLCV: `close_location`, `volume_ratio`,
`range_expansion`, `drawdown_from_high_pct`, and crucially **`prior_high`** (max
of prior highs over the lookback). `prior_high` is the closest existing
"option's own recent high" signal — a real **resistance** candidate. There is
**no existing "option recent low"** (support candidate) — that would need one
new derived field, the same one-field shape as `recent_resistance_price` in the
base spec. Caveat: Massive option bars are **EOD/DELAYED** on the free plan
(exactly how `current_price` in the live valuation already falls back to
Massive), so a level from this path is **DELAYED**, never LIVE.

### 0.3 The real held book (live `/positions` + valuations, read-only)
- pos 4 — CALL 1.5, 2027-01-15, 2 ct, avg 0.85, now 1.14 (ITM) · inst 6
- pos 5 — **622 AMC shares**, avg 1.52, now 2.44 · inst 7 (share — covered by base spec)
- pos 6 — CALL 1.5, 2026-12-18, 1 ct, avg 0.72, now 1.14 (ITM) · inst 8
- pos 7 — CALL 1.5, 2026-09-18, 7 ct, avg 0.51, now 1.01 (ITM) · inst 9
- pos 8 — CALL 1.5, 2026-08-21, 2 ct, avg 0.22, now 0.98 (ITM) · inst 10

4 of 5 open positions are ITM calls (underlying 2.44 vs strike 1.50), all with
real, position-derived breakevens already computed by the valuation endpoint.

## 1. Derivation method (option-native, no Greek translation)

Strictly the option's **own price series**. Never translates an underlying
level via delta/gamma — that constraint is unchanged from the base spec §6.

- **Stop (initial and trailing):** the option's **tightest recent support below
  current option price** from its own series — `min` of recent lows (or recent
  closes) over a declared lookback window, below current price, highest of the
  valid candidates (the tightest defensible level, mirroring the base spec's
  discipline). Refuse while a cross-TF `EXIT SIGNAL` is active; never lower an
  existing stop. **Minimum-history floor** (review item below): below it the
  output is `NO_SUGGESTION_INSUFFICIENT_OPTION_HISTORY` — fail-closed, never a
  number forced out of 2 bars.
- **Volume confirmation (causal discipline):** a support level is only used when
  the pullback into it was not on a volume spike — reuse `volume_ratio` /
  `activity_ratio` / `unchanged_print` in the same direction they are already
  used (options_dna_insight.py): an `unchanged_print` / near-zero `activity_ratio`
  means no basis; a volume spike into the low weakens it as support.
- **Target:** the option's **own recent high above current** (the `prior_high`
  extension → a `recent_option_resistance` level, max of recent highs), else the
  position **breakeven** (strike + avg_cost — real, position-derived, already
  computed by valuation) as the fallback reference, else an R:R fallback in
  **option-price** terms with the same validated constant as the base spec:
  **k = 2.2** (Trade Box 2.2:1, 17 real AMC 2H trades — 56.25% win vs 31.25%
  breakeven, +0.87R avg; see `TP_SL_RECOMMENDATION_SPEC.md` §2). The breakeven
  is preferred as fallback over a pure R:R multiple for options because it is a
  real level the human already tracks.

**New derived fields required (stated plainly):** `recent_option_support`
(min of recent lows/closes) and `recent_option_resistance` (max of recent
highs), computed from the option's own bar series at decision time. `prior_high`
(component_ledger) is the reuse point for the resistance side on the DELAYED
path; the support side has no existing reuse and is the genuinely new field.

## 2. Caps — option-contract notional

Same rule as the base spec §3, in option terms (`qty × price × 100`):

```
allowed_loss_usd      = max_daily_paper_loss_pct × TPV          # 5% × TPV
max_stop_distance     = allowed_loss_usd / (qty × 100)          # option notional
cap_floor_stop        = current_option_price − max_stop_distance
```

If the structural option stop is below the cap floor, clamp to the floor and
say so in the reasoning. **Real numbers on the live book** (TPV ≈ $2,862.68 =
sum of position valuations + $100 cash; allowed loss = $143.13):

| pos | inst | qty | cur | max stop dist | cap-floor stop |
|---|---|---|---|---:|---:|
| 4 | 6 | 2 | 1.14 | 0.7157 | 0.4243 |
| 6 | 8 | 1 | 1.14 | 1.4313 | −0.2913 (never binds) |
| 7 | 9 | 7 | 1.01 | 0.2045 | **0.8055** |
| 8 | 10 | 2 | 0.98 | 0.7157 | 0.2643 |

Position 7 (7 contracts) is where the cap genuinely binds: any option stop
below ~$0.81 would let a single stop-out breach the 5% daily-loss cap.

## 3. Reuse — set_bracket lifecycle, unchanged

Same exact `set_bracket` → `APPROVAL_REQUIRED` → approval → `upsert_bracket`
path (api.py:237-278, store.py:453). No new action type, no new approval model,
`set_bracket` stays out of `VERY_HIGH_AUTO_ACTIONS`. The only new thing is
**which evidence produces the suggested `stop_price`/`target_price`** when the
ticker is an option: the option's own series (§1) instead of the underlying's
`recent_support_price`.

## 4. Worked examples — real book, honest outcome

- **Cap math:** the four rows in §2 are real numbers from the live book and are
  the binding constraint today (esp. pos 7).
- **Level derivation:** for all four option instruments (6/8/9/10) the honest
  current output is **`NO_SUGGESTION_INSUFFICIENT_OPTION_HISTORY`** — there is
  no live option bar history at all (relays never landed), so no causal option
  level exists to compute. This is the correct fail-closed result and the
  expected steady state until the option relays accumulate fresh bars.
- **Once heartbeats land:** the same derivation then uses the accumulated 1m
  close/low series (≥ floor) to emit a level, or the DELAYED path uses Massive
  OHLCV (`prior_high`/recent lows) with an explicit `DELAYED` freshness label,
  matching how valuation already marks Massive-derived prices.

## 5. Honest statement — which contracts lack enough history

**All four currently-held options (instruments 6/8/9/10).** Their heartbeat
relays have never landed a fresh bar, so there is no live option-price history
to derive a causal level from today. The share position (inst 7) is not
affected — it uses the base spec's underlying levels. This is the single most
important grounded finding: the option-native feature's *real* dependency is the
option heartbeat relays actually flowing, which is the same infra gap already
blocking `/paper/health`.

## 6. Open items for review

1. Minimum-history floor for an option-native level (proposal: ≥ 30 bars of the
   option's own series) — confirm.
2. Lookback window (proposal: 20 bars, matching `component_ledger`'s `lookback=20`).
3. Target precedence: option recent-high first, then breakeven, then R:R (k=2.2) — confirm.
4. Whether the DELAYED Massive-OHLCV path should be a live fallback once the
   relays land, or LIVE-heartbeat-only.
5. Confirm the cap uses total TPV (positions + cash) at proposal time.

## 7. Boundary

Read-only. No code, no proposal created, nothing wired. Same review gate as the
base spec — stops here until Tiago reviews. No Greek is synthesized anywhere.
