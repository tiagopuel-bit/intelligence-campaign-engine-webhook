# DeepSeek handoff — AMC semi-automatic paper execution experiment

## Objective

Build a cloud-only, auditable AMC portfolio experiment that can:

1. monitor the existing beta AMC portfolio (shares and options);
2. publish a compact daily AMC decision report;
3. create time-sensitive paper order proposals from live DNA, position and
   contract evidence;
4. alert the user and wait up to 10 minutes for approval, modification or
   cancellation;
5. if the user does not respond, revalidate the proposal and paper-execute it
   only when every frozen `VERY_HIGH` eligibility gate still passes;
6. record the proposal, user response, simulated execution and later outcomes
   without rewriting history.

This is a multi-month test intended to run through January 2027. The portfolio
goal, starting value, drawdown limit and allocation limits must remain explicit
experiment configuration supplied by the user; do not invent them.

## Program North Star

Once activated, the January 2027 Portfolio Challenge is the primary operating
framework for this project. Data collection, AMC monitoring, Options DNA,
catalyst detection, the Decision Room, daily reporting and future asset
selection should be prioritized by whether they improve the quality,
timeliness, safety or measurability of portfolio decisions.

The Challenge is an evaluation stream, not an endlessly reusable training set.
Preserve two explicit tracks:

1. `CHALLENGE_OPERATIONS` — frozen policy versions make timestamped paper
   decisions and are scored without hindsight edits;
2. `RESEARCH_DEVELOPMENT` — new hypotheses are developed on separately defined
   historical/discovery data and may enter Challenge operations only through a
   versioned promotion checkpoint.

Never refit a rule to a Challenge loss and then rewrite the earlier result as if
the revised rule had been active. Policy updates begin a new evaluation segment
and preserve the preceding segment, proposal ledger and outcomes.

Primary scoreboard:

- Total Portfolio Value and Silver/Gold/Premium/Diamond milestone progress;
- performance versus the frozen do-nothing and AMC buy-and-hold baselines;
- realized/unrealized P&L and drawdown;
- decision attribution: DNA proposal, user approval/override, market movement,
  external cash flow and execution-model effect;
- quality metrics: false positives, cancelled revalidations, approval delay,
  opportunity capture, adverse excursion and risk avoided.

The milestone target never overrides evidence or safety. A system that reaches
a higher tier through uncontrolled concentration or unacceptable drawdown has
not passed the Challenge.

## Goal-establishment gate

P0 cannot pass and the experiment cannot be activated until the user approves a
versioned goal contract containing:

- exact start timestamp and end timestamp in `America/Los_Angeles`;
- immutable starting cash and starting holdings, valued under a declared method;
- primary January 2027 target portfolio value;
- secondary return target, derived from the frozen starting value;
- maximum tolerated portfolio drawdown;
- maximum AMC exposure and maximum exposure per option/expiry;
- whether additional capital deposits or withdrawals are prohibited or tracked
  separately from trading performance;
- allowed action types (hold, add, open, partial reduce, close, roll);
- benchmark portfolio and success criteria;
- minimum observation count required before judging auto-execution;
- safety goals: maximum daily paper loss, orders per day and consecutive failed
  proposals before the global auto switch disables itself.

The primary dollar target must not become an instruction to force trades. Risk
limits and evidence gates always take precedence over target pace. Daily reports
must distinguish:

- portfolio value change caused by market/trading performance;
- external deposits or withdrawals;
- progress versus target;
- progress versus the frozen do-nothing baseline;
- whether current target pace would require risk beyond the approved limits.

Write the approved contract to
`paper_execution/experiment_goal_v1.json`, hash it and prevent silent edits.
Any later goal change creates a new version and preserves the original.

### User-defined January 2027 portfolio milestones

Measure these against **Total Portfolio Value**, not AMC-only value, option
premium, realized P&L or cumulative trade proceeds:

| Tier | Target total portfolio value |
|---|---:|
| Silver | $6,000 |
| Gold | $8,000 |
| Premium | $10,000 |
| Diamond | $15,000 |

