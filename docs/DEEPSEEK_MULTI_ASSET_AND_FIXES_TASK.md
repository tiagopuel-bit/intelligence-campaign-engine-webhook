# Handoff — three build items, decoupled from tomorrow's AMC market-open watch

**From:** Claude, 2026-08-17 evening. **For:** DeepSeek.

## Context

Production is healthy (tonight's `TRACKED_SYMBOLS` import hotfix, `f27850c`,
is live). Tomorrow morning is AMC-only signal verification — none of this
blocks or is blocked by that.

**Updated priority (2026-08-17 evening, Tiago's explicit call):** build item
3 now, in parallel with AMC — do not wait for AMC to prove itself live
before doing this work. Goal: get tracking/eligibility/heartbeat plumbing
ready for all 7 assets (AMC, GME, PYPL, RBLX, SPY, VALE, U) so they're
"close to ready" on the engineering side. Trading focus stays on AMC —
deep AMC research/improvement continues, and the next asset to actually
open a paper position in is a deliberate choice Tiago makes later, not
automatic. Building the join-a-live-experiment capability and actually
using it to add a new tracked asset are two separate steps — build now,
activate per-asset only when Tiago says so (see item 3's boundary note,
unchanged).

Do not touch tomorrow's AMC activation watch (Claude has that). Do not
deploy/commit/push any of this without full suite + `git diff --check` clean,
and hand back for review same as always.

## 1. Live paper-cash balance on the dashboard (small, do first)

**Bug:** `ui/dna_dashboard.html:1818` reads `experiment.starting_cash` as the
displayed cash figure, both pre- and post-activation. Once trades execute,
the real running balance lives in `pe_paper_cash.cash` and is never surfaced
— the dashboard silently keeps showing the frozen starting value forever.

**Fix:** `get_experiment()` in `paper_execution/api.py:149` returns the raw
`pe_experiments` row only — join in (or add a field for) the current
`pe_paper_cash.cash` value for that `experiment_id`, and have the dashboard
read that live figure once an experiment is active (fall back to
`starting_cash` pre-activation, as today). Add a test asserting the API
response includes live cash after a simulated fill changes it.

## 2. Auto-entry for `open`/`add` — AMC-only, confirmed scope

Tiago's call (confirmed explicitly): extend auto-execution to new AMC
entries, **scoped to AMC only for now** — not the other 6 assets. This
matches `reports/PORTFOLIO_MULTI_ASSET_SPEC.md` §11 Option B, the
spec's own recommended first step (not Option C — never open this to
everything at once).

**Current state:** `paper_execution/engine.py:16`:
```python
VERY_HIGH_AUTO_ACTIONS = ("partial_reduce", "close")
```
`open`/`add` always require manual approval, no exception, on any symbol.

**Change:** make this symbol-aware — `open`/`add` become auto-eligible only
when `symbol == ANCHOR_SYMBOL` ("AMC") **and** `VERY_HIGH` still passes at
the 10-minute revalidation deadline. Every other symbol's `open`/`add` stays
manual-only, unchanged. Existing caps already apply and don't need new
config: `max_paper_auto_executions_per_day` (3, from
`experiment_goal_v1.json`), and the allocation/floor checks already
enforced in `runner.py`'s revalidation path (`AMC_FLOOR_WOULD_BREACH`,
`ALLOCATION_CAP_EXCEEDED` — though those specific two don't fire for AMC
itself, since AMC is the anchor; AMC opens are still bounded by
`single_contract_max_pct`/`single_expiration_max_pct`/`total_options_max_pct`
wherever those are actually enforced — **check whether they're enforced
anywhere yet**; if not, that's a gap worth flagging back, not silently
building around).

Write tests: AMC `open` auto-executes at deadline when `VERY_HIGH` passes;
AMC `open` does NOT auto-execute when `VERY_HIGH` fails (falls back to
manual/expired, unchanged); a non-AMC `open` (e.g. GME) never auto-executes
regardless of `VERY_HIGH`, even after item 3 below is wired up.

## 3. Multi-asset: build the missing "join an already-active experiment" path

This is the real gap, not what the spec doc's stale "read-only, no code"
status line suggests. Reality check first — go verify what's already built
before touching anything:

- `paper_execution/portfolio.py`, `runner.py`, `store.py`,
  `schema_v1.sql` already implement the 30% AMC floor (deployment-time
  block, R1), equal-weight 70%/6 allocation cap, per-symbol kill switch,
  and `pe_experiment_symbols`/`tracked_symbols()`.
- `tests/test_amc_paper_execution_multi_asset.py` — 10/10 passing already.
- All 7 in-scope assets (AMC, GME, PYPL, RBLX, SPY, VALE, U) already clear
  the eligibility gate per the spec's own §8 backfill table — no new
  backfill/DNA work needed data-wise.

**What's actually missing:** `activate_if_ready()` in
`paper_execution/activation.py` only ever writes `pe_experiment_symbols` at
the moment an experiment first transitions to `ACTIVE`, and it requires
every symbol passed in to *already have open holdings* at that exact
moment — all-or-nothing, one-shot. Since AMC activates alone tomorrow and
other assets join later (not simultaneously), there is currently no
function to add a symbol to an experiment that's already `ACTIVE`.

