# VIX vol-regime + sector/SPY relative-strength — spec (pre-build)

**Status:** specification only. No build authorized. Claude reviews before
any implementation. Follows `reports/ADDITIONAL_DATA_SOURCE_RESEARCH_2026-08.md`
§3 (shortlist) and §2.6 (macro/cross-asset).

## 0. Prerequisite — data-source check (result, stated plainly)

- **Sector ETFs (XLF/XLE/XLK/…) and SPY are ordinary stock/ETF tickers, not
  indices.** They are already reachable through the existing
  `massive_ohlc.py` path (`GET /v2/aggs/ticker/{sym}/range/...`, any
  `[A-Z0-9.-]` symbol). The relative-strength leg needs **no new endpoint, no
  new credential** — verified against the code, not assumed.
- **VIX is an index.** Massive exposes it as `GET
  /v2/aggs/ticker/I:VIX/range/...` (index tickers are `I:`-prefixed, e.g.
  `I:NDX` in the docs sample). The docs state the endpoint is **"included in
  all Indices plans"** with recency tiered by plan: *Indices Basic =
  end-of-day, Starter = 15-min delayed, Advanced = real-time*
  (https://massive.com/docs/rest/indices/aggregates/custom-bars).
- **Open item (one decision, not an assumption):** whether the project's
  current `MASSIVE_API_KEY` plan includes an *Indices* tier (the free plan
  today is 5 req/min + intraday stocks + EOD options; indices recency on the
  cheapest tier is EOD). This requires a one-click dashboard check or a single
  manual request with the key — I did **not** make that request.
- **Consequence for this spec:** a vol-regime gate is inherently a **daily
  (DELAYED)** read — a percentile of VIX against its own history does not need
  intraday precision. **End-of-day VIX on Indices Basic is sufficient.** The
  spec is therefore written against **DELAYED (EOD) VIX**, and only the
  *recency label* changes if the key later has a faster tier. If the key has
  no Indices tier at all, only the VIX leg is blocked (sector/SPY is not);
  FRED `VIXCLS` is a possible fallback but is **not** adopted without checking
  back, per the task.

## 1. Vol-regime vocabulary (closed set)

`LOW / NORMAL / ELEVATED / HIGH`, computed from the EOD VIX close ranked
against VIX's **own trailing history** — percentile-based, no arbitrary round
numbers (VIX = 20/30 are not used as thresholds).

- Window: **trailing 1260 trading days (~5 years)** of VIX daily closes.
- Rank = percentile of today's VIX close within that window (inclusive method,
  same as `adv_liquidity.py`).
- Thresholds (declared):
  - `LOW` — VIX ≤ 25th percentile
  - `NORMAL` — 25th < VIX ≤ 75th percentile
  - `ELEVATED` — 75th < VIX ≤ 90th percentile
  - `HIGH` — VIX > 90th percentile
- `NO_DATA` when fewer than 252 VIX closes are available (no-basis, fail-closed).
- Justification: quartiles + a p90 tail capture the "ordinary vs. stress"
  boundary without hand-picking levels; p90 is the regime that has historically
  coincided with the violent moves that matter for AMC/GME.

## 2. What it gates

The "high-vol veto" is defined precisely and narrowly:

- **`HIGH` vetoes new entries only.** It never blocks exits, never blocks
  risk-reducing actions, and never changes an existing stop/protect decision —
  consistent with the standing principle that `AUTO_IF_VERY_HIGH_PAPER` applies
  only to risk-reducing actions. A `HIGH` regime means "do not add / do not
  open," not "exit."
- **`ELEVATED` is an advisory caution flag** (not a veto): new entries are
  allowed but carry a visible "elevated vol" modifier.
- **`LOW`/`NORMAL` are neutral** (no flag).
- **Plug-in point:** an advisory dashboard flag in `ui/dna_dashboard.html`
  first. **It is NOT wired into `paper_execution/` evidence roots or
  auto-execution** — that is a separate, later, explicit authorization in the
  same category as the multi-asset auto-entry question.

## 3. Relative-strength read (sector/SPY benchmark)

A **discrete modifier, not a beta score** (no regression, no covariance):

- Per asset, compare the asset's 20-session return to SPY's 20-session return.
- `OUTPERFORM` — asset return − SPY return > +2.0 percentage points
- `INLINE` — |asset return − SPY return| ≤ 2.0 pp
- `UNDERPERFORM` — asset return − SPY return < −2.0 pp
- `NO_DATA` — insufficient daily bars for a 20-session window.
- The ±2.0 pp band is a declared, replaceable constant; it exists only to make
  the read categorical, not to claim an edge. Sector ETFs (XLF/XLE/XLK) are a
  follow-on refinement (asset-vs-sector) and are out of scope for the first
  build; SPY is the single benchmark.

## 4. Scope

**Asset-agnostic, all 7 tracked assets** (AMC, GME, PYPL, RBLX, SPY, VALE, U).
The VIX regime is one global read shared by every asset; the relative-strength
read is per-asset vs SPY. Structured asset-agnostic from the start (unlike the
per-asset reliability mask) because vol regime and benchmark strength are
cross-asset by nature, not AMC-specific.

## 5. Fold-in mechanism (not a new score)

Three discrete outputs, all closed-vocabulary, none numeric scores:

1. `VOL_REGIME: LOW/NORMAL/ELEVATED/HIGH/NO_DATA` — a regime modifier + the
   `HIGH` veto (entries only).
2. `REL_STRENGTH: OUTPERFORM/INLINE/UNDERPERFORM/NO_DATA` — a positioning
   modifier.
3. Freshness label: `DELAYED` (EOD VIX / EOD daily bars).

## 6. Boundary

Spec only. No code written, no endpoint wired, no `paper_execution/` change,
no credential touched, no spend. Build is a separate authorization after
Claude reviews this spec and Tiago confirms the Indices-tier question in §0.
