# AMC Paper Execution — P3 Asset Page / Daily Report Acceptance

Status: `P3_CODE_VERIFIED_NO_DASHBOARD_CHANGE_NEEDED`

The P3 Asset Page + daily AMC report layer is already implemented in
`ui/dna_dashboard.html` and satisfies seven of the eight checkpoint-P3
requirements in full, with the eighth satisfied at proposal-lifecycle
granularity. No dashboard change was required; the only residual gaps are
backend data-exposure limitations that are explicitly out of this task's
boundary (documented, not invented around).

## 1. Status and authorization boundary

- Scope: verify checkpoint P3 against `DEEPSEEK_AMC_PAPER_AUTO_EXECUTION_HANDOFF.md`
  §"Checkpoint P3", confirm what exists, close only genuine dashboard-only gaps.
- **No backend/schema change was made.** `webhook_receiver.py`, `positions.py`,
  Pine/webhook ingestion, `paper_execution/` write paths, and the broker path
  were not modified.
- `ui/dna_dashboard.html`, `webhook_receiver.py`, and `positions.py` already
  carry unrelated uncommitted work from a separate in-progress "Manage" dialog
  feature. This task added **zero** changes to those files, so it neither
  builds on nor conflicts with that work.
- No deployment, no P4 activation, no commit/push.

## 2. Commands and test counts

```bash
PYTHONPYCACHEPREFIX=/tmp/p3_pycache \
  python3 -m unittest tests.test_amc_paper_execution_p3_ui -v
#   -> Ran 6 tests ... OK

PYTHONPYCACHEPREFIX=/tmp/p3_pycache \
  python3 -m unittest discover -s tests -p "test_amc_paper*"
#   -> Ran 74 tests ... OK  (full paper-execution suite)

PYTHONPYCACHEPREFIX=/tmp/p3_pycache \
  python3 -m unittest discover -s tests
#   -> Ran 373 tests ... OK  (full repository suite)
```

`git diff --check` clean for this task's new files.

## 3. Requirement-by-requirement verification (available vs missing)

| # | P3 requirement | Status | Location / evidence in `ui/dna_dashboard.html` |
|---|---|---|---|
| 1 | Experiment progress toward Jan 2027 target (Silver/Gold/Premium/Diamond) | ✅ present | `paperMilestones()` (1490), North Star progress %, milestone track + labels (1595-1596) |
| 2 | Current value, realized/unrealized P&L, drawdown from high | ✅ present | `paperCurrentSnapshot()` (1536), KPI block: Total portfolio value / Open-position P&L + Realized / Drawdown from high (1591-1593) |
| 3 | Daily AMC campaign summary | ✅ present | "AMC campaign" daily item with headline + why (1600) |
| 4 | Position-level action queue | ✅ present | "Decision queue" + per-proposal rows (1597, 1575) |
| 5 | Pending proposal countdown + evidence | ✅ present | `paper-countdown` + `paperTimeLeft` (1560), `time_sensitive_reason` / `very_high` evidence line (1558, 1561) |
| 6 | Approve / Modify / Reject / Cancel auto controls | ✅ present (Cancel auto gated) | Approve/Modify/Reject buttons (1562), "Cancel auto" button (1589, disabled until the P2A kill-switch endpoint is accepted) |
| 7 | Unmistakable PAPER badges on every order and fill | ✅ present | `paper-badge` "Paper only" (1589) + `paper-badge` "Paper" on every proposal row (1559) |
| 8 | History comparing DNA proposals, user decisions, simulated outcomes | ⚠️ partial (backend-limited) | Proposal queue shows DNA action + reason + `current_status` (lifecycle encoding decision + execution); see §7 |

The P3 static test suite (`test_amc_paper_execution_p3_ui.py`) already asserts
the approved goal contract, daily-report/decision-queue presence, fail-closed
provider gating (`h.authoritative_provider_ready === true`), authenticated
`/paper/proposals` mutations with no broker route, and that server-owned
evidence fields are never sent by the UI.

