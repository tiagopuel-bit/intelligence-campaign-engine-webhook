# Paper Trade Desk Log

**Convention:** reverse-chronological — **newest entries go at the top**, under
the divider below. Add a new entry by inserting it immediately below the
`<!-- newest entries below -->` marker. Do not reorder old entries.

**Purpose:** the *why* behind Portfolio Challenge decisions that currently only
live in individual agent chats. Each entry is one decision point. This file is
append-only and git-tracked; every agent has read access to it.

**Format** (fixed):

```markdown
## <YYYY-MM-DD HH:MM PT> — <SYMBOL> — proposal #<id> (<ACTION>, position_ref=<n>, instrument_ref=<n>)

**Trigger:** <what fired — DNA read, catalyst, timer, etc.>
**Evidence roots:** underlying DNA ✅ · contract response ✅ · execution quality ✅ · portfolio risk ✅ → very_high=true
**Discussion:** <1-3 sentences of actual reasoning, or "none — auto path, no discussion">
**Decision:** <APPROVED by Tiago | auto-executed at deadline | REJECTED — reason>
**Outcome:** <filled at $X | cancelled — reason | still open, revisit after Y>
**Logged by:** <agent name>
```

**Minimum required fields:** date/time, symbol, proposal_id (or
`N/A — pre-proposal discussion`), decision, and who is logging it. Everything
else is best-effort — do not fabricate an outcome; if it is unknown yet, write
"unknown — follow up" and append/update later.

**Useful tables/fields:** proposals and lifecycle live in `pe_order_proposals`
/ `pe_proposal_events` / `pe_user_decisions` / `pe_paper_orders` /
`pe_paper_fills` (see `paper_execution/schema_v1.sql`). A read-only export
helper exists at `scripts/export_trade_desk_entry.py`.

---

<!-- newest entries below -->

## 2026-08-16 — AMC — N/A — pre-proposal discussion (Monday activation watch)

**Trigger:** handoff from Claude — DS covers Monday (2026-08-17) market-open
activation watch per `docs/MONDAY_ACTIVATION_RUNBOOK.md`.
**Evidence roots:** N/A — operational handoff acknowledgment, not a trade.
**Discussion:** Acknowledged the runbook: poll `GET /paper/health` from ~9:30am
ET, watch the five blockers clear in order (underlying heartbeat first, then
option instruments 6/8/9/10), and confirm `authoritative_provider_ready` flips
true while `runner_ready` stays false (experiment not yet seeded — P4). Local
baseline check (Sunday, market closed) shows the expected state: no fresh
heartbeats, `authoritative_provider_ready: false`. Will log each blocker
clearing / any stop-and-report trigger as it happens. Boundary: watch, log,
report — no approving/rejecting on Tiago's behalf, no kill-switch, no gate
changes.
**Decision:** coverage accepted; no action until Monday open.
**Outcome:** market closed — pending Monday open.
**Logged by:** DeepSeek

## 2026-08-15 12:30 PT — AMC — N/A — scope decision (Options DNA parked)

**Trigger:** Options DNA multi-asset external replication finished today —
`EXTERNAL_REPLICATION_NOT_CONFIRMED`, `promotion_forbidden: true`, 0/8 external
assets passing (see `reports/options_dna_replication/TOMORROW_REAL_TEST_READINESS.md`).
Discussion with Tiago clarified the corpus is `amc_provenance_only` — the
frozen `CALL/14` candidate was discovered entirely on AMC data, and today's
test was specifically checking whether it generalizes to future portfolio
assets. It doesn't (yet) — a coverage gap, not a directional miss.
**Evidence roots:** N/A — research/scope decision, not a trade proposal.
**Discussion:** Options DNA is not wired into the live AMC paper-execution
`VERY_HIGH` gate regardless of this result (that gate uses its own direct
contract-response check, independent of the discovered rule) — so today's
finding doesn't block or change anything about Monday's AMC activation.
Tiago decided to park the Options DNA research track entirely for now:
focus stays on trading AMC for real (paper) first, since that's where the
portfolio is concentrated. Options DNA / multi-asset generalization only
gets revisited once a second asset is actually about to be added to the
portfolio — not researched speculatively ahead of that.
**Decision:** Options DNA research paused. AMC paper-execution is the sole
active focus. No new candidate discovery authorized until a second asset is
imminent.
**Outcome:** N/A — scope/prioritization decision, not an outcome to track.
**Logged by:** Claude

## 2026-08-15 09:47 PT — AMC — N/A — pre-proposal discussion (PAPER_ONLY activation)

**Trigger:** manual activation setup, not a live DNA proposal.
**Evidence roots:** N/A — no proposal yet (activation/pre-flight note).
**Discussion:** Claude completed PAPER_ONLY activation. Five 1-minute
TradingView alerts are active (AMC underlying plus option instruments 6, 8, 9,
10); option alerts use OPTION_HEARTBEAT with exact position/instrument
references. Stale indicator removed; relay saved and compiled.
`/paper/health` intentionally reports five blockers while the market is closed
— these are closed-market conditions, not errors.
**Decision:** activation configuration complete (not a trade decision).
**Outcome:** market closed — no proposal activity expected until the open;
blockers expected to clear when the market opens.
**Logged by:** DeepSeek (seeding entry; activation commit a154066 is Claude's).