The user explicitly confirmed `Diamond` as `$15,000`; it is no longer a pending
assumption. The exact starting total portfolio snapshot remains required before
activation.

Daily reports must show the highest achieved tier, distance to the next tier,
and progress versus the do-nothing baseline. A tier may not change execution
eligibility, loosen risk limits or encourage additional trades merely because
the deadline is approaching.

### Strategic AMC allocation policy

While the current AMC campaign remains objectively intact and neither side has
completed the loss-of-confidence process below, target at least **30% of Total
Portfolio Value** in combined AMC exposure. The numerator includes marked
market value of AMC shares and AMC option positions; the report must also show
option delta-equivalent exposure later if trustworthy Greeks become available,
but must not invent it now.

The 30% level is a strategic target/floor, not permission to force a trade or
ignore execution, concentration or drawdown limits. If the portfolio falls
below it because of market movement, DNA should report the gap and evaluate an
action; it must not automatically buy solely to restore the percentage.

The floor may be suspended only when:

1. the versioned DNA campaign-break definition is objectively satisfied;
2. the AI records a structured `CONFIDENCE_WITHDRAWN` decision with evidence;
3. the user explicitly records agreement; and
4. any reduction still passes the normal proposal/revalidation workflow.

If DNA identifies structural damage but the user has not agreed, switch the
position to `DECISION_REQUIRED` and prohibit unattended exposure-increasing
orders. If the user loses confidence but DNA does not confirm a campaign break,
record the disagreement and require manual approval for changes; do not pretend
there is mutual confirmation.

Capital outside AMC may remain in cash. It may be allocated to other covered
assets only after those assets pass a separately frozen opportunity and
portfolio-risk policy. Cash is a valid allocation and must not be treated as a
failure to pursue the January milestones.

The goal contract must still define a maximum AMC allocation and option-risk
cap; the 30% floor does not replace those upper bounds.

### Provisional goal-template values for P0

Create `paper_execution/experiment_goal_v1.json` as a filled-in **provisional**
template using the values below. Preserve a `confirmation_status` per field and
do not mark the contract frozen until the user approves the generated JSON.

| Field | Provisional value |
|---|---|
| start | activation timestamp after P0 approval |
| end | January 31, 2027 market close, America/Los_Angeles |
| starting portfolio | immutable live holdings plus user-declared cash at activation |
| deposits/withdrawals | allowed, recorded separately and excluded from trading performance |
| AMC target floor | 30% of Total Portfolio Value |
| AMC maximum for new allocation | 70% |
| total options maximum | 50% of Total Portfolio Value |
| single expiration maximum | 25% of Total Portfolio Value |
| single contract maximum | 15% of Total Portfolio Value |
| maximum portfolio drawdown | 25% |
| maximum daily paper loss | 5% |
| maximum paper auto-executions | 3 per trading day |
| automatic safety shutdown | 3 consecutive failed/cancelled revalidations |
| minimum evaluation sample | 30 proposals, including at least 10 paper auto-executions |
| benchmarks | frozen starting portfolio; AMC share buy-and-hold; actual user-managed path; DNA paper-managed path |

If the starting AMC or option exposure exceeds a provisional cap, grandfather
the immutable starting holdings. Do not create a forced opening trade or forced
liquidation merely to satisfy a newly introduced allocation boundary. Apply the
cap to new exposure and report a controlled path toward compliance.

The P0 report must list every provisional field awaiting confirmation, show the
calculation method for each percentage and request the user's approval as one
explicit checkpoint. It must not silently promote defaults into an active
policy.

## Non-negotiable boundary

This stage is `PAPER_ONLY`.

- No broker connection, order transmission or real-money execution.
- No live or paper broker credentials.
- No endpoint may be capable of routing to a broker.
- Do not introduce an abstract adapter whose default could accidentally become
  live. A later broker handoff must be separately authorized and reviewed.
