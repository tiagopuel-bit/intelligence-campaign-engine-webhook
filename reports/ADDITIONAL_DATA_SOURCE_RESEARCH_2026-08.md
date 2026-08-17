# Additional Data Source Research — 2026-08

**Requested by:** Tiago · 2026-08-16 · **Scope:** research-only. No code, no
credentials, no spend, no provider signup. This is a decision-aid menu, not an
integration plan.

## 0. The one strategic finding: extend, don't add

The single most important result of this pass is that **most of the high-value
additions are already reachable through the existing provider, Massive
(`api.massive.com`)**, not through new vendors. Massive's catalog
(https://massive.com/docs/llms.txt) exposes, under the same `MASSIVE_API_KEY`
already in use:

- **Indices** (REST OHLC aggregates + snapshots + a real-time value websocket) —
  so VIX, sector indices, and a SPY benchmark are a *ticker add*, not a provider
  add.
- **Stocks fundamentals — Short Interest** (`GET /stocks/v1/short-interest`,
  "included in all Stocks plans", updated every 2 weeks, history to 2017-12-29;
  fields `short_interest`, `days_to_cover`, `avg_daily_volume`, `settlement_date`).
- **Stocks fundamentals — Short Volume** (`/stocks/v1/short-volume`, daily
  off-exchange / ATS short-sale volume).
- **Economy — Treasury Yields** (plus inflation and labor market, all Federal
  Reserve data).
- **Stocks — News (with sentiment), analyst ratings (Benzinga), earnings
  (Benzinga), ETF fund flows (ETF Global), corporate events (Wall Street
  Horizon), NBBO last-quote / quotes / tick trades.**

**Honest caveat:** the documented *free* plan is 5 req/min, end-of-day option
aggregates, and no option bid/ask/Greeks/IV/OI (see
`docs/OPTIONS_QUOTE_SOURCE_EVALUATION.md`). Whether each endpoint above is on
the free tier must be verified at https://massive.com/dashboard before wiring —
but *no new signup, key, or provider* is required, which changes the
signal-per-cost-per-effort math for several items below.

## 1. Covered already (reference only — do not re-propose)

- Indicators: `lib/pine_replay_v12_6_19.py` (RSI, EMA ladder + slopes, ATR,
  Bollinger, volume ratio, `campaignScore`, phase machine, 14 campaign events,
  `exhaustion_warning`).
- Sources wired: Massive free OHLC (intraday/daily) + options chain + option
  daily bars, TradingView webhooks, underlying/option heartbeats, SEC filings
  (`sec_filings.py`), FINRA daily short-sale volume (`finra_short.py`).
- System: paper execution (4 evidence roots, kill switch,
  `AUTO_IF_VERY_HIGH_PAPER`), `dna_insight_library.py` closed vocabulary,
  per-asset reliability mask, campaign lifecycle detector.
- Already-known gaps (reference, not new): real-time option bid/ask,
  Greeks/delta-equivalent exposure, CTB/locates, per-position SL/TP brackets,
  StochRSI divergence.

## 2. Evaluation tables by family

Columns: **what it adds** (which DNA decision + how it folds in — as a discrete
flag / veto / carry cost / closed-vocabulary modifier, never a new score),
**source · cost · credential**, **freshness** (LIVE / DELAYED / STALE),
**effort** (small = client module + field; medium = new table/endpoint; large =
new provider + backfill), **discipline fit**, **priority**.

### 2.1 Order flow / microstructure

| Candidate | What it adds | Source · cost · credential | Freshness | Effort | Discipline fit | Priority |
|---|---|---|---|---|---|---|
| Off-exchange / ATS ("dark-pool") volume + short volume | Off-exchange footprint read → closed-vocab modifier (off-exchange share bands) for the AMC campaign-lifecycle / squeeze reads | FINRA OTC (ATS & Non-ATS) Transparency — free, delayed, requires accepting a data agreement (`https://www.finra.org/filing-reporting/otc-transparency`, data at `otctransparency.finra.org`); or Massive `/stocks/v1/short-volume` (same key) | DELAYED (T+1) | Small–Medium | OK | **Medium** |
| Time & sales / tick tape | Microstructure burst / print flags → discrete flag | Massive/Polygon trades endpoint (real-time = paid tier) | LIVE (paid) | Medium–Large | OK | Reject (cost) |
| Footprint / volume profile | Structural level evidence (could inform Trade Box levels) | Derived from tick data (paid), or low-fidelity from existing bars | DELAYED | Large | OK | Reject (cost) |
| Order-book depth / balance (L2) | Depth-imbalance flag → entry timing | Broker feed or paid L2; no zero-credential source | LIVE (paid) | Large | **Reject** — requires broker/feed | Reject |
| Effective spread | Execution-quality realism | NBBO quotes (real-time = paid; options NBBO is a known gap) | DELAYED–LIVE | Small | OK | Defer (overlaps known gap) |

### 2.2 Options flow

| Candidate | What it adds | Source · cost · credential | Freshness | Effort | Discipline fit | Priority |
|---|---|---|---|---|---|---|
| Index put/call ratio | Sentiment regime modifier (fear/greed) + veto on extremes → closed-vocab modifier | CBOE daily market statistics — free, public, no key (`https://www.cboe.com/us/options/market_statistics/daily/`) | DELAYED (daily EOD) | Small | OK | **Medium** |
| Per-ticker put/call | Asset-level sentiment | Derive from existing Massive option daily bars (covered data) | DELAYED | Small | OK | Low (re-derivation) |
| Unusual options activity | Entry-timing / conviction flag | Unusual Whales / FlowAlgo / Barchart — paid (~$40–200+/mo) | DELAYED–LIVE | Medium | OK | Reject (cost) |
| GEX / gamma exposure | Dealer-hedging pin / acceleration read | SpotGamma (paid) or compute from OI + Greeks (free plan has neither) | DELAYED | Large | **Reject** — would synthesize Greeks | Reject (discipline) |
| IV rank / IV term structure | Vol-percentile regime → modifier | Needs option IV (free plan lacks IV) — known gap | DELAYED | Medium | OK | Defer (known gap) |
| Max pain | Pinning level → discrete flag | Needs OI by strike (free plan lacks OI) — known gap | DELAYED | Medium | OK | Defer (known gap) |

### 2.3 Short / borrow (beyond the FINRA CDN already wired)

| Candidate | What it adds | Source · cost · credential | Freshness | Effort | Discipline fit | Priority |
|---|---|---|---|---|---|---|
| Consolidated short interest + days-to-cover | Squeeze / positioning read → closed-vocab modifier extending `SHORT_PRESSURE_RISK` in `dna_insight_library.py`, plus sizing context | Massive `/stocks/v1/short-interest` (in all Stocks plans, bi-weekly) — same key; alt: FINRA Query API (free registration, `developer.finra.org`) | DELAYED (bi-monthly) | Small–Medium | OK | **High** |
| Off-exchange / ATS short volume | Same slice as 2.1 row 1 | Massive `/stocks/v1/short-volume` | DELAYED | Small | OK | **Medium** |
| CTB rate / shares available / locates | Borrow-cost carry + squeeze trigger | iborrowdesk.com (free web, no API, ToS-scrape) / ORTEX, S3 (paid); locates are broker-only | DELAYED | Medium | **Reject** — ToS scrape / broker locates | Reject |
| Utilization / borrow fee | — | ORTEX / S3 (paid) | DELAYED | Medium | OK | Reject (cost) |

### 2.4 Liquidity / execution

| Candidate | What it adds | Source · cost · credential | Freshness | Effort | Discipline fit | Priority |
|---|---|---|---|---|---|---|
| ADV bands | Position-sizing / carry-cost modifier + liquidity veto | Derive from existing Massive daily OHLC (zero new source) | DELAYED (daily) | Small | OK | **High** |
| Bid-ask spread (stocks) | Execution realism for shares | Massive stocks NBBO last-quote (free-tier TBD) | LIVE (if included) | Small | OK | **Medium** |
| Slippage model | Sizing realism | Needs spread + depth (see known gap) | — | Medium | OK | Defer (needs gap) |

### 2.5 Sentiment / positioning

| Candidate | What it adds | Source · cost · credential | Freshness | Effort | Discipline fit | Priority |
|---|---|---|---|---|---|---|
| News + sentiment | Catalyst flag → discrete flag | Massive news endpoint (likely paid tier) | LIVE | Medium | OK | Defer (cost/verify) |
| Social (Reddit / X / StockTwits) | Retail sentiment | Key-gated / paywalled / ToS-restricted APIs | LIVE | Medium | **Reject** — ToS/key | Reject |
| Analyst ratings / revisions | Consensus modifier | Massive Benzinga partner endpoints (likely paid) / Finnhub free tier (key) | DELAYED | Medium | OK | Defer (cost/key) |
| Insider transactions | — | **Covered** — `sec_filings.py` (INSIDER_FILING) | — | — | — | Covered |
| Buybacks | — | **Covered** via SEC filings + Massive corporate actions | — | — | — | Covered (Low enhancement) |
| Fund flows (ETF) | Rotation read | Massive ETF Global fund flows (likely paid) | DELAYED | Medium | OK | Defer (cost) |

### 2.6 Macro / cross-asset

| Candidate | What it adds | Source · cost · credential | Freshness | Effort | Discipline fit | Priority |
|---|---|---|---|---|---|---|
| VIX / vol regime | Vol-regime modifier + high-vol veto → closed-vocab modifier + veto | Massive index OHLC (VIX) — same key, add ticker; alt: FRED `VIXCLS` | DELAYED–LIVE | Small | OK | **High** |
| Sector / rotation | Relative-strength modifier → closed-vocab modifier | Massive sector-ETF OHLC (XLF/XLE/XLK/…) — add tickers | DELAYED–LIVE | Small | OK | **High** |
| Correlation / β | Position-sizing modifier | Derive from existing Massive OHLC (asset vs SPY) | DELAYED | Small | OK | **Medium** |
| Rates (10y / 2y curve) | Macro carry / regime context | FRED `fredgraph.csv` (zero-key, verified: `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10`); or Massive Treasury Yields | DELAYED (daily) | Small | OK | **Medium** |
| Seasonality | Descriptive context only | Derive from existing daily OHLC | STALE | Small | OK | Low (descriptive) |
| Earnings / dividend calendar | Event veto — avoid entries into earnings | Massive Corporate Events (Wall Street Horizon) / SEC | DELAYED | Small–Medium | OK | **Medium** |

### 2.7 Alternative data

| Candidate | What it adds | Source · cost · credential | Freshness | Effort | Discipline fit | Priority |
|---|---|---|---|---|---|---|
| Web traffic | — | Similarweb (paid) | STALE | Large | OK | Reject (cost/coverage) |
| App usage | — | data.ai (paid) | STALE | Large | OK | Reject |
| Satellite / foot traffic | — | RS Metrics (paid) | STALE | Large | OK | Reject |
| Consumer spending | — | Massive Fable Data (European panel — wrong geography for AMC) | STALE | — | Reject — irrelevant | Reject |

## 3. Shortlist — top "do next"

Best signal-per-cost-per-effort for *this* project (paper challenge,
AMC-anchored, no real bid/ask, no broker):

1. **VIX vol-regime + sector/SPY benchmark via existing Massive index OHLC.**
   Add index/sector tickers to `massive_ohlc.py`; derive a closed-vocabulary
   vol-regime (LOW/NORMAL/ELEVATED/HIGH) + a relative-strength read. Folds in as
   a modifier and a high-vol veto. Zero new credential, small effort, touches
   entry timing, exit/protection, sizing, and the reliability mask.
2. **Consolidated short interest + days-to-cover (Massive
   `/stocks/v1/short-interest`).** Completes the short/borrow family right next
   to the brand-new `finra_short.py`, on the same API key. Folds in as an
   extension of the `SHORT_PRESSURE_RISK` modifier (squeeze/positioning). AMC is
   a heavily shorted name, so this is the highest-value *AMC-specific* add.
3. **ADV bands derived from existing daily OHLC.** Pure derivation, zero new
   source; a position-sizing / carry-cost modifier + liquidity veto. Cheapest
   possible improvement to sizing realism.
4. **FRED treasury yields (10y/2y curve) via zero-key `fredgraph.csv`.** Macro
   carry/regime context; DELAYED but zero-credential and verifiably fetchable.
5. **CBOE index put/call ratio (daily, free, no key).** A one-number sentiment
   regime modifier with a public, checkable source.

Runner-up: **earnings/dividend calendar** as an event veto (avoids entering a
campaign add right into a binary event) — slightly more effort than the top
five because it needs a calendar endpoint or partner data.

**Single highest-priority add:** the macro/cross-asset extension (item 1) —
VIX vol-regime + sector/SPY benchmark — because it is the only candidate that
is (a) reachable with zero new credential, (b) LIVE-adjacent rather than
DELAYED, and (c) broad enough to touch entry, exit, sizing, *and* the
reliability mask simultaneously.

## 4. Defer / reject list

| Item | Verdict | Why |
|---|---|---|
| GEX / gamma exposure | **Reject (most surprising)** | The single most-cited "options flow" edge, but computing it honestly needs OI + Greeks; the free plan has neither, and synthesizing Greeks is explicitly out of bounds ("no invented numbers"). It fails the *discipline* test, not just cost. |
| CTB rate / shares available / locates (via iborrowdesk) | **Reject** | *Looks* free, but iborrowdesk is an undocumented scrape of a broker's website (ToS), and locates are broker-only. Fails discipline + freshness. |
| Order-book depth / balance (L2) | **Reject** | Requires a broker feed or an expensive market-data subscription; violates no-broker + no-spend. |
| Unusual options activity (UOA vendors) | **Reject** | Paywalled ($40–200+/mo), and the free plan lacks the OI/IV needed to even approximate it independently. |
| Time & sales / footprint / tick tape | **Reject** | Real-time tick data is paid; low-fidelity derivations from existing bars are already covered by volume ratio / Bollinger. |
| Social sentiment (Reddit / X / StockTwits) | **Reject** | Key-gated, paywalled, or ToS-restricted; no honest zero-credential path. |
| IV rank / IV term structure / Max pain | **Defer** | Correct ideas, but each depends on IV or OI, both absent on the free plan (already-known gap). Revisit only after an options-quotes upgrade. |
| Effective spread / slippage model | **Defer** | Depends on real-time bid/ask (known gap). Stock-side NBBO via Massive is the cheap partial step. |
| Alternative data (web/app/satellite) | **Reject** | Paid and coverage-thin; classic cost/coverage traps with no paper-challenge payoff. |
| Seasonality | **Low** | Descriptive only; the project's evidence rules forbid promoting descriptive reads to decision inputs without a controlled study. |

## 5. Boundary

No provider was contacted, no credential added, no money spent, no signup made,
and nothing in `paper_execution/` or `massive_*.py` was modified. Every source
claim above was checked against its documented page during this session
(FINRA short-sale-volume catalog, FINRA short-interest reporting, FINRA OTC/ATS
transparency, CBOE daily market statistics, FRED fredgraph CSV, and the Massive
docs index). Free-tier eligibility of any Massive endpoint is a *pending
verification*, not an assumption.
