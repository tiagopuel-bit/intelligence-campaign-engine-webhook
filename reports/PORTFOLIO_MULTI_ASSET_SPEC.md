# Portfolio Challenge — Multi-Asset Expansion Spec

**Status:** design/spec phase. Read-only against existing data; no code changed,
no experiment activated. Spec-then-build — wait for review before implementation.

## 0. Boundary — a conscious supersession, stated plainly

`docs/DEEPSEEK_AMC_PAPER_AUTO_EXECUTION_HANDOFF.md` said adding assets to
paper-execution "requires a separate pre-registered study, not ad hoc addition."
This document **is** that study. The reasoning for moving past AMC-only is a
portfolio-construction decision, not setup-chasing: the January-2027 North Star
is far more achievable diversified across the seven deep-backfilled assets than
concentrated in one, and **AMC stays the anchor rather than being replaced.**
This is not the "add a hot setup opportunistically" behavior the original
boundary guarded against.

Scope: the **7 deep-backfilled assets** — AMC, GME, PYPL, RBLX, SPY, VALE, U.
MARA / TSLA / ARB stay watchlist candidates with their own thinner data and are
**out of scope** until they earn the same depth.

## 1. Experiment / portfolio model — recommend one experiment, multi-symbol

Today: `pe_experiments` = one row, one `symbol`, one cash pool
(`pe_paper_cash` UNIQUE per experiment), one `GLOBAL` kill switch, and
`_validate_experiment` enforces `proposal.symbol == experiment.symbol`.

**Options:**
- (a) **One experiment spanning 7 symbols** under a shared cash pool.
- (b) **7 linked experiments** under a shared portfolio rollup.

