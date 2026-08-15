# Task packet — Close the P3 documentation gap + Monday activation runbook

**Requested by:** Tiago, 2026-08-15. **For:** DeepSeek. Two small, bounded,
AMC-focused pieces — Options DNA stays parked per today's scope decision
(`docs/PAPER_TRADE_DESK_LOG.md`), and nothing here touches that track.

## Context

`reports/amc_paper_execution/P2A_INDEPENDENT_ACCEPTANCE.md` status is
`CODE_ACCEPTED_RELAY_CONFIGURATION_REQUIRED` — the one blocker it names
(the TradingView underlying/option heartbeat relays) was cleared today; see
`docs/PAPER_CHALLENGE_ALERTS_ACTIVATED_2026-08-15.md`. Checkpoint P3
(Asset Page / daily report) already appears substantially built —
`ui/dna_dashboard.html` has ~123 paper/proposal references and
`tests/test_amc_paper_execution_p3_ui.py` has 6 tests — but unlike P0 and
P2A, there's no formal P3 stop-report in `reports/amc_paper_execution/`.
Checkpoint P4 (activation) correctly hasn't started and can't until the
market is open Monday plus your explicit authorization — nothing here
tries to move P4 forward.

## Part 1 — Close the P3 gap

Verify, don't assume. Run `tests/test_amc_paper_execution_p3_ui.py` plus a
real browser check of `ui/dna_dashboard.html` against the exact P3
requirement list from `DEEPSEEK_AMC_PAPER_AUTO_EXECUTION_HANDOFF.md`:

- experiment progress toward the January 2027 target (Silver/Gold/Premium/
  Diamond milestones from `paper_execution/experiment_goal_v1.json`);
- current value, realized/unrealized P&L, drawdown from portfolio high;
- daily AMC campaign summary;
- position-level action queue;
- pending proposal countdown and evidence;
- `Approve` / `Modify` / `Reject` / `Cancel auto` controls;
- unmistakable `PAPER` badges on every order and fill;
- history comparing DNA proposals, user decisions, and simulated outcomes.

For anything missing or incomplete: implement it (dashboard-only, no
backend/schema changes should be needed if P2 already exposes the data —
if it doesn't, say so explicitly rather than inventing a field). For
anything already present: just confirm it with the test suite + a
screenshot/description, don't rebuild working code.

Write `reports/amc_paper_execution/P3_ASSET_PAGE_REPORT.md` following the
same "Required report format" the other checkpoints used (status/boundary,
commands/test counts, available/missing fields, safety verification,
blockers, files changed, confirmation that Pine/webhook/broker paths stayed
untouched, explicit stop before P4).

**Boundary:** dashboard/UI changes only if genuinely needed to close a real
gap — do not touch `webhook_receiver.py`, `positions.py`, or Pine/webhook
ingestion. (Note: those three plus part of `ui/dna_dashboard.html` already
have unrelated local uncommitted changes from a different in-progress
feature — a partial-close "Manage" dialog. Don't build on top of or
conflict with that uncommitted work; if your P3 changes to
`ui/dna_dashboard.html` would collide with it, stop and report the
conflict instead of resolving it yourself.) No deployment, no P4 activation,
no commit/push required from you — hand it back for review same as before.

## Part 2 — Monday activation runbook

A short, concrete doc — `docs/MONDAY_ACTIVATION_RUNBOOK.md` — for the first
live trading session after alert activation. Not a redesign of the P4
checklist already in the handoff doc; a **practical, copy-pasteable**
version of it:

- exact command(s) to poll `/paper/health` and what each blocker code
  means in plain language;
- the expected order blockers should clear in (underlying heartbeat first,
  then each option instrument) and roughly how soon after market open to
  expect the first one, given TradingView's 1-minute confirmed-bar timing;
- what `authoritative_provider_ready: true` and `runner_ready: true`
  actually unlock, versus what still requires your explicit approval;
- what a healthy first proposal should look like in `/paper/proposals`
  (fields to sanity-check: `very_high`, `evidence_roots`,
  `position_ref`/`instrument_ref`);
- explicit "stop and report, don't improvise" triggers — e.g. a blocker
  that won't clear after N minutes, an evidence root that looks fabricated,
  anything that smells like it's bypassing a gate;
- one line pointing back to `docs/PAPER_TRADE_DESK_LOG.md` as where the
  first real entry should be logged once something actually happens.

## What to report back

- P3: test results, what was already working vs. what you built, the new
  report file, confirmation Pine/webhook/broker paths are untouched.
- Runbook: just confirm it exists and is accurate against the real API
  responses you've already seen today (`/paper/health` shape, etc.) —
  no need for a separate verification report, this one's just a doc.
