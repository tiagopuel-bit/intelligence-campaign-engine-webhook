# Entry Discovery — Spec (DNA Trader surfaces new candidate positions)

**Status:** design/spec phase. Read-only against existing data; no code changed,
no proposal created, no activation. Spec-then-build — wait for review before any
implementation.

## 0. What this formalizes

Today `paper_execution` only ever evaluates actions on **already-held**
positions (the frozen starting holdings from activation). There is no mechanism
that scans for and surfaces a **new** position worth opening — a candidate a
human hasn't thought of yet. This spec defines that capability: a read-only
scanner that turns the DNA state machinery into closed-vocabulary **entry
candidates**, surfaced as ordinary `open` proposals requiring manual approval.

## 1. Hard boundary — discovery, not execution (read first)

Per `reports/PORTFOLIO_MULTI_ASSET_SPEC.md` §11 (Option A, locked tonight),
entries are **manual-only**. This spec does **not** change that. A surfaced
candidate becomes a normal `PENDING_APPROVAL` proposal and must clear the exact
same path a hand-typed `open` would: evidence-root reconstruction, the 30% AMC
floor (R1), the eligibility gate, and the 600-second approval window. **If any
part of this design would let a discovered candidate skip that path, it is
wrong and must be rejected at review.** Auto-entry (Option B) is a separate,
explicitly-gated later authorization and is deliberately out of scope here.

## 2. Candidate definition — closed vocabulary, no score

A candidate is a named condition, not a rank:

```
candidate = {
  symbol,                      # in tracked_symbols(experiment) AND asset_eligible
  direction = LONG,            # ignition is a bullish entry; short discovery is out of scope
  stage     = "ignition",      # the lifecycle stage, per CAMPAIGN_LIFECYCLE_SPEC §5
  contract  = {type: CALL, strike, expiration},   # §6 selection rule
  evidence  = {timing_tf, micro_tf, timing_event, close}
}
```

**`ignition` is already defined** (CAMPAIGN_LIFECYCLE_SPEC §5), all three legs:

1. a **timing** tier bar (`15m` or `30m`) fires an `entry` event
   (`STRONG START / CAMPAIGN START / FIRE ADD / ACCUMULATE / IGNITION / ADD / RELOAD`);
2. the **micro** tier (`5m`) fired `entry` or `entry_test` within ±15 min of it; and
3. higher tiers are **quiet**: no `entry`/`stretch`/`fail`/`fail_test` on
   `confirm` (`60`/`120`) within 4h, `owner` (`180`/`240`) within 6h, or
   `backbone` (`D`/`W`) within 12h.

Additional gating (still closed-vocabulary, no new scoring):
- **Not already held** — no open paper position for `symbol`.
- **Not already proposed** — no existing `PENDING_APPROVAL`/`APPROVED` `open`
  proposal for `symbol` (dedup; §9).
- **Asset eligible** — `asset_eligible(mask, symbol)` passes (reliability-mask
  gate). AMC always passes; this is what keeps thin/noisy assets out tomorrow.

## 3. Reuse, don't duplicate

**Trigger = the lifecycle `ignition` stage.** It is the earliest, broadest entry
flicker, and it is exactly what the lifecycle feature was built to catch. Its
definition (§2) is already frozen in `CAMPAIGN_LIFECYCLE_SPEC.md`.

**Confirmation layer = `decision_engine.synthesize_multi_timeframe_decision`
(already Python, already cross-asset validated).** Its `ENTRY SIGNAL` (3+ TFs
with confirmed continuation after a STRONG START/RELOAD) is a *later, stronger*
read than ignition. Discovery does **not** re-implement it: when both fire, the
candidate's evidence records `synthesis = "cross-TF confirmation"` alongside
`stage = "ignition"`; when only ignition fires, the candidate stands on ignition
alone. The two are composed, not reinvented.

**One new piece of logic, and it is a port, not new reasoning:** the `ignition`
condition is currently implemented client-side in `ui/dna_dashboard.html`
(`lifecycleStage()`). Discovery needs a server-side Python port of that single
condition (§2) as a pure function over the `/state_all` snapshot. It is ~30
lines, fully specified in §5 of the lifecycle spec, and must be unit-tested
against the same fixtures.

## 4. What "surfacing" means — recommend a real proposal, not a candidate object

Two options:

| | create `pe_order_proposals` row (recommended) | separate lighter candidate object |
|---|---|---|
| reuses approval/evidence/kill-switch machinery | yes, for free | no — needs a new "promote to proposal" path |
| blast radius if discovery logic is wrong early | a spurious `PENDING_APPROVAL` row a human must still approve | smaller — candidate never touches the ledger |
| cost | none new | new table + promotion UI + its own tests |

**Recommendation: create a real `open` proposal** (`mode=APPROVAL_REQUIRED`,
`status=PENDING_APPROVAL`). The discovery logic is read-only and only *suggests*;
the human still approves. The "candidate object" alternative is only worth it if
we expect discovery to be badly wrong at first — but §2's condition is the
already-validated ignition stage, not a fresh heuristic, so the extra indirection
buys little. If review disagrees, the candidate-object option is the fallback.

## 5. The `open` evidence-reconstruction gap (must be closed to build this)

Real finding from reading the code: `cloud_state.reconstruct_cloud_state`
returns `None` when `position_ref is None` (cloud_state.py, the position block).
Every `open` proposal has no `position_ref`, so **today an `open` proposal cannot
be reconstructed at all** — this is *why* the system only evaluates held
positions.

