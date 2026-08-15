# Task packet — Portfolio Challenge Trade Desk Log

**Requested by:** Tiago, 2026-08-15. **For:** DeepSeek. **Priority:** additive,
non-blocking — do this alongside or after the Options DNA replication run, in
whichever order is convenient. Does not touch anything that run is working on.

## Why

Three agents work this project (Claude, GPT, DeepSeek) plus Tiago, none of
whom share chat history. The Portfolio Challenge (`DEEPSEEK_AMC_PAPER_AUTO_EXECUTION_HANDOFF.md`)
already has an authoritative *what-happened* ledger in the DB
(`pe_experiments`, `pe_order_proposals`, lifecycle events, fills) — that part
is solid and append-only by design. What's missing is the *why*: the DNA
read, the discussion, the reasoning behind a decision. That currently only
exists in whichever chat it happened in, which means any agent picking up
cold has no way to reconstruct "why did proposal #14 get rejected" without
Tiago manually re-explaining it.

The fix is a single git-tracked markdown file every agent can read directly
from the repo (all three already have access) — no new service, no new
storage, just a convention plus one small script to keep it honest.

## What to build

### 1. The log file

`webhook/docs/PAPER_TRADE_DESK_LOG.md` — append-only, reverse-chronological
is fine (newest entries on top) or forward-chronological, your call, but
pick one and say which in the file's own header so nobody appends
inconsistently.

Each entry is one decision point. Fixed format:

```markdown
## 2026-08-18 09:47 PT — AMC — proposal #14 (ADD, position_ref=5, instrument_ref=7)

**Trigger:** 3H flipped EXPANSION (health 91, conf 84) after Reload on 4H.
**Evidence roots:** underlying DNA ✅ · contract response ✅ · execution
quality ✅ · portfolio risk ✅ → very_high=true
**Discussion:** [1-3 sentences of the actual reasoning, or "none — auto
path, no discussion" if it went straight through the 10-minute window]
**Decision:** APPROVED by Tiago (or: auto-executed at deadline, or: REJECTED
— reason)
**Outcome:** [filled at $X / cancelled — reason / still open, revisit after Y]
**Logged by:** [agent name]
```

Minimum required fields: date/time, symbol, proposal_id (or "N/A — pre-proposal
discussion" for things like the PYPL watch note that never became a proposal),
decision, and who's logging it. The rest is best-effort — don't block an
entry on having every field if the info genuinely isn't available yet
(e.g. outcome is unknown until later; append a follow-up entry or edit that
one field in place, your call, just don't fabricate an outcome).

### 2. A read-only export helper (optional, only if it saves real effort)

If it's low-effort, a small script (e.g. `scripts/export_trade_desk_entry.py`,
**outside** `paper_execution/`) that takes a `proposal_id` and prints a
pre-filled entry skeleton (evidence roots, decision, timestamps) pulled from
`pe_order_proposals` / `pe_order_lifecycle_events` / `pe_paper_fills`, so
whoever's logging isn't manually retyping data that's already in the DB. This
is a convenience tool only — it must not write to the DB, must not import or
call anything in `paper_execution/`'s write paths, and must not run as part
of any deploy or scheduled process. Skip this if it adds meaningful scope;
the log file itself is the actual deliverable.

## Boundaries — same as the current standing directive

- Do **not** modify TradingView, Pine, Railway, webhook ingestion, the
  dashboard, `paper_execution/`, or Claude's activation documentation.
- This task only **adds** two new files (the log, optionally the export
  script). No existing file should change.
- No commit/push required from you specifically — hand the new file(s) back
  and Tiago or Claude will commit, unless he tells you directly to push.
- Nothing here is time-sensitive or blocks the Options DNA replication work.

## What to report back

- Confirmation the log file exists with the header convention stated.
- One seeded example entry for today's actual alert-activation work (or
  leave it empty with just the header/format if you'd rather Claude seed the
  first real entry — either is fine, just say which).
- If you built the export helper: the exact command, one example run against
  a real or synthetic `proposal_id`, and confirmation it performs no writes.