**Recommendation: (a).** The North Star is a single number ("Total Portfolio
Value"), the 30% AMC floor is a single-experiment-wide ratio, and the existing
paper ledger already values every position in one place. (b) would force the
rollup + floor logic to aggregate across 7 cash pools for no benefit.

Concrete schema change for (a): add a `pe_experiment_symbols(experiment_id,
symbol)` join table; keep `pe_experiments.symbol` as the **anchor** (AMC) for
the existing single-symbol validation path, and change `_validate_experiment`
to accept any symbol in the experiment's tracked set. Shared cash pool and
single `GLOBAL` kill switch stay exactly as they are.

## 2. The 30% AMC floor — closed rules

Definitions: `A` = AMC market value (shares + options), `T` = total portfolio
value (cash + all paper positions), `w = A / T`.

**R1 (deployment-time block).** A non-AMC `open`/`add` proposal is rejected at
creation **and** at revalidation when its projected weight breaches the floor:

```
if symbol != AMC and action in {open, add}:
    projected_w = A / (T + notional)
    if projected_w < 0.30:  block(reason=AMC_FLOOR_WOULD_BREACH)
```

**R2 (drift → flag, never auto-trade).** Natural price drift that pushes
`w < 0.30` (AMC declining, or others appreciating) is **flagged** in the daily
report and keeps R1's non-AMC-add block active, but triggers **no** automatic
rebalancing. Force-selling other assets to "top AMC back up" is an execution
action with its own risk and is **out of scope** — a human decision each time.

## 3. Per-symbol kill switch (in addition to GLOBAL)

Keep `GLOBAL` as the full-stop. Add a `scope='SYMBOL'` value to
`pe_auto_switches`, storing the symbol in the existing `position_ref` column
(reusing the `UNIQUE(experiment_id, scope, position_ref)` key — no schema
change). `kill_switch_active(conn, experiment_id, position_ref=…, symbol=…)`
gains a symbol check, and both claim paths pass the proposal's `symbol` so a
bad fill or stuck approval on one asset stops only that asset. This is the same
shape as the per-position enforcement fix already shipped for Finding A.

## 4. AMC-only assumptions — audit findings

Confirmed hardcodes (read-only audit of `paper_execution/`):

| site | what's hardcoded | change needed |
|---|---|---|
| `cloud_state.py:69` (`cloud_readiness`) | underlying heartbeat `symbol='AMC'` | loop the tracked symbol set |
| `cloud_state.py:75` (`cloud_readiness`) | open positions `p.symbol='AMC'` | loop the tracked symbol set |
| `activation.py:26` | `activate_if_ready(..., symbol="AMC")` default | activate the multi-symbol experiment |
| `webhook_receiver.py:521` | `activate_if_ready(..., "AMC")` call | pass the tracked set |

`cloud_state.reconstruct_cloud_state` already takes a `symbol` parameter and is
symbol-agnostic; `engine.py`'s four evidence-root functions are pure functions
over evidence dicts with **no** symbol reference — no change needed there.

## 5. Per-asset eligibility gate (reliability gating real trades)

Reuse the campaign-lifecycle reliability discipline. An asset is
**trade-eligible** iff, from `tables/dna_campaign_lifecycle_reliability.csv`:

1. its backfill depth clears the sample floor — every timeframe in the
   `timing`+`confirm`+`owner` tiers has ≥ 25 classified bars; **and**
2. those tiers are marked `reliable=1`.

Ineligible assets (thin/noisy) are **not** live-tradable: proposals are blocked
with `ASSET_NOT_ELIGIBLE`. This makes the reliability mask a real execution
gate, not just a dashboard badge — the exact discipline the CHWY-noisy-tier
case motivated.

## 6. Capital allocation across the remaining 70%

**Equal weight: each non-anchor asset gets 70% / 6 ≈ 11.7% of TPV.** Rationale:
the DNA confidence is not validated enough to size capital (confidence-weighting
would over-claim precision), and equal weight is the simplest defensible model.
Existing per-trade caps already bound concentration (single contract 15%,
single expiration 25%, total options 50%). Confidence-weighting is a later
refinement, gated behind its own study.

## 7. Onboarding the next asset — what's data-driven vs human

**Data-driven (no code change):** run `backfill.py` for the symbol → recompute +
append the reliability mask → the symbol crosses the eligibility gate → add it
to `pe_experiment_symbols`. Done.

**Human decision every time:** *which* asset enters the remaining 70% (portfolio
construction), and whether to relax anything — never auto-decided. The 30%-floor
and equal-weight rules are fixed logic and don't change per asset.

**Honest caveat:** this is not zero-touch. Backfill window depth, the reliability
floor, and the tracked-set membership are each still a conscious call — what's
now free is that none of them requires a bespoke `cloud_state.py` edit or a
hand-rolled mask anymore.

## 8. Grounded validation (read-only, 7 assets' real backfill)

### Eligibility gate

| asset | 5m | 15m | 30m | 1H | 2H | 3H | 4H | eligible |
|---|---:|---:|---:|---:|---:|---:|---:|:---:|
| AMC | 1959 | 577 | 269 | 92 | 53 | 54 | 34 | ✅ |
| GME | 2073 | 701 | 293 | 162 | 95 | 84 | 32 | ✅ |
| PYPL | 1885 | 699 | 373 | 152 | 86 | 90 | 43 | ✅ |
| RBLX | 2123 | 735 | 331 | 162 | 90 | 62 | 29 | ✅ |
| SPY | 2140 | 785 | 396 | 199 | 117 | 105 | 45 | ✅ |
| VALE | 2140 | 817 | 409 | 126 | 65 | 86 | 54 | ✅ |
| U | 1895 | 696 | 398 | 158 | 88 | 79 | 42 | ✅ |
| MARA (out of scope) | 1177 | 448 | 157 | 78 | 62 | 46 | **0** | ❌ thin |

All 7 in-scope assets clear the gate (deep + reliable). MARA — the thin
candidate — correctly fails, which is the gate working as intended.

### 30% floor sanity — the finding that matters

Buy-and-hold simulation over the aligned 2-year 1D closes (501 days, AMC 30% /
others 11.7% each, no rebalancing):

```
AMC weight: 0.063 .. 0.300   →   AMC below 30% on 501/501 days (100%)
```

AMC declined sharply across the backfill, so under **buy-and-hold** the 30%
floor is breached essentially always. This proves the floor must be read as a
**deployment-time constraint** (R1), not a "maintain 30% at all times" target —
because "maintain at all times" would imply constant force-rebalancing, which
R2 explicitly forbids. The spec's R1/R2 split (block new non-AMC adds below the
floor, flag drift, never auto-rebalance) is exactly what this data demands.

