# DNA-recommended TP/SL bracket levels — Spec

**Status:** design/spec. Read-only — no code, no proposal created. Stops here
for review before any implementation. Follows
`docs/DEEPSEEK_TPSL_RECOMMENDATION_TASK.md`; the `set_bracket` proposal →
approval → `upsert_bracket` lifecycle is already shipped and unchanged.

## 0. Building blocks (verified in code, not assumed)

- `decision_engine.suggest_trailing_stop(states, position, current_price)`
  (decision_engine.py:729) — **trailing** stop: tightest `recent_support_price`
  below price, never lowers, refuses while a cross-TF `EXIT SIGNAL` is active.
  Gate: `position.current_stop is None → return None` (built for trailing an
  existing stop, not the initial one).
- `CampaignState.recent_support_price` (decision_engine.py:69) — the close at
  the timeframe's most recent bullish-support event
  (STRONG START/RELOAD/ADD/FIRE ADD/MANAGE/CAMPAIGN START), set by
  `poll_and_recommend.build_campaign_state` from `/state_all` (poll_and_recommend.py:102).
- `set_bracket` proposal path (paper_execution/api.py:237-278): `create_proposal`
  with `action="set_bracket"`, `position_ref`=ticker, `stop_price`/`target_price`,
  `mode=APPROVAL_REQUIRED`, carries both prices on the proposal row
  (store.py:89-133). On approval → `_apply_approved_bracket` →
  `upsert_bracket` (api.py:94-106).
- `upsert_bracket` (store.py:453) **supersedes the prior ACTIVE bracket for the
  ticker** and inserts the new ACTIVE row; one ACTIVE bracket per
  (experiment, ticker), enforced by a partial unique index (schema_v1.sql:236).
  **So a raised-stop "update" is just `set_bracket` reusing the ticker — no new
  action variant and no extension needed.**
- Challenge caps (experiment_goal_v1.json): `max_daily_paper_loss_pct=5`,
  `single_contract_max_pct=15`, `single_expiration_max_pct=25`,
  `total_options_max_pct=50`, `max_drawdown_pct=25`, `approval_window_seconds=600`.

## 1. Initial stop suggestion

Remove only the `position.current_stop is None` early-return for the
no-existing-stop case; keep every other discipline identical:

- `valid_levels` = `recent_support_price` across timeframes, each `< current_price`.
- Suggest `max(valid_levels)` — the **tightest defensible support below price**
  (same rule as the trailing case; the function's own comment: a level above
  price has already been passed, a level below the tightest is a wider risk than
  necessary).
- Refuse while `synthesize_multi_timeframe_decision(...).action.startswith("EXIT
  SIGNAL")` — same priority rule. In that state the call is an exit, not a bracket.
- If no valid level exists (no fresh bullish-support event anywhere), return
  **no suggestion** — fail-closed, never invent a level from ATR or a fixed
  percent. This is the honest "broken/recovering regime" case.

The initial suggestion differs from the trailing one in exactly one way: the
`current_stop` gate comes off; the "never lower" rule is vacuous at proposal time
because there is no stop to lower yet.

## 1a. Trailing (ongoing) stop updates — in scope, reuse as-is

`suggest_trailing_stop` already produces the correct ongoing read. Design:
while a ticker has an **ACTIVE bracket** and `suggest_trailing_stop` returns a
stop **higher than** the active bracket's `stop_price`, emit a `set_bracket`
proposal that reuses the same `position_ref` (ticker) with the new `stop_price`
and the existing `target_price` preserved. On approval `upsert_bracket`
supersedes the old ACTIVE row (verified §0) — **reuses existing semantics
exactly; no extension.** The bracket is never auto-raised: it still needs the
human's `PENDING_APPROVAL` approval.

## 2. Target / resistance suggestion — the new piece

Evaluated candidates:

