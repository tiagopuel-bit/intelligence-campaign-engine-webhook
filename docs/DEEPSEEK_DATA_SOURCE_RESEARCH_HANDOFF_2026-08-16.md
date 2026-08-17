# Data-source research handoff — findings only, nothing built

**From:** DeepSeek, 2026-08-16. **For:** Claude / GPT / DeepSeek (cold-start
context). This records the outcome of the indicator / data-source research task
so the next agent picks it up without re-deriving it — and knows that **no
action has been taken yet**.

## What happened

- Completed the task packet at
  `docs/DEEPSEEK_INDICATOR_DATA_SOURCE_RESEARCH_TASK.md` (research-only).
- Deliverable: `reports/ADDITIONAL_DATA_SOURCE_RESEARCH_2026-08.md`, with a
  PDF of the same name alongside it for a quick full-picture read.
- Scope was held exactly: **no code, no credentials, no spend, no provider
  signup, no provider contact, no new dependency added, no change to
  `paper_execution/` or `massive_*.py`.**

## The one finding to remember

**"Extend, don't add."** The existing provider, Massive (`api.massive.com`,
same `MASSIVE_API_KEY` already in use), already exposes — under its own REST
catalog (`https://massive.com/docs/llms.txt`) — indices, consolidated short
interest (bi-monthly FINRA, `GET /stocks/v1/short-interest`), off-exchange/ATS
short volume (`/stocks/v1/short-volume`), treasury yields, news+sentiment,
analyst ratings, earnings, and ETF fund flows. Most high-value additions are
new **tickers or endpoints on the existing key**, not new vendors.

**Caveat (do not skip):** free-tier eligibility of each endpoint is *unverified
by design*. The documented free plan today is 5 req/min, end-of-day option
aggregates, and no option bid/ask/Greeks/IV/OI (see
`docs/OPTIONS_QUOTE_SOURCE_EVALUATION.md`). Verify at the Massive dashboard
before wiring anything.

## Top shortlist — "do next", in priority order (proposals only)

1. **VIX vol-regime + sector/SPY benchmark via existing Massive index OHLC**
   — the single highest-priority add. Zero new credential; folds in as a
   closed-vocab vol-regime modifier + high-vol veto + relative-strength read.
2. **Massive consolidated short interest + days-to-cover**
   (`/stocks/v1/short-interest`) — completes the short/borrow family next to
   `finra_short.py`; extends the `SHORT_PRESSURE_RISK` modifier. Highest-value
   *AMC-specific* add.
3. **ADV bands derived from existing daily OHLC** — pure derivation, zero new
   source; position-sizing / carry-cost modifier + liquidity veto.
4. **FRED treasury yields (10y/2y curve)** via zero-key
   `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10` (verified
   fetchable, no credential).
5. **CBOE index put/call ratio** (daily, free, no key) — sentiment-regime
   modifier.
   - Runner-up: earnings/dividend calendar as an event veto.

## Defer / reject — do not re-propose without new information

| Item | Verdict | Why |
|---|---|---|
| GEX / gamma exposure | Reject (discipline) | Would synthesize Greeks; free plan lacks OI + IV. |
| CTB / locates via iborrowdesk | Reject | ToS scrape of a broker's site; locates are broker-only. |
| Order-book depth (L2) | Reject | Needs broker feed or paid data. |
| Unusual options activity vendors | Reject | Paid ($40–200+/mo). |
| Time & sales / footprint | Reject | Real-time tick data is paid. |
| Social sentiment (Reddit/X/StockTwits) | Reject | Key-gated / paywalled / ToS. |
| IV rank / IV term structure / max pain | Defer | Known gap: free plan has no IV/OI. |
| Effective spread / slippage model | Defer | Known gap: no real-time bid/ask. |
| Alternative data (web/app/satellite) | Reject | Cost/coverage traps. |

## Status — awaiting Tiago, nothing to build

All five shortlist items are **proposals, not tasks**. Do **not** add a ticker,
wire an endpoint, or create a client module until Tiago explicitly authorizes
a specific item. The full evaluation (per-family tables with source/cost/
freshness/effort/discipline/priority for every candidate) is in the report —
read it before drafting any build plan for one of the shortlist items.

## Boundary

Research only, as scoped. Nothing was implemented, contacted, purchased, or
signed up for.
