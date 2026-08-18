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

## 2026-08-17 — N/A — blocked: Massive Indices entitlement not yet propagated

**Trigger:** `docs/DEEPSEEK_MASSIVE_INDICES_CHECK_TASK.md` — live check
against the deployed `MASSIVE_API_KEY` on Railway.
**Discussion:** `I:VIX` returned `403 NOT_AUTHORIZED` ("You are not
entitled to this data... upgrade your plan"); `AMC` control returned a
clean `200` with real OHLC bars. Key itself is valid — this is
specifically the Indices Basic entitlement (enabled in Tiago's Massive
dashboard) not yet propagated to the deployed key. Not a code issue,
nothing to fix here.
**Decision:** VIX vol-regime spec stays parked, no other work blocked by
it. Retest later; if still 403 after a reasonable wait, contact Massive
support directly.
**Outcome:** blocked, pending Massive-side propagation.
**Logged by:** Claude

## 2026-08-17 — N/A — review: four-item batch committed, join_symbol_if_ready confirmed final

**Trigger:** Claude's verify-then-commit pass on DS's four-item batch
(cash balance, AMC-only auto-entry, multi-asset join, set_bracket
lifecycle), plus ADV liquidity bands reviewed separately.
**Discussion:** Both reviewed line-by-line and shipped as separate
commits: `b03e788` (ADV bands) and `745c8d8` (the four-item batch).
Migrations verified data-preserving (explicit column lists checked
against pre-migration schema, not a blind `SELECT *`). Tiago
explicitly confirmed `join_symbol_if_ready()`'s design as final — a
newly joined symbol starts at zero position, funded by a future
`open` proposal under the existing floor/eligibility checks; this was
flagged by DS as a judgment call and is no longer open. Also flagged:
`join_symbol_if_ready()` is not yet wired to any API route (exists
and is tested, but unreachable in production) — a follow-up, not a
blocker. Massive Indices Basic confirmed free ($0/mo, EOD data, 5
req/min) — unblocks the VIX vol-regime spec at zero cost pending
Tiago enabling the product on his account and a live access check.
**Decision:** both commits ship as-is; `join_symbol_if_ready` design
confirmed, no rework needed.
**Outcome:** live health confirmed good post-commit (`/health` ok).
**Logged by:** Claude

## 2026-08-17 16:08 PT — N/A — build: multi-asset plumbing + AMC auto-entry + bracket lifecycle

**Trigger:** Claude handoff `DEEPSEEK_MULTI_ASSET_AND_FIXES_TASK.md` (4 build items), done in one pass.
**Discussion:** (1) `/paper/experiments` now returns live `live_cash` from `pe_paper_cash`; dashboard reads it. (2) `open`/`add` are auto-eligible only for the AMC anchor (Option B), other symbols stay manual. (3) `join_symbol_if_ready()` adds a symbol to an already-ACTIVE experiment (eligibility gate + fresh heartbeat, no holdings required). (4) `set_bracket` proposals flow through the approval lifecycle before `upsert_bracket`; dashboard shows active brackets + renders set_bracket proposals. **Flagged gap:** allocation caps (single-contract 15%, single-expiry 25%, total-options 50%, daily-loss 5%, orders/day 3) are declared in the goal but not enforced anywhere — pre-existing, needs Tiago's call. Left `set_bracket` out of `VERY_HIGH_AUTO_ACTIONS` (default).
**Decision:** handed back for review; no deploy/commit/push.
**Outcome:** 484 tests pass, `git diff --check` clean.
**Logged by:** DeepSeek

## 2026-08-17 14:14 PT — AMC — N/A — production incident (502, fixed)

**Trigger:** Tiago reported Railway showing "Deployment failed" with a
Network → Healthcheck failure on deployment `737dea4a` (2026-08-17 13:01
PDT). `/health` and `/paper/health` both returned 502
`"Application failed to respond"` for the intervening ~70+ minutes.
**Evidence roots:** N/A — infra incident, not a trade.
**Discussion:** Deploy logs (pasted by Tiago) showed every gunicorn worker
crashing on boot: `ImportError: cannot import name 'TRACKED_SYMBOLS' from
'paper_execution.portfolio'`. Root cause traced to commit `54dafef`
("Fix: remove close_instruments route accidentally committed in aa1e25f")
— that commit correctly stripped the unreviewed `close_instruments` route
but left one unrelated line behind: `from paper_execution.portfolio import
TRACKED_SYMBOLS` and `activate_if_ready(PAPER_DB_PATH, DB_PATH,
TRACKED_SYMBOLS)`. `TRACKED_SYMBOLS` only exists in local, not-yet-
committed multi-asset expansion work — never pushed — so the import always
failed on the deployed commit. Fix: built a clean git worktree from
`origin/main` (isolated from all other local uncommitted WIP), reverted
those two lines back to the known-good `activate_if_ready(PAPER_DB_PATH,
DB_PATH, "AMC")` literal, verified the import resolves, ran the full suite
(450 passing on that clean base) and `git diff --check` (clean), then
Tiago pushed the single-commit fix (`f27850c`) from his own terminal (push
itself is blocked for Claude by the sandbox's auto-mode classifier — commit
prep only, human executes the actual push). Deliberately did **not** pull
in the local `TRACKED_SYMBOLS` definition to close the gap the other way,
to keep the unreviewed multi-asset expansion isolated, matching the intent
of `54dafef` itself.
**Decision:** hotfix pushed to `main` as `f27850c`.
**Outcome:** confirmed fixed — `/health` returned `{"status":"ok"}` at
14:14:11 PT (3rd poll after push), `/paper/health` returned `status: ok`
with the expected five closed-market blockers (no fresh heartbeats yet —
correct resting state, not an error). Today's TradingView alert reset
(Tiago, earlier this afternoon) should now deliver cleanly against a
working backend once the market opens. Claude covers the market-open watch
tomorrow (2026-08-18) per `docs/DEEPSEEK_TUESDAY_HANDOFF_2026-08-18.md`.
**Logged by:** Claude

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
