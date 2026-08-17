# Task packet — Research: what other indicators / sources / data are worth adding

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. **Scope:** research-only,
produce an evaluated, prioritized menu — no code, no credentials, no spend, no
provider signup.

## Context (so you don't re-derive what's already covered)

The DNA stack already ingests a lot. Do **not** propose re-doing these; treat
them as covered and build *on top*:

- **Indicators (Pine DNA v12.6.x, replayed faithfully in
  `lib/pine_replay_v12_6_19.py`):** RSI(14), EMA 21/50/100/200 + slopes, ATR,
  Bollinger (width/squeeze/expansion), volume ratio, a composite `campaignScore`
  (trend + momentum + volume + structure + compression + expansion), a campaign
  **phase state machine**, and **14 discrete campaign events** (STRONG START,
  CAMPAIGN START, FIRE ADD, ACCUMULATE, IGNITION, ADD, PREMIUM, MANAGE, PEAK,
  FAIL, FAIL TEST, RELOAD, START TEST, IGNITION TEST). Plus one *experimental*
  RSI/price "exhaustion" divergence flag (`exhaustion_warning`), live-only.
- **Data sources already wired:** Massive free plan (OHLC intraday/daily + options
  chain + option daily bars, **no real-time bid/ask**), TradingView alert
  webhooks (live events), underlying/option heartbeats, SEC filings (dilution /
  financing catalyst via `sec_filings.py`), and — brand new this session — **FINRA
  consolidated short interest + daily short sale volume** (free, no credential).
- **System layer:** paper execution (proposals, four evidence roots, kill switch,
  `AUTO_IF_VERY_HIGH_PAPER` for risk-reducing actions only), a closed-vocabulary
  insight library (`dna_insight_library.py`), a per-asset **reliability mask**, and
  a campaign **lifecycle** detector (ignition → establishment → resolution/faded).
- **Already identified as gaps (reference, don't re-list as new):** real-time option
  bid/ask, Greeks/delta-equivalent exposure, CTB/locates, per-position SL/TP
  brackets, StochRSI divergence.

## What to do

Produce a **quick overview research** of candidate indicators / data sources /
information feeds that would be *meaningful* for the DNA algorithm and the DNA
Trader operation, beyond the above. Cover at least these families (and add any
you think of):

1. Order flow / microstructure — time & sales, footprint, dark-pool prints,
   order-book depth/balance, effective spread.
2. Options flow — unusual options activity, put/call ratio, GEX/gamma exposure,
   IV rank/IV term structure, max-pain.
3. Short/borrow (beyond FINRA) — CTB rate, shares available, locates, short
   interest vendors, utilization, borrow fee.
4. Liquidity / execution — bid-ask spread, ADV bands, slippage models.
5. Sentiment / positioning — news, social, analyst ratings/revisions, insider
   transactions, buybacks, fund flows.
6. Macro / cross-asset — VIX/vol regime, rates, sector/rotation, correlation/β,
   seasonality, earnings/dividend calendars.
7. Alternative data — web traffic, app usage, satellite, etc. (assess honestly,
   most of these are cost/coverage traps for a paper challenge).

For **each** candidate, evaluate and tabulate:

- **What it adds** — which specific DNA decision it improves (entry timing,
  exit/protection, campaign lifecycle, position sizing, risk) and how it would
  fold into the existing machinery (as a discrete flag / veto / carry cost /
  closed-vocabulary modifier — *not* a new score).
- **Source + cost + credential** — named provider, free vs paid, what account/API
  key is needed. Be specific; prefer zero-credential public sources where honest.
- **Freshness / latency** — real-time vs delayed vs stale (reuse the existing
  LIVE/DELAYED/STALE vocabulary).
- **Integration effort** — rough (small = a client module + a field; medium = new
  ingestion table + endpoint; large = new provider + backfill).
- **Discipline fit** — does it respect the project's rules: paper-only, no
  invented numbers (no synthesized Greeks unless data supports them), closed
  vocabulary, fail-closed on missing/stale data, no broker credentials?
- **Priority** — High / Medium / Low / Reject, with a one-line justification.

## Deliverable

A single markdown doc (put it in `reports/`, name it
`ADDITIONAL_DATA_SOURCE_RESEARCH_2026-08.md`) with:

1. A ranked evaluation table (or tables by family) using the columns above.
2. A **shortlist of the top 3–5 "do next"** — the ones with the best
   signal-per-cost-per-effort ratio for *this* project specifically (paper
   challenge, AMC-anchored, no real bid/ask, no broker).
3. An **explicit defer/reject list** — anything that sounds good but fails the
   cost, freshness, or discipline-fit test, with the reason.

## Boundaries

- Research only. No code, no API keys, no account signups, no spend, no
  provider requests, no new dependency added.
- Do not re-spec existing indicators; reference them as covered.
- Every claim about a source (what it provides, cost, freshness) must be
  checkable — cite the source/doc URL you verified, don't invent.
- Do not propose anything that requires broker credentials or real orders.

## What to report back

The path to the written doc, plus a one-paragraph summary: the top shortlist,
the single highest-priority add, and the most surprising reject/defer.