## 9. Open items for review (not decided)

1. Should R1's floor check use projected weight (block the specific trade) or
   current weight (block any non-AMC add while below floor)? Spec assumes the
   stricter projected-weight check.
2. Per-symbol kill switch: reuse `position_ref` (spec's proposal) vs a new
   `symbol` column.
3. Whether the eligibility gate's 25-bar floor should be per-tier or asset-wide.

## 10. Boundary

Fail-closed throughout: nothing here weakens `authoritative_provider_ready`,
evidence-root validation, or kill-switch discipline — it expands *which assets*
the existing safety model covers. Read-only; no code, no activation. Stops here
for review before any implementation.

## 11. Auto-entry policy (open question — requires separate sign-off)

**Current state (unchanged):** `paper_execution/engine.py` sets
`VERY_HIGH_AUTO_ACTIONS = ("partial_reduce", "close")` — auto-execution
(`AUTO_IF_VERY_HIGH_PAPER`) exists only for risk-*reducing* actions. Every new
position (`open`/`add`) requires manual approval, no exception. This section
decides whether that changes once the multi-asset model is live. It needs
**explicit sign-off separate from §1–§9**, even though it lives in this document.

### Option A — stay manual-only for entries (no change)

Entries remain `APPROVAL_REQUIRED`; auto stays risk-reducing-only.

- **Risk:** none added. The safest state; auto can never deploy new exposure.
- **Cost:** every entry depends on Tiago answering the 10-minute approval window
  in time — the same manual gate that exists today, just now across 7 assets
  instead of 1 (more alerts, but no *new* safety surface).

### Option B — auto-entry scoped to AMC only, top confidence tier, hard caps

`open`/`add` on AMC becomes auto-eligible only when `VERY_HIGH` passes *and* an
additional confidence gate passes, with a hard size cap and a per-day count cap.
The other 6 assets stay manual.

- **Risk:** auto can deploy AMC exposure unattended; a wrong entry signal
  converts directly into a wrong position. Mitigated by: AMC-only scope (the
  deepest-data anchor), the `VERY_HIGH` four-root gate, size + per-day caps, and
  the existing kill switches.
- **Cost:** partial — the anchor can capture entries unattended, but the 6 other
  assets still need manual approval.

### Option C — auto-entry across all 7, per-asset caps

`open`/`add` auto-eligible for every in-scope asset, with per-asset size/count
caps.

- **Risk:** highest — unattended capital deployment across the whole book, on
  the *least* validated signals (the reliability/eligibility data is deep but
  has never been validated for auto-deployment). A single bad day multiplies
  across 7 assets.
- **Cost:** none (full unattended entry coverage) — but at the price of the
  largest safety regression in this spec.

### Recommendation: **Option A**, with Option B as an explicitly-gated later step

Stay manual-only for entries at multi-asset launch. The existing auto model
already encodes the correct principle — automate what *reduces* risk
(`partial_reduce`, `close`), never what *adds* exposure — and the multi-asset
expansion doesn't change that reasoning. Option B (AMC-only auto-entry) is the
reasonable next step **only after** the manual-entry quality is observed for a
defined period (e.g., a minimum number of manual AMC entries with a
pre-registered false-entry rate below a threshold). Option C is not recommended
at this time.

**This section is an open question and requires separate, explicit sign-off from
Tiago before it enters any implementation — it is deliberately not bundled with
the §1–§9 decisions.**

