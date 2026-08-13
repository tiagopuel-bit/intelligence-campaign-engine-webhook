# ETH Data Validation Protocol (draft)

**Status:** validation checklist for Tiago's manual ETH pull. Not yet a data source.
**Mirrors:** the AMC 3m validation approach (session-boundary bar counts, no
RTH/ETH overlap, gap preservation, per-session expected bar counts), extended
to the full extended-hours session.
**Consumer contract:** once the receiver tags `session` (v12.6.20), ETH rows must
carry the correct PRE/RTH/POST tag so Track 2's coverage matrix splits RTH vs
ETH on stored data instead of guessing from time-of-day.

---

## 1. Session definitions (America/New_York)

| Segment | Window (ET) | Minutes |
|---|---|---:|
| Pre-market (PRE) | 04:00 – 09:30 | 330 |
| Regular (RTH) | 09:30 – 16:00 | 390 |
| After-hours (POST) | 16:00 – 20:00 | 240 |
| **Full ETH session** | **04:00 – 20:00** | **960** |

Early-close days: RTH ends at 13:00 (09:30–13:00 = 210 min); PRE and POST are
unaffected. Use the audited Cboe early-close calendar (same one the RTH pipeline
uses).

A bar's session tag is derived from its **bar-open time**:
- open ∈ [04:00, 09:30) → `PRE`
- open ∈ [09:30, 16:00) → `RTH`
- open ∈ [16:00, 20:00) → `POST`

---

## 2. Expected completed-bar counts per session

| Timeframe | Full ETH (04:00–20:00) | PRE (330m) | RTH (390m) | POST (240m) | RTH early-close (210m) |
|---:|---:|---:|---:|---:|---:|
| 1m | 960 | 330 | 390 | 240 | 210 |
| 3m | 320 | 110 | 130 | 80 | 70 |
| 5m | 192 | 66 | 78 | 48 | 42 |
| 15m | 64 | 22 | 26 | 16 | 14 |
| 30m | 32 | 11 | 13 | 8 | 7 |

The 13:00 closing-auction print is folded into the prior real bar (same rule as
the audited RTH/5m pipeline). Full RTH = 130 completed 3m bars; a 210-minute
early close = 70.

---

## 3. Validation gates (each must PASS before ETH is trusted)

| # | Gate | What to check | Pass condition |
|---|---|---|---|
| 1 | Schema | required columns present, numeric types | `time/open/high/low/close/volume` (or provider equivalent) parse cleanly |
| 2 | Ordering | timestamps strictly increasing | zero out-of-order rows |
| 3 | Duplicates | no two rows share a timestamp | zero duplicate timestamps |
| 4 | Timezone | timestamps resolve to UTC correctly | no ambiguous/naive timestamps |
| 5 | OHLC invariants | `high >= max(open,close)`, `low <= min(open,close)`, `high >= low` | zero violations |
| 6 | Volume | volume non-negative | zero negative volumes |
| 7 | Session boundary | no bar-open outside 04:00–20:00 ET | zero bars < 04:00 or >= 20:00 |
| 8 | Session tag | PRE/RTH/POST derived from bar-open matches the exported tag (if any) | zero mismatches |
| 9 | No RTH/ETH overlap | ETH's RTH-portion bars equal the RTH-only stream bar-for-bar (OHLC) | zero discrepancies on shared timestamps |
| 10 | Gap preservation | authentic missing bars are present as gaps, not forward-filled | missing/partial sessions are recorded, never imputed |
| 11 | Per-session counts | each session's bar count matches §2 (full vs early-close) | counts match, or the discrepancy is a recorded gap |
| 12 | Aggregation consistency | if ETH is derived (3m from 1m, etc.), OHLCV aggregates exactly | derived bars reconcile to native bars |

---

## 4. What to record alongside the data

- Provider, plan tier, and exact acquisition date range.
- Per-session coverage ledger: which (date, session) have full vs partial vs
  missing bar counts, and the early-close dates applied.
- Any corporate-action / split discontinuities (flagged, not repaired).
- The frozen manifest + SHA-256 of the immutable snapshot.

---

## 5. What ETH may and may not do

- ETH is a **separate detection/context stream**. It never becomes a fill source:
  RAW RTH remains the only executable-price authority.
- ETH may supply PRE/POST deterioration or recovery context (the AMC Signals v2
  RTH/ETH audit already found ETH standalone value is timeframe-gated and noisy;
  Phase 4B closed ETH *context fields* as NOT justified). This protocol validates
  the *data*, not any trading use.
- Until Track 2's coverage matrix is green, ETH rows are tagged but not promoted
  into any decision path.

---

## 6. Sign-off

This is a draft checklist. Tiago validates the pulled ETH files against gates
1–12 and returns the coverage ledger + hashes; nothing downstream (coordinator,
coverage matrix, any outcome) trusts ETH until every gate passes.
