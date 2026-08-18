# Add a Freeze/Hold control to the proposal lifecycle

**For:** DeepSeek. Build this before or alongside Entry Discovery
(`docs/DEEPSEEK_ENTRY_DISCOVERY_BUILD_TASK.md`) — it's the control Tiago
needs the moment discovery starts surfacing real `open` candidates on AMC
that are auto-entry-eligible.

## The gap (confirmed by Claude tonight)

Today a `PENDING_APPROVAL` proposal has exactly three live outcomes:
`approve`, `reject`, or `cancel` (kills it entirely) — and if none of
those happen before `expires_at`, the runner's `due_proposals()` claims it
and, for anything in `VERY_HIGH_AUTO_ACTIONS` (currently AMC
`open`/`add`/`partial_reduce`/`close`), it auto-executes if `VERY_HIGH`
still revalidates. `modify` resets the clock to a fresh 10 minutes but
doesn't stop it. **There is no way to pause the countdown without
rejecting or cancelling the proposal outright.** Tiago wants: "if I don't
show up, green light to execute" to stay the default, but with an
explicit option to say "wait, let me actually look at this" that stops
the clock without discarding the proposal.

## Design

New status: `ON_HOLD`, inserted into the lifecycle between
`PENDING_APPROVAL` and its terminal states:

```
PENDING_APPROVAL -> ON_HOLD -> APPROVED | REJECTED | PENDING_APPROVAL (resume)
```

- `POST /paper/proposals/<id>/hold` — requires auth, same pattern as
  `cancel`/`approve`/`reject`. Valid only from `PENDING_APPROVAL`. Sets
  `expires_at = NULL` and status `ON_HOLD`. Record the transition in the
  append-only proposal-event ledger same as every other transition (check
  `transition()` in `store.py` — likely just needs `ON_HOLD` added to
  whatever enum/allowlist of valid statuses it enforces).
- **While `ON_HOLD`, `due_proposals()` must never claim it.** Check the
  exact query in `store.py`'s `due_proposals()` — it almost certainly
  filters on `expires_at <= now AND status='PENDING_APPROVAL'` already,
  so excluding `ON_HOLD` may already be implicit via the status filter,
  but verify this explicitly with a test, don't assume the NULL
  `expires_at` alone protects it.
- `POST /paper/proposals/<id>/resume` — requires auth. Valid only from
  `ON_HOLD`. Re-arms a fresh `expires_at` (now + 600s, same
  `APPROVAL_WINDOW_SECONDS` constant everywhere else) and returns to
  `PENDING_APPROVAL`. The countdown restarts clean — holding doesn't bank
  extra time, it just pauses.
- `approve`/`reject` must also work directly from `ON_HOLD` (Tiago
  decides while paused, without needing to resume first) — a held
  proposal isn't locked out of normal decisions, only exempt from the
  timeout.
- `cancel` still works from `ON_HOLD` too (Tiago changes his mind
  entirely, not just wants to pause).

## Dashboard

Add a "Freeze" button next to Approve/Reject/Modify on any proposal card
still `PENDING_APPROVAL`. While `ON_HOLD`, show "Resume" instead, and
visually distinguish it from a normal countdown (no ticking timer, since
there isn't one).

## Tests

- Hold a `PENDING_APPROVAL` proposal → status `ON_HOLD`, `expires_at`
  NULL.
- `run_once()`/`due_proposals()` never claims an `ON_HOLD` proposal even
  when `now` is far past when it *would* have expired had it stayed
  `PENDING_APPROVAL` — this is the test that actually proves the freeze
  works, not just the status label.
- Resume → status back to `PENDING_APPROVAL`, fresh `expires_at` ~600s
  out.
- Approve/reject/cancel directly from `ON_HOLD` all work.
- Hold from a non-`PENDING_APPROVAL` status (e.g. already `APPROVED`)
  rejected with a clear error, not a silent no-op.

## Boundary

This does not change what's auto-eligible (`VERY_HIGH_AUTO_ACTIONS` stays
exactly as scoped — AMC-only) or weaken any evidence/floor/eligibility
gate. It only adds a pause between "proposal exists" and "clock runs out."
Full suite + `git diff --check` clean, no deploy/commit/push — hand back
for review. Log a summary to `docs/PAPER_TRADE_DESK_LOG.md` when done.
