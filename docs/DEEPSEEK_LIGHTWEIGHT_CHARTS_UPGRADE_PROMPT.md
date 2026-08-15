# DeepSeek execution prompt — TradingView Lightweight Charts upgrade

Copy everything below this line into DeepSeek/OpenCode from the dedicated
`webhook/` repository root:

---

You are upgrading the chart layer of the production-connected DNA dashboard.
Execute the work; do not merely propose it.

## Start by reporting the work boundary

Before editing, state:

- **Selected scope:** replace the hand-drawn dashboard canvas chart with the
  open-source TradingView **Lightweight Charts v5.x** engine, and expose the
  existing Massive option aggregate bars through one authenticated API route.
- **Evidence level:** production UI/infrastructure work. This is not research
  evidence, a trading strategy, or permission to change DNA semantics.
- **Likely files:** `ui/dna_dashboard.html`, `massive_options.py`,
  `webhook_receiver.py`, targeted tests, one vendored open-source chart bundle
  plus its license/attribution, and current UI docs.
- **Verification:** backend unit tests with mocked Massive responses, static
  dependency/route checks, and a real-data browser proof for AMC stock and one
  selected AMC option contract before declaring the old canvas replaced.

Read completely before acting:

1. `../AGENTS.md`
2. `docs/UI_HANDOFF.md`
3. `docs/PROGRESS_LOG_2026-08-13.md`
4. `docs/CHART_OHLC_TASK_PACKET.md`
5. `massive_ohlc.py`
6. `massive_options.py`
7. `webhook_receiver.py` chart/options routes
8. `ui/dna_dashboard.html`, especially `deriveHoldings`, selected-holding row
   behavior, `drawChart`, timeframe override, valuation rendering, theme
   switching, and the `/dashboard` serving path

Do not use the TradingView iframe widget, Advanced Charts proprietary library,
Trading Platform library, copied TradingView website code, or an unlicensed
package. Use the official Apache-2.0 `lightweight-charts` standalone v5 build,
pin the exact version, preserve its required license/attribution, and make the
dependency work both when the HTML is opened through `file://` and through the
Railway `/dashboard` route. Do not silently depend on a floating CDN URL. A
vendored pinned production bundle is preferred; if you choose another path,
prove both load modes and document why.

## Non-negotiable product boundary

- DNA is advisory. It does not place or route broker orders.
- Do not modify Pine, alerts, webhooks payload semantics, DNA phase/event
  formulas, decision-engine logic, research artifacts, frozen data, or Railway
  secrets.
- Do not add probabilities, predictive claims, fake prices, fake Greeks,
  bid/ask values, or invented markers.
- RAW Massive OHLC is price authority. Backfilled DNA rows are advisory and must
  remain visually distinguishable where they are used.
- Preserve all current position CRUD, portfolio expansion, held-asset sorting,
  selected-holding toggle/deselect behavior, Campaign Insights, timeframe
  normalization, light/dark themes, and stale/error messaging.
- Do not redesign the entire dashboard in this task. This task upgrades the
  chart engine and the minimum supporting option-history API only.

## Why this is needed

The current `drawChart()` is a manually painted 230px `<canvas>` showing a
close-price line. It is low quality and difficult to extend. The replacement
must be a genuinely useful interactive financial chart, not a cosmetic redraw.

## Phase 1 — option OHLC API, tested first

The Massive free plan has already been verified to return option aggregate
bars. `massive_options.py` currently uses only recent daily bars to value an
option and does not expose full contract history.

Add a safe, read-only route such as:

`GET /options/ohlc/<contract_ticker>/<timeframe>`

Contract tickers are Massive tickers like `O:AMC260821C00004000`. URL encoding
must be handled correctly. The endpoint must:

- use `state_is_authorized()` exactly like `/ohlc`;
- validate option-ticker shape and timeframe against an explicit allowlist;
- return the same normalized bar schema as stock OHLC:
  `{t,o,h,l,c,v}` with epoch-ms `t`, ascending and duplicate-free;
- return metadata including ticker, canonical timeframe, source, bar count,
  start/end, cached and fetched-at;
- share the existing global Massive 5-request/minute limiter;
- cache by contract/timeframe/range with a documented TTL;
- accumulate paginated results safely without leaking the API key;
- map upstream auth/rate/vendor failures consistently with `/ohlc`;
- return honest empty/no-bars behavior;
- never imply the latest daily close is a live quote;
- support enough bounded intervals/lookbacks for the UI to show useful
  1W/1M/3M/YTD/MAX-like views and to keep an older open entry in view. Choose a
  conservative explicit contract rather than making many vendor calls.

Do not duplicate the entire stock provider. Extract/reuse only where doing so
does not destabilize its proven behavior.

Backend tests must cover at least:

- bearer authorization;
- valid encoded `O:` ticker;
- invalid/non-option ticker rejection;
- supported/unsupported timeframe normalization;
- ascending normalized bars;
- pagination;
- cache hit avoids a second vendor call;
- empty results;
- 429/vendor error mapping;
- no API key in response or logs.

Update `docs/UI_HANDOFF.md` with the exact new endpoint response and limitations.

## Phase 2 — standalone real-data chart proof

Before replacing `drawChart()`, build a small isolated proof page or harness
using the same APIs and auth conventions as the dashboard. It must prove:

### Underlying mode

- real candlesticks from `/ohlc/<symbol>/<timeframe>`;
- a separate volume histogram pane;
- readable price/time axes;
- crosshair with OHLCV tooltip;
- mouse/touch pan and zoom;
- responsive resizing;
- light and dark themes;
- current-price line;
- timeframe switch without stale series/markers.

### Selected option mode

- real option-premium candlesticks from the new option route;
- option volume;
- option premium on the y-axis, never the underlying stock price;
- exact open-leg entry markers at recorded `entry_time` and `entry_price`;
- one fixed entry line per open leg;
- weighted average-cost line calculated from open-leg quantities and entry
  prices;
- partial-close/closed-leg markers when those records exist;
- current premium line using the same delayed/latest-close truth as valuation;
- underlying price shown only as contextual text or through an explicit
  Underlying/Option mode switch;
- no invented point when an entry timestamp falls between bars: use the nearest
  valid containing/adjacent bar and preserve the exact timestamp/price in the
  tooltip.

Use official Lightweight Charts v5 APIs. Series markers are the correct base
for Entry/Add/Roll/Partial Close/Exit. Price lines are the correct base for
current price, open-leg entries, weighted average, DNA entry/stop/target. Use a
custom primitive only where needed for an entry/target zone band; do not build
a new rendering engine around the library.

Checkpoint requirement: capture exact endpoint responses (with secrets removed)
and a screenshot or browser verification record for one AMC stock chart and one
real selected AMC option. If browser verification is impossible in the
environment, stop and report the specific gate; do not claim visual success from
static inspection.

## Phase 3 — integrate only after the proof passes

Replace the old canvas internals while preserving the surrounding dashboard.
A small chart adapter/controller is preferred over spreading library calls
through portfolio rendering.

Required integrated behavior:

1. With no holding selected, show the underlying asset chart.
2. Clicking a share holding selects it and shows the underlying chart with only
   that holding's open-leg entries, weighted average, closes and relevant DNA
   levels.
3. Clicking an option strategy/contract selects that exact contract and switches
   the chart to its premium history.
4. The selected portfolio row is visibly marked `Viewing on chart`.
5. Clicking the selected row again deselects it and returns to underlying mode.
6. Provide a compact `Underlying | Option` toggle without losing selection.
7. Each open option leg retains its own entry marker and fixed price line until
   that leg is closed. Closed/partial exits become exit markers; they are not
   silently discarded.
8. Weighted average updates from the real open legs only.
9. Timeframe controls keep the current per-symbol override behavior, but option
   timeframes must reflect what the option API actually supports.
10. Auto-fit/widen must keep the selected entry inside the visible range without
    fetching every timeframe or exceeding the provider budget.
11. Add toggles for Volume, Position, DNA Events and Trade Box. Defaults should
    prioritize position readability. Trade Box should be subtle lines/bands, not
    a giant panel.
12. Use a real candlestick series, volume pane, crosshair tooltip and responsive
    ResizeObserver behavior.
13. Clear/destroy old chart instances and subscriptions when switching symbol,
    holding, timeframe or repainting. No stacked canvases, duplicated listeners,
    memory leaks or stale markers.
14. Show useful loading, no-data, delayed-data and error states without erasing
    the rest of the dashboard.
15. Current colors must come from existing CSS variables and update correctly
    when `dna_theme` changes.

Do not remove the existing chart implementation until the new adapter passes the
proof and integration checks. Then remove dead canvas-only code and CSS cleanly;
do not leave two competing chart engines.

## Phase 4 — acceptance and regression verification

Run the repository's existing full webhook test command plus all new tests.
First discover the exact existing command from the repository/docs; report the
literal command and count. Also perform focused UI verification for:

- AMC underlying, light and dark;
- one AMC share holding;
- one AMC option with two open legs at different costs;
- portfolio click -> option chart -> deselect -> underlying chart;
- manual timeframe changes;
- entry outside the shortest timeframe window;
- option contract with sparse/no bars;
- closed/partial leg marker;
- Trade Box active and inactive;
- theme change after chart creation;
- browser resize;
- both `file://` and Railway-style `/dashboard` asset loading.

Verify that no Pine, engine, research, webhook ingestion, alerts, credentials,
database contents or production trading behavior changed.

## Report-back format

Return exactly:

1. Scope/evidence level and files touched.
2. Lightweight Charts exact version, source, license/attribution path and how it
   loads in both `file://` and `/dashboard` modes.
3. New option-OHLC route, supported intervals/lookbacks, caching and one redacted
   real response summary.
4. Test commands, counts and failures/skips.
5. Real browser proof results for stock and option modes.
6. Selection/entry/add/close/average-cost behavior verified.
7. Rate-limit behavior and number of Massive calls made during proof.
8. Known limitations (delayed option close, no bid/ask, no Greeks, sparse
   contracts, ETH/RTH alignment).
9. Exact commits created and deployment status. Do not deploy unless Tiago
   explicitly authorizes it in the active session.
10. Explicit confirmation that Pine, DNA engine/research, webhook ingestion,
    alerts, secrets and existing database rows were untouched.

If a dependency or real-data gate blocks the work, preserve the passing phase,
state the smallest unblocking action, and do not fake the remaining result.

---