Discovery therefore requires a small extension: for `action == "open"` (no
position), `reconstruct_cloud_state` must return a **position-less** snapshot —

- `underlying` (confirm/timing tone + `upper_neg` + heartbeat freshness) — already
  computed before the position check, just no longer discarded;
- `execution` (underlying heartbeat `close` + `source` as the price reference);
- `position = {exists: False, …}` (no position, no direction/side);
- `contract` stays absent — `policy_v1.json` requires **no** `contract_response`
  for `open` (only `underlying_dna`, `execution_quality`, `portfolio_risk`).

This keeps the four-root engine and the approval path untouched; it only lets
`open` reach them. No evidence gate is weakened.

## 6. Contract selection — chain + frozen DTE targets, no Greeks

From `massive_options.get_chain(symbol)` (already wired): pick the **ATM CALL**
(nearest strike to the current underlying close) at the listed expiration
**closest to the 14-DTE target, else 30-DTE** (the frozen DTE targets from the
options-DNÁ entry research). No Greeks, no IV, no probability — none are
available and none are invented. The `close` is the near-live daily close, and
the candidate's evidence states that freshness honestly (`DELAYED`), exactly as
the execution-quality root already does.

## 7. Symbol scope — AMC today, checklist tomorrow

Build AMC-only now, but parametrize by `tracked_symbols()` (already shipped in
`store.py`) and `asset_eligible()` (already shipped in `portfolio.py`) from the
start. Extending to the other 6 assets tomorrow is then the "checklist, not a
rebuild" item §7 of the multi-asset spec already promised — add the symbol to
`pe_experiment_symbols`, ensure it clears the eligibility gate, done. No
bespoke per-symbol code.

## 8. Frequency / triggering — on the existing paper tick, read-only

Run discovery on the same tick as the runner (`_paper_tick_safely` /
`run_once`), because ignition is a *fresh* flicker and the tick is already
event-driven off heartbeats/webhooks. Discovery is a **read-only step that
precedes** the runner's proposal/fill phases; it never mutates anything except
the proposal row it creates. It is cheap (a `/state_all` read + a chain read +
the §2 condition). Tradeoff: on-tick is the most responsive and can't miss the
ignition window; noise is bounded by §9's cap, not by slowing the scan.

## 9. Rate / volume limiting (alert-fatigue guard)

- **Idempotency/dedup:** one candidate per `(symbol, stage)` — a new ignition
  for the same symbol is not re-surfaced while a prior `open` proposal for that
  symbol is `PENDING_APPROVAL`/`APPROVED`.
- **Hard cap:** at most **3** surfaced candidates outstanding per experiment
  (all symbols), and at most **1 per symbol per trading day**.
- **Cooldown:** a symbol whose `open` proposal is `REJECTED` is not re-surfaced
  for the remainder of that trading day (the human has seen it and declined).
- These are stated thresholds, reviewed as part of this spec.

## 10. Grounded validation (read-only, AMC real history)

Ran the §2 ignition condition read-only over AMC's 2-year backfill
(`source='backfill_replay'`, the live Railway DB):

- **143 ignition clusters over 2 years** — roughly one every ~3–4 trading days,
  consistent with the cadence reported in `CAMPAIGN_LIFECYCLE_SPEC.md` §8.
  Discovery at that rate is a "campaign leg" cadence, not per-bar noise.
- **Most recent ignition moments (UTC):** 2026-07-02 12:30, 07-09 11:00,
  07-10 13:30, 07-15 09:45, 07-16 10:45, 07-20 19:30, 07-21 11:00, 07-24 11:00,
  07-29 13:30, 07-30 12:00, 07-31 11:00, **2026-08-07 12:30**.
- **Live check today (2026-08-16):** `/state_all/AMC` is **not** in ignition —
  `5m`/`15m` WAIT, `30m` RECOVERY WATCH, `60m`/`120m` RESOLVING (recent `FAIL`),
  `180`/`240`/`1D` WAIT. So discovery would surface **nothing** for AMC right now
  — the honest baseline, and the expected steady state between campaigns.
- **Chain availability:** `get_chain('AMC')` returns 256 contracts across 11
  expirations (weekly 2026-08-21 through 2028-01-21), so the §6 ATM-CALL/14-DTE
  selection has a real contract to point at whenever ignition fires.

This is the same grounded-validation discipline as the lifecycle spec's §8: the
condition fires at a sane cadence and is quiet when it should be.

## 11. Open items for review (not decided)

1. **Surfacing = real proposal vs candidate object** — §4 recommends the real
   `open` proposal; confirm before build.
2. **Contract direction/type scope** — v1 is LONG / CALL only (ignition is
   bullish). Are shares or short-side candidates wanted? (Separate authorization
   if so.)
3. **DTE target** — 14 primary / 30 fallback per the frozen research, or a
   single fixed target?
4. **Cap values** — 3 outstanding / 1-per-symbol-per-day / rejection-cooldown are
   proposals to review.

## 12. Boundary

Fail-closed throughout. Nothing here weakens `authoritative_provider_ready`,
evidence-root validation, the 30% AMC floor, the eligibility gate, or the
approval window — it expands *what gets proposed*, never how proposals are
approved. Read-only now; no code, no activation. Stops here for review before
any implementation.