- Do not modify Pine, TradingView alerts, DNA signal definitions or webhook
  ingestion.
- Do not call an observed rule validated merely because it produces a high
  score.

The current Options DNA entry result is
`HISTORICAL_RESEARCH_FINDING_NEEDS_EXTERNAL_REPLICATION`: one CALL/14
`CONFIRMATION_FAILURE` family, Discovery rank 12, four full-sample Holdout
triggers and three active-print Holdout triggers. It is not shadow-eligible and
must not power `VERY_HIGH`, production wording or an order proposal.

Position-management calibration remains
`BLOCKED_INSUFFICIENT_REPLAY_COVERAGE`. Any initial paper decision policy is an
explicitly pre-registered `EXPERIMENTAL_HEURISTIC`, not a fitted or validated
Options DNA rule.

## Existing system to preserve

Repository: `intelligence-campaign-engine-webhook`

Relevant existing components include:

- `webhook_receiver.py` — authenticated Flask API and SQLite initialization;
- `decision_engine.py` — current advisory navigation;
- `ui/dna_dashboard.html` — live Asset Page and Position Manager;
- `GET /state_all/<symbol>` — live DNA timeframe state;
- `GET /positions` and position valuation/CRUD endpoints;
- `GET /ohlc/<symbol>/<timeframe>`;
- `GET /options/ohlc/<contract_ticker>/<timeframe>`;
- `GET /options/chain/<symbol>`;
- SEC filing and media work currently in the dirty worktree;
- Options DNA research artifacts under `reports/options_dna_expansion/`.

The working tree contains parallel-session and research changes. Preserve them.
Before editing, record `git status --short`, inspect overlapping diffs and avoid
formatting or rewriting unrelated code.

All protected requests use `STATE_API_TOKEN`. Never print, persist in artifacts,
commit or screenshot its value.

## Operating modes

Every experiment and proposal must carry one of these explicit modes:

- `ADVISORY_ONLY`
- `APPROVAL_REQUIRED`
- `AUTO_IF_VERY_HIGH_PAPER`
- `PROTECTION_ONLY_PAPER`

The only auto mode authorized here is `AUTO_IF_VERY_HIGH_PAPER`.

Proposal lifecycle:

```text
DRAFT -> PENDING_APPROVAL -> APPROVED | REJECTED | CANCELLED | EXPIRED
PENDING_APPROVAL -> REVALIDATING -> PAPER_EXECUTED | CANCELLED_REVALIDATION
APPROVED -> REVALIDATING -> PAPER_EXECUTED | CANCELLED_REVALIDATION
PAPER_EXECUTED -> PARTIALLY_FILLED | FILLED | UNFILLED | EXPIRED_UNFILLED
```

Every transition is append-only. A current-state column may be maintained for
efficient reads, but the event ledger is authoritative.

## Ten-minute rule

When a proposal is created:

1. alert immediately;
2. show `Approve`, `Modify`, `Reject` and `Cancel auto-execution` controls;
3. set a default maximum approval window of 10 minutes;
4. user approval may trigger immediate revalidation;
5. no response does **not** approve the stale proposal;
6. at the deadline, perform a new atomic revalidation using current causal data;
7. submit only to the paper fill simulator if every gate still passes;
8. otherwise record the exact cancellation reason.

The user must be able to disable auto-execution globally and per position. A
disabled switch must win over any pending timer.

## Live-price freshness gate

The Massive free-plan aggregate feed is not a real-time execution feed. The
current TradingView DNA webhook carries the underlying close, but v12.6.21
emits only on a DNA/state change at a confirmed bar close; a configured 1-minute
alert therefore does not guarantee one update every minute.

P0 must report this distinction explicitly. No proposal may be described as
real-time or `VERY_HIGH` merely because a 1-minute TradingView alert exists.

Before paper activation, verify a separate underlying heartbeat behavior that:

- posts AMC symbol, timeframe, bar close, bar timestamp, session and a distinct
  heartbeat/source marker on every confirmed 1-minute bar;