| candidate | mechanism | verdict |
|---|---|---|
| (a) structural stretch level | close of the nearest `stretch`-family event (`PEAK`/`MANAGE`/`PREMIUM`, CAMPAIGN_LIFECYCLE_SPEC §3 line 51) **above** current price on any timeframe — the mirror of `recent_support_price` | **Primary** — real structural resistance, same discipline as support |
| (b) risk-reward-derived target | `target = current + k × (current − stop)`, `k` a declared constant | **Fallback** when (a) has no level above price |
| (c) other | TRADE_BOX zones / option OI levels | Rejected for v1 — not cleanly derivable from the state snapshot, would need new data |

**Recommendation: (a) primary, (b) fallback.** For (a): symmetric to support,
pick the **nearest stretch-event close above current price** across timeframes
(`min` of levels `> current_price`). For (b): `k = 2.2` — the one **validated**
reward:risk constant in the codebase: the Trade Box engine's **2.2:1** target,
backtested on **17 real AMC 2H trades** (56.25% win rate vs a 31.25% breakeven
requirement, +0.87R average per closed trade; CIF Engineering Bible,
`Documents/AMC DNA Project/Bible/Claude/filesUPDATED by CLAUDE/
Volume_VI_Validation_Statistical_Framework.md` §3). It only guarantees a defined
downside:upside ratio where no structural resistance exists yet; it is a floor
on target quality, not a claim of probability.

**New tracking required (stated plainly):** unlike support, there is **no
existing tracked field** for the stretch-event close. `CampaignState` needs one
new derived field, `recent_resistance_price`, populated the same way as
`recent_support_price` but when `recent_event ∈ {PEAK, MANAGE, PREMIUM}`. Cost:
one optional dataclass field + the same one-line derivation in
`build_campaign_state` — no new data source, no new storage. This is the only
structural addition in the whole spec.

## 3. "Adapted to our challenge goals" — concrete rule

A suggested bracket must never let a single stop-out breach a declared cap.
Concrete rule (long convention):

```
allowed_loss_usd      = max_daily_paper_loss_pct × total_portfolio_value     # 5% × TPV
max_stop_distance_usd = allowed_loss_usd / |notional|                         # notional = qty × price × 100 if option
max_stop_price        = current_price − max_stop_distance_usd                 # tightest stop the cap permits
```

- If the structural stop (≤ current) is **≥ max_stop_price** (closer), use the
  structural stop; it respects the cap.
- If the structural stop is **< max_stop_price** (too far), clamp to
  `max_stop_price` and say so in the reasoning: "structural support at $X sits
  beyond the 5% daily-loss cap; suggested stop clamped to $Y." The cap wins.
- Lifecycle stage is stated, not guessed: `ignition`/`entry` reads prefer the
  tightest structural level (fresh position); `establishment` naturally widens
  the trail to the higher support on slower timeframes. The reasoning string
  names the stage, the level, and the timeframe/event that produced it.

This makes the caps **enforced at proposal time** for brackets (they are not
otherwise enforced in the fill path), which is the concrete meaning of "adapted
to our challenge goals."

## 4. Trigger — on the paper tick, with caps

Recommendation: **on-tick, matching Entry Discovery's pattern**
(reports/ENTRY_DISCOVERY_SPEC.md §8), with three guards:

1. Suggest only for a ticker with an **open** paper position and **no ACTIVE
   bracket** (initial), or an ACTIVE bracket whose stop `suggest_trailing_stop`
   would raise (trailing).
2. Dedup: no outstanding `PENDING_APPROVAL`/`APPROVED` `set_bracket` for that
   ticker, and at most **1 new suggestion per ticker per trading day** and **3
   outstanding per experiment** (same fatigue discipline as Entry Discovery §9).
3. Suggest only when the level **moved materially** from the active bracket
   (declared threshold: ≥ 0.5% of price), so a healthy campaign isn't re-proposing
   every bar.

Tradeoff stated: on-tick is the most responsive and can't miss an ignition or a
raised-stop moment; the caps above bound the noise. "Only on request" is rejected
— it would miss exactly the protective moments this feature exists for.

