# Task packet — Entry Discovery: build (not activate)

**Requested by:** Tiago, 2026-08-17. **For:** DeepSeek. Build authorized
following `reports/ENTRY_DISCOVERY_SPEC.md` (reviewed and accepted in
full). Answers to §11's open items, so there's nothing left to guess:

1. **Surfacing = real `open` proposal** (§4's recommendation) — confirmed.
2. **LONG/CALL only for v1** (§11.2) — confirmed, shorts/shares stay out
   of scope for this build.
3. **DTE 14-primary/30-fallback** (§11.3) — confirmed as specified.
4. **Cap values as proposed** (§11.4) — 3 outstanding per experiment, 1
   per symbol per trading day, rejection-cooldown for the rest of the
   trading day — confirmed as specified.

## What to build

Per the spec, in order:

1. **Server-side port of the `ignition` condition** (spec §2/§3) — a pure
   Python function over a `/state_all`-shaped snapshot, mirroring
   `lifecycleStage()`'s ignition branch in `ui/dna_dashboard.html`
   exactly. Unit-test against the same fixture shapes already used for
   the client-side version; the two must agree on the same inputs.
2. **The `open` evidence-reconstruction extension** (spec §5) —
   `cloud_state.reconstruct_cloud_state` must return a position-less
   snapshot when `position_ref is None` for `action == "open"`:
   `underlying` + `execution` computed as today, `position = {exists:
   False, ...}`, no `contract` block (policy already doesn't require
   `contract_response` for `open`). This must not change behavior for
   any existing action with a real `position_ref` — test that explicitly.
3. **Contract selection** (spec §6) — ATM CALL via
   `massive_options.get_chain(symbol)`, nearest expiration to 14 DTE,
   else 30 DTE. No Greeks, no IV, no invented numbers. Freshness labeled
   `DELAYED` on the candidate's evidence, same honesty as the execution
   root elsewhere.
4. **Discovery scan** (spec §8/§9) — runs on the existing paper tick,
   read-only, before the runner's proposal/fill phases. Dedup by
   `(symbol, stage)`, hard cap 3 outstanding per experiment, 1 per symbol
   per trading day, rejection-cooldown for the rest of the trading day.
5. **Symbol scope**: build against `tracked_symbols()` and
   `asset_eligible()` from the start (already shipped) — AMC-only in
   practice today since it's the only symbol in any active experiment,
   but no AMC-specific hardcoding in the discovery logic itself.

## Hard boundary — read first

A surfaced candidate is an ordinary `PENDING_APPROVAL` `open` proposal.
It must clear the exact same path as a hand-typed `open`: evidence-root
reconstruction, the 30% AMC floor (R1), the eligibility gate, and the
600-second approval window. **If any part of the implementation lets a
discovered candidate skip that path, stop and report — do not ship it.**
This does not touch `VERY_HIGH_AUTO_ACTIONS` or the auto-entry question;
discovery only ever proposes, never executes.

## Boundaries (standard)

- No activation, no changes to which experiment is `ACTIVE`.
- No changes to `paper_execution`'s evidence-root functions beyond the
  scoped position-less-snapshot extension in item 2.
- Full suite + `git diff --check` clean.
- No deploy/commit/push — hand back for review, same verify-then-commit
  pass as every task.
- Log a summary entry to `docs/PAPER_TRADE_DESK_LOG.md` when done, same
  convention as the other in-flight items.

## What to report back

What was built per item, new/updated tests and their names, full suite
result. Also: run the ignition port against AMC's current live
`/state_all` and confirm whether it would surface a candidate right now
(per the spec's §10, it shouldn't — AMC wasn't in ignition as of the
grounded validation) — a live sanity check that the port agrees with the
spec's own read.