- preserves the existing event/state-change records and does not manufacture a
  DNA event on heartbeat-only bars;
- is accepted idempotently by Railway and exposes price age/freshness;
- has explicit RTH/PRE/POST coverage and stale-session handling;
- achieves a documented expected latency (approximately one confirmed 1-minute
  bar, not tick-level execution data);
- does not consume additional alert capacity unnecessarily if it can safely use
  the existing `Any alert() function call` alert.

TradingView alerts capture the script version at alert creation. If Pine is
changed to add heartbeat emission, document that the AMC 1-minute alert must be
deleted/recreated and verify the new payload end to end. No Pine change is
authorized inside P0; P0 may only specify the smallest separate implementation
task and acceptance test.

Underlying heartbeat data does not solve option-premium freshness. A premium-
based proposal, premium-spike detector or price-specific option paper order is
ineligible unless the selected contract has a fresh causal quote/bar source.
The current free Massive option aggregate close must be labelled delayed. Until
a verified option feed exists, resolve these cases to
`BLOCKED_STALE_OPTION_QUOTE` or `UNSCORABLE_EXECUTION_DATA`; do not infer a live
premium from AMC's underlying move.

P0 must compare bounded options for contract freshness without integrating one:

1. a future broker paper/live quote API;
2. a provider plan with real-time option bid/ask;
3. a limited TradingView contract heartbeat for already-held contracts, if the
   user's TradingView data entitlement supports those symbols.

No real option order path may be enabled until bid/ask, quote timestamp, spread
and revalidation behavior are verified.

### Bounded option-contract watchlist

Do not stream or alert the full option chain. Maintain a small, rotating list of
contracts whose live behavior could change an actual portfolio decision:

1. `HELD` — every currently open AMC option contract;
2. `ENTRY_CANDIDATE` — contracts attached to an active, time-bounded staged
   entry thesis;
3. `ROLL_CANDIDATE` — at most the small set of replacement contracts currently
   being compared for an open position;
4. `EXIT_WATCH` — a held contract temporarily elevated because a manage,
   protect or close condition is near.

Suggested provisional capacity is all held contracts plus no more than three
entry candidates and two roll candidates at once. P0 must inventory the real
TradingView alert budget and provider limits before freezing a number.

Every watched contract requires:

- canonical option ticker, underlying, type, strike and expiration;
- watch reason, linked position/proposal and priority;
- created/last-needed/expires timestamps;
- latest causal OHLCV/bar timestamp and source;
- data age and session;
- active/paused/stale/error status;
- automatic retirement when the position closes, proposal expires, contract
  becomes irrelevant or a higher-priority candidate replaces it.

A minimal TradingView option quote relay may be evaluated as a separate task:
one lightweight Pine v6 alert per watched contract, using the option chart's
confirmed 1-minute OHLCV and a distinct payload type. Do not run the full DNA
campaign engine on the option premium or interpret option-chart DNA as the
underlying campaign. Verify the user's TradingView option-data entitlement and
actual alert behavior first.

This relay would support near-live premium movement, volume and contract-versus-
underlying response for paper research. Pine OHLCV is not bid/ask. It therefore
does not satisfy the future real-order execution gate by itself; a broker or
real-time option quote source is still required for executable spread-aware
limits.

The dashboard/daily report must distinguish:

- `LIVE_CONTRACT_BAR`;
- `DELAYED_PROVIDER_BAR`;
- `STALE_CONTRACT_DATA`;
- `NO_LIVE_CONTRACT_SOURCE`.

Never silently fall back from a live contract bar to a delayed daily close in a
time-sensitive proposal.

## `VERY_HIGH` evidence contract

Do not equate a numeric confidence field with execution eligibility. A proposal
may be `VERY_HIGH` only when all four independent roots are present:

1. **Underlying DNA:** named timeframe agreement, event recency and no
   disqualifying FAIL/pressure conflict.
2. **Contract response:** real active prints and causal premium behavior; no
   unchanged-print inference and no missing contract bar presented as evidence.