## 5. Output shape — reuse `set_bracket`, real proposal

A suggestion is created through the **existing** `create_proposal` path with
`action="set_bracket"`, `position_ref`=ticker, `stop_price`/`target_price`,
`mode="APPROVAL_REQUIRED"` (never auto — unchanged, and `set_bracket` is not in
`VERY_HIGH_AUTO_ACTIONS`). Same reasoning as Entry Discovery §4: reusing the real
proposal machinery buys the approval window, the kill switch, and the append-only
audit for free; a separate "candidate" object buys nothing.

The proposal's `time_sensitive_reason` carries the **evidence attribution**
(reason string): the exact level, the timeframe, the event (`recent support at
$2.4050 from 5m RELOAD @ 08-10 15:20`), and whether the cap clamped it. Same
discipline as `suggest_trailing_stop`'s existing reason.

## 6. Share vs option bracket — honest scope decision

Structural levels are **underlying** levels. A bracket on the **share** ticker
triggers on the underlying close, so the levels attach directly. An **option**
bracket triggers on the **option** close (bracket_decision → `latest(symbol,
ticker)`); translating an underlying level to an option price requires
delta/gamma — which the project forbids to synthesize and does not have.
**Therefore:** DNA-suggested levels attach directly to the **share** bracket;
for **option** tickers the same underlying levels are surfaced as a
reference-only line in the reasoning, and the option bracket price stays a human
decision. This is a stated scope limit, not a silent shortcut.

## 7. Grounded validation (read-only, real data)

**Live multi-TF state, AMC 2026-08-17 ~20:00 ET** (real `/state_all/AMC`
fetch, auth read-only):

| TF | phase | recent_event | close |
|---|---|---|---|
| 1W | WAIT | — | 2.49 |
| 3 / 5 / 15 | WAIT | — | 2.44 |
| 30 / 60 | RECOVERY WATCH | — | 2.455 / 2.44 |
| 120 | RESOLVING | FAIL | 2.44 |
| 180 / 240 / 1D | WAIT | — | 2.44–2.445 |

- **Result on live data:** no bullish-support event on any timeframe →
  `recent_support_price` is null everywhere → **DNA proposes no bracket** —
  the correct fail-closed output for a post-FAIL / WAIT regime. A concrete
  example of the "no structure → no suggestion" rule, not an empty pipeline.
- **Recent worked example (real 5m `live_webhook`, Aug 7–10):** current 5m
  close $2.4450; most recent bullish-support event `RELOAD @ 08-10 15:20`,
  close **$2.4050** → **initial stop $2.4050** (−1.64%). No stretch event in
  window → structural resistance NO_DATA → R:R fallback (k=2.2): `2.445 + 2.2 ×
  (2.445 − 2.405)` = **$2.5330** (2.2:1).
- **Cap check:** stop distance $0.04; allowed loss = 5% × TPV; the stop is
  inside the cap for notional ≤ ~1.25 × TPV (essentially always at ≤100% of
  the book) — the clamp only binds for wide structural stops.

## 8. Open items for review (not decided)

1. `k=2.2` R:R fallback constant (the validated Trade Box number cited in §2) — confirm as the declared default.
2. The 0.5% material-change and 1/day, 3/experiment caps — confirm.
3. Option-bracket handling in §6 (share-direct, option-reference) — confirm scope.
4. Whether the initial suggestion should always pair a target (§2) or stop-only
   until a structure exists.
5. Confirmation that `max_daily_paper_loss_pct` is the right cap to clamp to
   (vs `single_contract_max_pct`).

## 9. Boundary

Read-only. No code, no proposal creation, nothing wired. Nothing weakens the
existing gate: a DNA-suggested bracket still clears the exact same
`PENDING_APPROVAL` → approval → `upsert_bracket` path, and `set_bracket` stays
out of `VERY_HIGH_AUTO_ACTIONS`. Stops here for review before any implementation.
