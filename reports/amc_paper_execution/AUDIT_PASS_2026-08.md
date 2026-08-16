# AMC Paper Execution — Independent Auditor Pass (2026-08)

**Method:** adversarial read of the whole `paper_execution/` module set
(`engine.py`, `state.py`, `store.py`, `fill.py`, `runner.py`, `api.py`,
`cloud_state.py`, `activation.py`, `policy.py`, `schema_v1.sql`,
`policy_v1.json`, `policy_corrections_v1.2.json`) plus the webhook tick
integration in `webhook_receiver.py`. No code was changed.

**Verdict:** no actively-dangerous fail-open execution bug was found. The
previous P2A fail-open (status set to `PAPER_EXECUTED` without an order/fill
record) remains fixed: execution is a single transaction that writes
orders+fills+ledger before the final status transition. The findings below are
latent-correctness and hygiene issues, not live safety holes. None is being
fixed in this pass, per the audit boundary.

## Findings

### A — Per-position kill switch is not enforced by the runner (MEDIUM, latent)

`kill_switch_active()` in `store.py` supports a per-position scope
(`position_ref`), but both claim paths call it without `position_ref`:

- `store.py:233` (`claim_due_proposal`) → `kill_switch_active(conn, row["experiment_id"])`
- `store.py:281` (`claim_approved_proposal`) → `kill_switch_active(conn, row["experiment_id"])`

So a per-position kill switch (once `set_kill_switch(scope="POSITION",
position_ref=...)` is exposed) would be silently ignored by the auto-execution
and user-approved paths. This is currently dormant only because `set_kill_switch`
has **no API route** (the P3 report already flagged this). When the kill-switch
endpoint is wired, it must pass `position_ref=row["position_ref"]` through to
`kill_switch_active` in both claim functions, and the tests must cover the
POSITION scope (today `test_amc_paper_execution_p1/p2` only exercise GLOBAL).

### B — Expired non-auto proposals never transition to EXPIRED (LOW, hygiene)

`due_proposals(auto_only=True)` returns only `AUTO_IF_VERY_HIGH_PAPER`
proposals, and `claim_due_proposal` only claims auto-mode proposals. A
`PENDING_APPROVAL` proposal in `APPROVAL_REQUIRED` mode that passes its
10-minute deadline is therefore never auto-claimed and never reaches `EXPIRED`
(nothing emits that transition). It lingers as `PENDING_APPROVAL` until a human
rejects/cancels it. The `APPROVE` endpoint's expiry check blocks late approval,
so this is UI/hygiene clutter, not a safety bug. A bounded sweep that
transitions overdue `PENDING_APPROVAL` → `EXPIRED` would close it.

### C — `modify` supersession cancels the parent without a CAS rowcount check (LOW, race)

`modify_proposal_transactional` (`store.py:410-414`) cancels the parent with
`UPDATE ... WHERE id=? AND current_status='PENDING_APPROVAL'` but does not
assert `rowcount == 1`. A concurrent `APPROVE` (which uses a proper
compare-and-set in `transition`) could win, leaving the parent `APPROVED`
(and later executable) while a superseding child is also committed. The child
is `PENDING_APPROVAL` and never auto-executes, so this is not fail-open, but
the parent cancellation should roll back when `rowcount != 1`.

### D — Roll reconstruction silently resolves to UNFILLED (LOW, completeness)

`reconstruct_legs` returns `(None, instrument_type)` when a roll lacks exactly
two legs, and `reconstruct_cloud_state` never populates `roll_legs`. Every roll
therefore yields `EMPTY_ORDER` → `UNFILLED`, and `revalidate` does not verify
the roll-specific two-leg requirement. Policy (`policy_v1.json` `roll_fill`)
says a roll without two priced legs is `UNSCORABLE_EXECUTION_DATA`. Roll is
`APPROVAL_REQUIRED` (never auto), so it cannot auto-execute, but a
user-approved roll would silently `UNFILL` instead of reporting `UNSCORABLE`.
Roll is effectively not implemented end-to-end; either implement `roll_legs`
in the cloud state provider or make an unreconstructable roll fail closed as
`UNSCORABLE_EXECUTION_DATA`.

### E — SHARE contract_response root is synthetic (LOW, documentation)

For SHARE instruments `reconstruct_cloud_state` sets `contract.option_return=1.0`,
`matched_bars=12`, `activity_ratio=1.0` — a synthetic "active print". The
`contract_response` root therefore passes trivially for shares, and since
`close`/`partial_reduce` on shares ARE auto-eligible, a share close can be
`VERY_HIGH` with no genuine contract-level response. This is likely intended
(shares have no option contract; the underlying heartbeat is the contract), but
it contradicts the literal "`very_high_requires_all_four_roots`" wording and
should be documented explicitly.

### F — Engine/policy staleness threshold mismatch (INFO)

`policy_v1.json` declares `execution_quality.max_bar_staleness_minutes: 15`,
but `engine.py` enforces `LIVE_FRESHNESS_MAX_MINUTES = 2`. The engine is
strictly stricter (fail-closed), so this is not a safety issue — but the two
numbers should be reconciled to avoid a future reader trusting the 15-minute
figure.

## Confirmed-correct areas (no bug found)

- **Idempotent creation:** `UNIQUE(experiment_id, idempotency_key)` +
  `INSERT OR IGNORE`; duplicate keys return the existing id.
- **Compare-and-set everywhere:** `transition`, `claim_due_proposal`,
  `claim_approved_proposal` all assert `rowcount == 1`; losers roll back.
- **Revalidation on both paths:** user-approved and auto-due proposals both run
  `revalidate()` against freshly reconstructed evidence (all four roots +
  vetoes); stale state → `CANCELLED_REVALIDATION`.
- **Ref mismatch fails closed:** `POSITION_REF_MISMATCH` /
  `INSTRUMENT_REF_MISMATCH` → `CANCELLED_REVALIDATION`.
- **Global kill switch** enforced at both claim paths (`kill_switch_active`).
- **Two-leg atomicity:** `simulate_order` marks the whole order
  `UNSCORABLE_EXECUTION_DATA` if any leg is unscorable; fills are written per
  leg and the ledger applies only FILLED legs.
- **Fill model fail-closed:** missing/non-finite/non-positive price →
  `UNSCORABLE_EXECUTION_DATA`; quantity must be a positive integer; 100×
  multiplier derived from instrument type, not a caller default.
- **Single execution transaction:** `_process` wraps transition → orders/fills
  → ledger in one transaction (`commit=True` at the end), with rollback on any
  exception.
- **No broker path** and no future-outcome access (policy `FUTURE_FRAGMENTS`
  guard).
- **Approval-window expiry** is enforced on `APPROVE` (string compare of
  consistent UTC ISO timestamps) and re-checked in the claim CAS.

## Boundary honored

No code was changed; nothing found is "actively dangerous", so no fix is made
here. Production, Pine, webhook ingestion, and broker paths were not modified.
No commit/push.