3. **Execution quality:** fresh input, deterministic price reference, acceptable
   spread/liquidity evidence when available and no stale/ambiguous quote.
4. **Portfolio risk:** position exists for reductions; exposure, size, daily
   limits, duplicate-order and conflict checks pass.

Catalyst/SEC risk is an independent veto or policy modifier, never silently
folded into a score.

Every proposal must store:

- the named evidence roots and raw causal fields;
- missing evidence;
- contradictions and vetoes;
- policy version and immutable hash;
- proposal type and why it is time-sensitive;
- exact condition that would cancel or change the proposal.

Pre-register separate paper policies for entries, adds, partial reductions,
full closes and rolls. Do not let evidence from a risk-reducing action validate
an entry policy. Rolls are two-leg decisions and cannot be simulated as one
price without both legs.

## Checkpoint P0 — audit and freeze the experiment contract

Do not implement timers, APIs or UI yet.

1. Inventory the exact current position, valuation, DNA, option OHLC, alert,
   SEC and news fields available without adding fake data.
2. Identify which fields are live, cached, reconstructed, delayed or absent.
3. Define the versioned `EXPERIMENTAL_HEURISTIC_V1` policy in machine-readable
   form. All thresholds must be causal and selected without inspecting the
   future outcomes of this experiment.
4. Define the experiment configuration:
   - symbol (`AMC` initially);
   - start/end dates;
   - immutable starting portfolio snapshot;
   - user-supplied target value;
   - maximum drawdown;
   - maximum order/position allocation;
   - allowed action types;
   - default 10-minute approval window;
   - report schedule;
   - global and per-position auto modes.
5. Define schema and migrations for, at minimum:
   - experiments;
   - immutable starting holdings;
   - order proposals;
   - proposal evidence snapshots;
   - proposal lifecycle events;
   - paper orders and fills;
   - user decisions/overrides;
   - outcome snapshots;
   - daily portfolio reports.
6. Define idempotency, concurrency, restart and Railway-redeploy behavior.
7. Define exact fill/censoring rules. If bid/ask is unavailable, do not invent a
   midpoint. Use a conservative, declared bar-based paper model or report
   `UNSCORABLE_EXECUTION_DATA`.
8. Define alert delivery as a boundary only; reuse an existing verified channel
   if one exists. Do not add an unapproved external messaging service.

Required P0 outputs:

- `docs/AMC_PAPER_EXECUTION_PROTOCOL_V1.md`
- `paper_execution/policy_v1.json`
- `paper_execution/schema_v1.sql`
- `reports/amc_paper_execution/P0_DATA_AND_SAFETY_AUDIT.md`
- deterministic tests proving policy parsing, forbidden live mode, append-only
  transitions and no future-outcome access during proposal generation.

Stop and report P0 for review before implementation.

## Checkpoint P1 — deterministic engine and persistence

Only after P0 approval:

- implement idempotent schema initialization;
- implement pure proposal eligibility and revalidation functions;
- implement append-only lifecycle transitions with optimistic/transactional
  concurrency protection;
- implement global/per-position kill switches;
- implement deterministic paper limit-order simulation;
- implement restart-safe due-proposal processing without sleeping inside the
  web process;
- add unit tests for duplicate triggers, double approval, cancel-at-deadline,
  stale data, changed positions, conflicting orders, SEC veto, missing option
  bars, unchanged prints, partial fills and Railway restart.

Stop after P1. No routes, scheduler, dashboard or deploy.

## Checkpoint P2 — authenticated API and cloud runner

Only after P1 approval:

- add authenticated read/write endpoints for experiment state, proposals,
  evidence, approval, modification, rejection, cancellation and reports;
- use compare-and-set/idempotency keys on every mutation;
- add a one-shot runner suitable for a Railway scheduled service;
- runner revalidates due proposals and never executes an expired/stale order;
- `/health` must expose only aggregate paper-runner readiness, not secrets;
- document the Railway command but do not create/change services or deploy.

