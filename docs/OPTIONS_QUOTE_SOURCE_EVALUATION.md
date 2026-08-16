# Options Quote-Source Evaluation (research only)

**Purpose:** compare realistic upgrades to the options data source, motivated by
two confirmed constraints: (1) the Massive free plan has no real-time bid/ask
and options data is ~1 day delayed, which weakens the `execution_quality`
`VERY_HIGH` root (its `price_reference` is a bar close, not a fillable quote);
(2) Part 1's coverage study showed PUT liquidity is a real data-quality
constraint — illiquid options don't print on the exact decision bar, so a
richer quote/tick source would both improve fills and let the exact-signal gate
be measured against real market data instead of sparse 15m aggregates.

**This is a comparison document only.** No sign-up, no credential, no
integration, no money, no vendor commitment. The final decision is Tiago's.
Cost figures are approximate and must be verified at purchase time.

## Current state (baseline)

- Provider: Massive (`api.massive.com`), Polygon-compatible endpoints
  (`/v2/aggs`, `/v3/reference/options/contracts`).
- Free plan: ~5 req/min shared limiter; **end-of-day** option aggregates
  (~1 day delayed); no bid/ask, no midpoint, no Greeks, no IV, no OI, no
  real-time option quotes.
- Consequence: the engine's `execution_quality` root is only ever `LIVE` because
  the TradingView `OPTION_HEARTBEAT` relay supplies a fresh 1-minute bar close;
  on the free provider alone it is `DELAYED` and vetoed. The
  `contract_response` root is computed from 15m option aggregates that are
  sparse for illiquid options (the exact-signal-bar absence seen in Part 1).

## Candidates

### 1. Upgraded Massive / Polygon paid tier (lowest friction)

- **What it is:** the same Polygon-shaped API the code already uses, on a paid
  plan. Polygon's options plans add real-time options aggregates and options
  quotes (NBBO bid/ask) via `/v3/quotes/{options_ticker}`, plus Greeks/IV/OI.
  Massive's own paid tier, if it exists, is the same shape.
- **Cost (approx, verify):** Polygon options plans run roughly $29–$199/month
  depending on real-time vs delayed and whether quotes/Greeks are included;
  real-time options quotes are on the higher tiers. Massive's paid tier is
  unverified here.
- **Latency / freshness:** real-time (sub-second to ~1s) NBBO and last-trade for
  options; real-time 1m aggregates. Directly removes the "delayed provider bar"
  veto and lets `execution_quality.price_reference` be a true last-trade or
  midpoint instead of a day-old close.
- **Evidence roots strengthened:** `execution_quality` (real fillable price +
  spread), `contract_response` (real-time `option_return`, `volume_ratio`,
  `range_expansion`, `activity_ratio` on 1m bars instead of sparse 15m).
- **Integration effort:** lowest. `massive_options.py` already targets these
  endpoint shapes; add a `/v3/quotes` method and upgrade the key/tier. No new
  SDK or gateway. Risk: quota/tier limits on the options endpoints need
  checking (they are separate from the aggregate endpoints).

### 2. Tradier (brokerage API, paper sandbox)

- **What it is:** a brokerage API with an options-quote endpoint (NBBO bid/ask,
  greeks) and a free paper/sandbox environment. Real-time market data requires
  a funded account or a paid data feed; the sandbox is typically delayed.
- **Cost (approx, verify):** free sandbox; real-time option quotes generally
  require a funded brokerage account (no monthly subscription cost but account
  funding) or Tradier's own data plan.
- **Latency / freshness:** real-time (for funded accounts) NBBO; sandbox is
  delayed (~15 min) and therefore would NOT clear the `LIVE` freshness gate
  without a funded account.
- **Evidence roots strengthened:** `execution_quality` (true NBBO, spread
  awareness) and `contract_response` (greeks/IV become available, though the
  current engine doesn't consume them).
- **Integration effort:** moderate. New HTTP client + a second credential; the
  data model (bid/ask/quote) is different from the current aggregate-only
  shape. Would need a new quote-adapter layer kept out of `paper_execution`
  until separately authorized.

### 3. Interactive Brokers paper API (TWS / Client Portal)

- **What it is:** IBKR's Client Portal / TWS API exposes real-time options
  NBBO, last-trade, Greeks, and a full paper-account execution path.
- **Cost (approx, verify):** free paper account; real-time US options data is
  usually included for funded accounts or a small monthly data fee.
- **Latency / freshness:** real-time NBBO; highest fidelity of the three.
- **Evidence roots strengthened:** `execution_quality` (NBBO, most accurate
  fillable price) and, longer-term, a genuine paper-order route (which the
  current system deliberately does NOT have and must not silently gain).
- **Integration effort:** highest. Requires running the IBKR Gateway (or
  Client Portal Gateway) as a local process, a websocket/REST adapter, and
  careful scoping so the presence of a real brokerage API never implies a
  live-execution path. This is a much larger security review.

## Recommendation framing (no decision made)

- **If the only goal is to strengthen `execution_quality` cheaply:** upgrade
  Massive/Polygon to a real-time options-quotes tier — it reuses the existing
  endpoint shapes and is the smallest change.
- **If the goal includes a fillable bid/ask with spread for realistic paper
  fills:** Tradier (funded) or IBKR paper are the honest options, at higher
  integration cost; IBKR additionally offers a paper-order route that must be
  treated as a new authorization, not an incidental addition.
- **Do not** expect any provider to fix Part 1's PUT-liquidity finding by
  itself: the exact-signal-bar gate reflects genuinely sparse option trading,
  not just provider latency. A better source lets us measure it against real
  ticks; it does not manufacture prints.

## Boundary

No provider was contacted, no credential added, no money spent, no integration
performed, and nothing in `paper_execution/` was modified. This is a
decision-aid document only.