## 4. Policy / schema hashes (frozen, unchanged)

| Artifact | sha256 (first 16) |
|---|---|
| `paper_execution/schema_v1.sql` | `35037cd29363f803` |
| `paper_execution/policy_v1.json` | `7688b012a2355aec` |
| `paper_execution/experiment_goal_v1.json` | `e3b2f665e5400aaf` |

Goal contract remains `FROZEN_APPROVED_V1` (Silver $6k / Gold $8k / Premium
$10k / Diamond $15k, AMC strategic floor 30%, drawdown limit −25%).

## 5. Proposal and fill semantics (unchanged, confirmed)

- Proposals are created server-side from authoritative cloud state; the UI only
  submits `action`, `symbol`, `position_ref`/`instrument_ref` (never `very_high`,
  `evidence`, `freshness`, `price_*`, `policy_sha256`, or `mode` — asserted by
  the test suite).
- `Approve`/`Reject`/`Cancel` post to `/paper/proposals/<id>/…` with auth; the
  server enforces the 10-minute window, `expected_from=PENDING_APPROVAL`, and
  records a `pe_user_decisions` row.
- Paper fills are simulated server-side (`simulate_order`, conservative
  bar-close model, no bid/ask); missing prices resolve to
  `UNSCORABLE_EXECUTION_DATA`.

## 6. Safety / race / restart verification

- `paperExecutionReady()` requires `authoritative_provider_ready && runner_ready
  && !global_auto_disabled`; controls stay disabled otherwise.
- "Cancel auto" is present but disabled pending the P2A kill-switch endpoint
  (`set_kill_switch` exists in `store.py` but is not yet routed) — fail-closed
  by design, not a P3 UI defect.
- Paper mutations are authenticated (`authHeaders()`) and never reach a broker
  (no `/broker/order` or `/orders/live` — asserted by the test suite).

## 7. Blockers and honest unscorable cases

No P3-specific blocker. Two backend-exposure limitations were identified and
are reported explicitly rather than worked around:

1. **"Cancel auto" control** is rendered but disabled with
   "Enabled only after the P2A kill-switch endpoint is accepted". Enabling it
   requires a global kill-switch API route (`set_kill_switch` is not wired to a
   route yet). This is a backend endpoint, out of scope for a dashboard-only
   change.
2. **Granular history (requirement #8).** `/paper/proposals` returns only
   `pe_order_proposals` rows (`current_status` encodes decision + execution
   outcome). The granular user-decision records (`pe_user_decisions`) and
   simulated fills (`pe_paper_fills`) and outcome snapshots
   (`pe_outcome_snapshots`) are not exposed by any GET endpoint, so a
   three-way "DNA proposal vs user decision vs fill" comparison cannot be
   rendered dashboard-only without a backend addition. The dashboard already
   shows the lifecycle comparison that the current API supports.

These are documented as honest gaps; no field was invented and no backend
endpoint was added.

## 8. Files created / modified

- **Created:** `reports/amc_paper_execution/P3_ASSET_PAGE_REPORT.md` (this file).
- **Modified:** none. `ui/dna_dashboard.html`, `webhook_receiver.py`,
  `positions.py`, and everything under `paper_execution/` were left exactly as
  found (the first three already had unrelated uncommitted changes).

## 9. Proof production / Pine / webhook ingestion / broker stayed untouched

- `webhook_receiver.py` and `positions.py` are modified in the working tree only
  by the pre-existing unrelated feature; this task made no edit to them
  (`git diff` on those files is unchanged from before this task).
- No Pine, Railway, alert, or broker-path change was made.
- No secrets were added or read into any artifact.

## 10. Explicit stop before P4

Checkpoint P4 (paper activation) is **not** started. Activation requires a live
market session plus explicit authorization, the atomic portfolio snapshot, and
experiment seeding. This task stops at P3 verification and documentation.