Stop after P2 and provide API examples using synthetic data only.

## Checkpoint P2A — independent acceptance correction (required before P3)

P2 produced a useful isolated Blueprint and one-shot runner, but independent
review found that the checkpoint is **not yet accepted**. Preserve the frozen
policy/goal provenance and correct the following issues before touching the
Asset Page.

### 1. Make user approval executable without weakening safety

The current approval route transitions a proposal from `PENDING_APPROVAL` to
`APPROVED`, while the runner only selects expired `PENDING_APPROVAL` auto-mode
rows. An approved proposal therefore never reaches revalidation or a paper
fill.

Implement two explicit runner paths:

- **user-approved path:** claim an `APPROVED` proposal immediately, before its
  approval window expires, then rebuild current authoritative evidence,
  enforce kill switches and action compatibility, and revalidate;
- **automatic path:** claim only an eligible
  `AUTO_IF_VERY_HIGH_PAPER` + `very_high=1` proposal after its 10-minute
  approval deadline, then perform the same fresh reconstruction and
  revalidation.

Approval must never bypass freshness, position existence, direction/side,
scenario trigger, catalyst veto, duplicate/conflict, daily-loss or exposure
checks. Reject approval after expiry. A non-`VERY_HIGH` proposal may remain an
observation, but it must not become executable merely because the client calls
`approve`; if a lower-confidence user-approved policy is desired, define and
freeze it separately rather than silently treating missing roots as optional.

Persist every `APPROVE`, `MODIFY`, `REJECT`, `CANCEL_AUTO`, `CANCEL_GLOBAL` and
`CANCEL_POSITION` decision in `pe_user_decisions` as well as the lifecycle
event ledger.

### 2. Execute a real paper fill, not a status-only transition

The current runner changes a valid proposal directly to `PAPER_EXECUTED` but
does not call the fill simulator and writes no `pe_paper_orders` or
`pe_paper_fills` rows. Correct this fail-open semantic.

For a valid revalidation, reconstruct server-side order legs from the selected
authoritative position/action state, call `simulate_order()`, and atomically:

1. append one `pe_paper_orders` row per leg;
2. append the corresponding `pe_paper_fills` rows only for simulated fills;
3. record the declared price source, bar timestamp and bar-close beta model;
4. transition to the exact outcome (`FILLED`, `PARTIALLY_FILLED`, `UNFILLED`,
   `EXPIRED_UNFILLED` or `UNSCORABLE_EXECUTION_DATA`);
5. update the paper portfolio ledger/cash/holding state without mutating the
   user's live/manual position records.

Do not label a proposal `PAPER_EXECUTED` unless an order record exists. Rolls
remain two-leg and fail closed unless both legs have fresh causal prices.

### 3. Wire an actual authoritative cloud state provider

The documented Railway command currently omits `--state`; the script then
installs a provider that always returns `None`, so every due proposal cancels
as `NO_AUTHORITATIVE_STATE`. A JSON file provider is acceptable only for tests.

Add a read-only cloud provider that reconstructs state from the canonical
Railway data sources:

- the latest verified AMC TradingView heartbeat / DNA event state;
- the selected held or watched option contract's verified live relay state;
- the current paper experiment portfolio and selected position;
- the SEC catalyst-veto state.

It must expose provenance (`bar_time`, explicit allowlisted `source`, ticker,
contract, price reference and received time), reject delayed Massive bars as a
live substitute, and return `None` when any action-required dependency is not
authoritative. Keep the JSON provider under an explicit test-only flag. Until
the real provider exists, report the runner as
`BLOCKED_NO_AUTHORITATIVE_CLOUD_PROVIDER` and do not present the Railway
command as activation-ready.

Extend aggregate `/paper/health` with the non-sensitive UI contract:
`active_experiment_id`, `authoritative_provider_ready`, `runner_ready` and a
short `blockers[]` code list. Do not include balances, holdings, evidence,
credentials or tokens. The Asset Page uses
`authoritative_provider_ready === true` as its fail-closed control gate.

