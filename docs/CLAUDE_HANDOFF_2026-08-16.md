# Handoff — DeepSeek → Claude, 2026-08-16

**From:** DeepSeek. **For:** Claude. Summary of what landed in the webhook repo
this session, what's still pending, and what's waiting on Tiago. Everything is
**uncommitted** — handed back for review, no deploy/commit/push.

## 1. MARA backfill + reliability mask (earlier task packet)

- Ran the 6-month-bounded backfill for `MARA` (live Railway, over SSH): 4,182
  rows across 3m–4H, 0 on 1D/1W (6 months = 125 daily bars < the replay's
  ~200-bar ema warm-up, so Daily/Weekly emit nothing).
- Computed MARA's reliability mask and appended 7 rows to
  `tables/dna_campaign_lifecycle_reliability.csv`, added `"MARA": {…,"4H":0}` to
  the dashboard's `LIFECYCLE_RELIABILITY`, and updated
  `tests/test_campaign_lifecycle_ui.py` to 8 assets.
- **Finding to note:** MARA `4H` is unreliable — not noisy, but because its
  anchor (Daily) has 0 classified bars at 6 months, so 4H can't be validated.
  Owner tier falls back to `3H` (reliable, 0.63).

## 2. FINRA short-sale data (borrow/short thread)

- New `finra_short.py` — daily short-sale-volume client (free CDN, browser
  User-Agent, **no credential**): `https://cdn.finra.org/equity/regsho/daily/CNMSshvol{YYYYMMDD}.txt`
  (pipe-delimited `Date|Symbol|ShortVolume|ShortExemptVolume|TotalVolume|Market`).
- New `GET /short/<symbol>` (STATE_API_TOKEN-gated), returning rolling
  short-volume ratio + closed-vocab `short_activity`
  (`LOW/NORMAL/ELEVATED/HIGH/NO_DATA`), freshness `DELAYED`.
- Wired into the DNA insight library: `dna_insight_library.compose(..., short_activity=...)`
  now de-risks **short positions** on `ELEVATED`/`HIGH` (squeeze risk):
  `hold/wait → protect` (shares) or `reduce` (options), `protect → reduce`;
  never overrides reduce/close/monitor, never touches longs.
- **Deferred (needs Tiago):** bi-monthly consolidated short interest +
  days-to-cover requires a FINRA *Public credential* (free account signup —
  the unauthenticated Query API only returns a 2020 sample). Tiago said he'll
  open the account. The seam is documented in `finra_short.py`.
- **Not built:** interest/CTB carry cost — FINRA publishes no rate, so it stays
  a declared model parameter (same discipline as the fill model).

## 3. SL/TP protective brackets (paper execution)

- New `paper_execution/brackets.py` + `pe_position_brackets` table (partial
  unique index: one ACTIVE bracket per position, history preserved).
- `store.py`: `upsert_bracket` / `cancel_bracket` / `list_active_brackets` /
  `apply_bracket_trigger` (closes the paper position + adjusts cash).
- `api.py`: `POST /paper/brackets`, `GET /paper/brackets`,
  `DELETE /paper/brackets/<id>` — server derives direction/symbol/instrument
  from the paper position, never trusts the client.
- `runner.py`: `run_once` now has a third phase evaluating brackets each tick,
  gated by kill switch + `cloud_state.latest_close()` (fresh heartbeat).
- **Honest fill model:** fires on a **bar-close crossing**, fills at that close
  — no intrabar, no bid/ask, no price invented, no fire without a fresh price.
  Pre-registered standing order: **no 600-second approval window**.

## 4. Indicator/data-source research (separate tab)

- Prompt written to `docs/DEEPSEEK_INDICATOR_DATA_SOURCE_RESEARCH_TASK.md`;
  Tiago ran it in another tab. Output landed as
  `reports/ADDITIONAL_DATA_SOURCE_RESEARCH_2026-08.md` (+ `.pdf`). I have not
  read it — worth reviewing alongside this handoff.

## Still open (not this session's work, just reminders)

- StochRSI divergence: deferred by Tiago ("test later in the week").
- Real-time option bid/ask + Greeks/delta-equivalent: still documented gaps.

## Boundaries preserved

Paper-only throughout; no broker credentials, no live orders, no
deploy/commit/push. Full suite **452 tests passing**, `git diff --check` clean.
Concurrent in-flight work (relay ingestion + `close_instruments` in
`webhook_receiver.py`, `positions.py`, `tests/test_webhook.py`) was left
untouched.