Build `join_symbol_if_ready(paper_db_path, webhook_db_path, experiment_id,
symbol)`:
- Requires the experiment to be `ACTIVE` (error otherwise).
- Requires the symbol to pass `asset_eligible()` (already built,
  `portfolio.py:88`) against the reliability mask.
- Requires a fresh underlying heartbeat for the symbol (same `MAX_AGE_MS`
  freshness check `activate_if_ready` already uses) — but, unlike initial
  activation, **does not require pre-existing open holdings**. A newly
  joined asset starts at zero position in the shared cash pool; it gets
  funded by a future `open` proposal under the existing 70%/6 allocation
  cap and 30% floor checks `runner.py` already enforces. (If you think it
  should require a starting position instead, matching the AMC-anchor
  pattern, stop and ask — don't assume; this changes the onboarding UX
  materially.)
- Inserts into `pe_experiment_symbols` atomically, same transactional
  discipline as the rest of `activation.py`.
- Fails closed with a clear reason (`ASSET_NOT_ELIGIBLE`,
  `BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT`, `ALREADY_TRACKED`) — no silent
  no-ops.

Write tests mirroring `test_amc_paper_execution_multi_asset.py`'s existing
style: eligible symbol with fresh heartbeat joins successfully; ineligible
symbol is rejected; stale heartbeat is rejected; already-tracked symbol is
a no-op with a clear status, not an error; experiment not yet active is
rejected.

**Do not wire this into `webhook_receiver.py` or activate anything in
production** — this stays local/tested/committed-but-inert until Tiago
explicitly says to turn a specific asset on. Do not resolve spec §9's open
items (floor check semantics, kill-switch column choice, eligibility floor
granularity) beyond what the existing code already assumes — flag if you
find the existing code's assumption looks wrong, don't silently change it.

## 4. SL/TP brackets need to go through the discussion/approval lifecycle

**Current gap (confirmed by Claude tonight):** `POST /paper/brackets`
(`paper_execution/api.py:349`) creates a bracket immediately via a raw
authenticated API call — no proposal, no evidence roots, no discussion, no
approval window. Nothing today auto-calls this (checked: no engine/insight
code path creates a bracket on its own), so it's not an unsafe silent-auto
problem — but it also means there's no way for DNA to *suggest* a stop/
target with reasoning and have Tiago review it before it's set, the way
`open`/`close`/`roll` proposals already work. There is also **no dashboard
UI at all** for brackets — not visible, not creatable, not listable
(confirmed: zero references in `ui/dna_dashboard.html`).

Tiago wants: DNA proposes a bracket (stop/target levels + reasoning) the
same way it proposes other actions — it shows up in the Decision Queue,
he approves/rejects/modifies, and only then does `upsert_bracket` actually
get called. Once a bracket exists and triggers, it should keep firing
immediately without the 10-minute window (that part is correct today and
should not change — a stop-loss that waits 10 minutes isn't a stop-loss).

Scope for this item:
- A new proposal action type (e.g. `set_bracket`) that carries
  `stop_price`/`target_price` through the same `PENDING_APPROVAL` →
  `APPROVED`/`REJECTED`/`EXPIRED` lifecycle already used elsewhere in
  `paper_execution/api.py`'s `create()` / `_decision_endpoint()`.
- On approval (or auto-approval if you decide `set_bracket` ever qualifies
  for `VERY_HIGH` auto — **don't assume this, ask**; brackets are risk-
  reducing by nature so it's plausible but not decided), call
  `upsert_bracket` with the approved prices.
- Dashboard: a minimal panel showing active brackets per position (ticker,
  direction, stop, target) — reuse `GET /paper/brackets` (already exists)
  — plus wherever the Decision Queue renders other proposal types, render
  `set_bracket` proposals the same way (reasoning text, approve/reject).
- Tests: proposal created but bracket NOT set until approved; approved
  proposal calls `upsert_bracket` with the exact approved prices (not
  re-derived); rejected/expired proposal never creates a bracket.

This item is lower priority than 1-3 — do it after, not instead of.

## Boundary (same as always)

No schema/gate changes beyond what's scoped above. No deploy/commit/push —
hand back for review. No activating any additional symbol in production.
Full suite + `git diff --check` clean for each of the three items; report
results separately per item so partial progress is legible if you don't
finish all three in one pass.

## What to report back

Per item (1-4): what changed (file/line), new/updated tests and their
names, full suite result, `git diff --check` result. For item 3
specifically: your answer to the starting-position question above if you
had to make a call, flagged clearly as a judgment call for Tiago to
confirm, not a silent decision. For item 4: whether you left `set_bracket`
out of `VERY_HIGH_AUTO_ACTIONS` (default — do this unless told otherwise)
or added it, and why, if you did.

Log a summary entry to `docs/PAPER_TRADE_DESK_LOG.md` when you finish any
of these, same convention as always.