The paper database may remain separate from the canonical alert/position
database, but the provider must be given both explicit paths or an equivalent
read-only API. Do not assume `/data/paper.db` contains webhook state.

### 4. Preserve the complete causal evidence snapshot

The proposal API currently stores empty `raw_fields` and synthesized root
presence records. Persist the exact server-reconstructed causal fields used by
the evaluator, including timestamps, sources, missing fields, contradictions,
vetoes and the effective policy plus correction-chain hashes. Do not persist
credentials or future outcomes.

### 5. Make modification and API validation transactional

Modification currently creates/commits the child proposal before cancelling
the parent. Make the supersession one SQLite transaction: validate the parent
is still `PENDING_APPROVAL`, create exactly one versioned child, append the user
decision and lifecycle events, then cancel the parent. Any failure rolls back
the entire operation. Prove concurrent/retried modification cannot create two
children or cancel a parent without a valid replacement.

Use strict request allowlists rather than only rejecting known server-owned
fields. Validate that the experiment exists, is active, matches the symbol,
allows the action and is inside its chronology. Keep all reads authenticated
except aggregate `/paper/health`.

### 6. Required P2A tests and report

Add deterministic tests for at least:

- approved proposal -> immediate claim -> fresh revalidation -> persisted
  order/fill -> terminal lifecycle;
- expired approval rejected;
- non-eligible approval cannot bypass a missing evidence root;
- auto proposal waits until deadline and only one runner wins;
- global/per-position kill switch wins for both approved and auto paths;
- missing/delayed/unknown/future underlying or contract data produces no order;
- the production runner uses the DB/API-backed provider, not the JSON fixture;
- `UNSCORABLE_EXECUTION_DATA` writes an auditable order outcome but no fake
  fill;
- two-leg roll atomicity;
- modification rollback, retry and concurrent-child uniqueness;
- evidence snapshot round-trip matches the exact evaluator input;
- API unknown-field, experiment/action/symbol and expiry validation;
- migration from a disposable P1/P2 database adds required columns/tables
  without losing rows.

Run the full suite and `git diff --check`. Report exact commands/counts, schema
and provenance hashes, lifecycle examples and the remaining live-data blocker.
Stop before P3, commit, push, Blueprint mounting, Railway service changes or
deployment.

### P2A independent re-review addendum — must pass before acceptance

The first P2A implementation passed its focused tests but remains unaccepted
until these integration findings are corrected:

1. **Target the exact holding/contract.** A symbol plus action is ambiguous
   because AMC has shares and multiple option contracts. Add a server-validated
   `position_ref`/`instrument_ref` intent field to the proposal and persist it.
   For reductions, closes and rolls it must resolve to one exact open paper
   holding (and exact legs for a roll). Never select the first AMC instrument
   with `LIMIT 1`. The provider, duplicate/conflict checks, per-position kill
   switch, reconstructed evidence and order legs must all use this same
   reference. Add a regression with shares + option A + option B proving a
   proposal for option B cannot read or fill option A.

2. **Make lifecycle + orders + fills + paper portfolio one transaction.** The
   current runner commits `PAPER_EXECUTED` before inserting orders/fills. A
   storage failure can therefore leave an executed proposal with no order.
   Replace this with one atomic helper that appends the order outcome, fills,
   lifecycle event and paper cash/holding update together. Roll legs must commit
   or roll back together. Inject a storage failure in a test and prove no
   partial lifecycle/order/portfolio state remains.

3. **Preserve `UNSCORABLE_EXECUTION_DATA` exactly.** Do not map it to generic
   `UNFILLED`. Add the explicit lifecycle terminal/status and show that an
   auditable order outcome exists with zero fake fills. An ordinary unfilled
   order and an unscorable order are analytically different.

4. **Use actual execution provenance.** Do not hardcode
   `price_source="live_webhook"` in the runner. Persist the source, ticker,
   contract, bar timestamp, received timestamp and reference type from the
   exact reconstructed execution/contract state. Reject a mismatch between the
   evidence contract and order-leg contract.

