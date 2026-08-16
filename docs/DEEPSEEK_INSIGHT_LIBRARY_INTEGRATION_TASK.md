# Task packet — Wire the DNA position vocabulary/insight library into the live dashboard

**Requested by:** Tiago, 2026-08-15. **For:** DeepSeek.

## Context

`reports/DNA_POSITION_VOCABULARY_RESEARCH.md` (§9, "Integration contract for
Claude/GPT") already specifies exactly how this should wire up — this packet
just authorizes doing it. The rule engine (`campaign_condition` →
`holding_state` → `tf_relationship` → `compose`) is implemented and tested in
`tests/dna_insight_library.py` / `tests/test_dna_insight_library.py`, but
verified today to be **completely unreferenced by any production file** —
`webhook_receiver.py`, `positions.py`, and `ui/dna_dashboard.html` don't
import it. The dashboard's live `holdingGuidance()` function still calls the
older `shareInsight`/`optionInsight` narrative generators instead.

## What to build

**1. Promote the module out of `tests/`.** It's production logic sitting in
the wrong place. Move `tests/dna_insight_library.py` to a real module (e.g.
`dna_insight_library.py` at repo root, matching `positions.py`/
`sec_filings.py`'s pattern), update `tests/test_dna_insight_library.py`'s
import accordingly, confirm those tests still pass unchanged.

**2. Add a read-only, authenticated endpoint** that runs the existing
`compose()` pipeline server-side against live data, e.g.
`GET /positions/<id>/insight` (or per-holding if that fits the existing
`position_ref`/`instrument_ref` pattern better — your call, follow whatever's
most consistent with `/positions/<id>/valuation`'s existing shape). It should:
- pull the position's `instrument`/`holding` fields the same way
  `/positions/<id>/valuation` already does;
- pull `states` the same way `/state_all/<symbol>` already does;
- call `compose(states, holding, instrument)` and return its exact output
  shape from the integration contract (`status_label`, `conclusion`,
  `evidence`, `decision_change`, `prohibited`, `confidence`) — no
  reshaping, no added free text.

**3. Wire the dashboard to it.** `holdingGuidance()` in `ui/dna_dashboard.html`
currently computes synchronously from local `shareInsight`/`optionInsight`.
Switching to a fetched, server-computed insight means restructuring this to
the same async-fetch-plus-cache pattern already used elsewhere in the file
(`loadOhlc`, `loadChain`) — not a synchronous call. Render the new
`status_label`/`conclusion`/`evidence` output in place of (or alongside,
your call on which reads better) the existing bullets.

**Fallback required:** if the new endpoint errors, is slow, or the position
has fields the rule engine marks `confidence: "no-basis"`, fall back to the
existing `shareInsight`/`optionInsight` output rather than showing nothing
or a broken state. Never let this be a silent failure.

## Verification

- Existing `test_dna_insight_library.py` suite still passes after the move.
- New endpoint: at least one test per campaign condition (§3.3, 6 conditions)
  proving the live-data path produces the same output the pure-function
  tests already prove for that input shape.
- Live/local verification: real position(s) via `POST /positions` against
  the local server (same pattern used earlier today — real data, screenshot,
  DELETE cleanup afterward), confirming the dashboard actually renders the
  new insight text, and that the fallback path works if you temporarily
  break the endpoint on purpose.
- Full suite + `git diff --check` clean.

## Boundaries

- Don't touch `paper_execution/`, Pine, TradingView, webhook ingestion
  structure, or the unrelated in-progress partial-close "Manage" feature
  already sitting uncommitted in `positions.py`/`webhook_receiver.py`/
  `ui/dna_dashboard.html` — same rule as every task today: if your changes
  would collide with it, stop and report instead of resolving it yourself.
- This is a real production change (new endpoint + dashboard behavior), so
  no deploy/commit/push required from you — hand back for review same as
  always, but note in your report that this one, unlike today's other
  tasks, does touch files the paper challenge also touches
  (`webhook_receiver.py`) — flag the exact diff clearly so it's easy to
  review in isolation from anything else in that file.

## What to report back

- The exact new endpoint shape (request/response).
- Test results (existing suite + new tests + full repo suite).
- Confirmation of the fallback behavior actually working, not just coded.
- Screenshot/description of the live-rendered insight text on a real
  position, next to what the old `shareInsight`/`optionInsight` would have
  said for the same position, so the wording change is easy to judge.