5. **The cloud provider must not treat all webhook alerts as a heartbeat.** The
   existing Pine alert stream is event/state-change driven; a latest alert can
   remain old even while 1-minute bars continue. Require a distinct verified
   heartbeat/relay record and validate receive time as well as bar time. Until
   the AMC 1-minute heartbeat and selected-option relays actually populate that
   record, health must report provider readiness false and the runner must stay
   blocked.

6. **Bound SEC vetoes to active/new filing state.** Counting any historical
   HIGH dilution filing forever creates a permanent veto. Use the filing watch
   state, first-seen/acceptance time and the frozen active window/acknowledgment
   policy. Store which accession caused the veto. Historical seed records alone
   cannot indefinitely veto all actions.

7. **Complete the health/UI contract.** `/paper/health` currently lacks
   `active_experiment_id`, `authoritative_provider_ready`, `runner_ready` and
   `blockers[]`. Add them exactly as specified above. Provider readiness must
   be false while the option relay or true heartbeat is absent; a DB-backed
   adapter existing on disk is not itself readiness.

8. **Prove paper cash/holdings change.** The schema has paper cash/position
   tables, but the first P2A runner does not update them. Test share and option
   partial reductions/closures (correct signs and 100x option multiplier), and
   prove the user's production/manual `positions` tables remain untouched.

9. **Exercise real two-leg rolls.** The current `reconstruct_legs()` returns
   one leg. Add a two-leg roll fixture with an exact close leg and open leg,
   separate fresh prices, signed debit/credit result and atomic failure when
   either price is absent.

Regenerate the P2A report after this addendum. Do not claim P2A accepted merely
because the earlier focused suite passes.

## Checkpoint P3 — Asset Page and daily AMC report

Only after **P2A acceptance**:

Add to the existing dashboard without replacing the approved Asset Page:

- experiment progress toward the user-supplied January 2027 target;
- current value, realized/unrealized P&L and drawdown from portfolio high;
- daily AMC campaign summary;
- position-level action queue;
- pending proposal countdown and evidence;
- `Approve`, `Modify`, `Reject`, `Cancel auto` controls;
- unmistakable `PAPER` badges on every order and fill;
- history comparing DNA proposals, user decisions and simulated outcomes.

Daily report sections:

1. portfolio progress;
2. AMC campaign and volume/decision window;
3. position decisions;
4. option contract efficiency/activity;
5. SEC/catalyst watch;
6. pending/expired/executed paper actions;
7. performance versus frozen baselines.

Baselines must include starting-portfolio buy-and-hold/do-nothing and the actual
user-managed path. No hindsight edits.

Stop after local deterministic and browser verification. No deployment.

## Checkpoint P4 — paper activation (separate authorization required)

Do not activate schedules or deploy automatically. Report:

- complete test command/count;
- database migration result against a disposable copy;
- lifecycle and race-condition tests;
- browser evidence;
- exact Railway configuration required;
- rollback plan;
- all changed files;
- confirmation that no live execution path exists.

Wait for explicit user approval before commit, push, Railway changes or
deployment.

## Future expansion, not authorized now

After AMC runs reliably, the Portfolio Campaign Radar may nominate two more
assets for potential positions. Asset selection, opening policies and portfolio
correlation limits require a separate pre-registered study. Do not add assets
to this experiment opportunistically after seeing outcomes.

A future real broker adapter requires a new security and execution review,
broker selection, credential boundary, paper-broker validation and explicit
user authorization. Nothing in this handoff authorizes it.

## Required report format at every checkpoint

1. status and exact authorization boundary;
2. commands and test counts;
3. available/missing evidence fields;
4. policy/schema hashes;
5. proposal and fill semantics;
6. safety/race/restart verification;
7. blockers and honest unscorable cases;
8. files created/modified;
9. proof production/Pine/webhook ingestion/broker execution stayed untouched;
10. explicit stop before the next checkpoint.
