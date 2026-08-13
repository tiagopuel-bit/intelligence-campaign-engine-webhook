# DNA Dashboard — UI Handoff (as of 2026-08-13)

For GPT / any agent picking up the **frontend/UI work**. Everything below is the
current, working state of the webhook + dashboard after the recent backend +
position-tracking build. The API surface here is stable and is what the UI is
built against — build on it, don't redesign the backend to match the UI.

## 1. Where things live

| Path | What |
|---|---|
| `webhook/webhook_receiver.py` | Flask app — all routes (alerts, state, positions, OHLC, chain) |
| `webhook/massive_ohlc.py` | Massive (Polygon) stock OHLC client + shared rate limiter |
| `webhook/massive_options.py` | Massive options chain + per-contract bars |
| `webhook/positions.py` | positions payload validation + row shaping (no Flask import) |
| `webhook/ui/dna_dashboard.html` | **THE dashboard — this is what you'll edit** |
| `webhook/ui/dna_asset_page.html` | older/earlier asset page (legacy) |
| `webhook/ui/dna_asset_page_dev.html` | frozen design exploration (not wired to positions) |
| `webhook/docs/*.md` | task packets + this handoff |
| `webhook/migrations/*.sql` | DB migrations (001 session, 002 positions, 003 trade-box cols) |

Repo: `tiagopuel-bit/intelligence-campaign-engine-webhook` (dedicated git repo).
**Deploy:** `railway up` from `webhook/` (GitHub auto-deploy is broken — Railway
lost the GitHub App connection). The dashboard HTML is opened locally via
`file://`, NOT served by Railway. The base URL field defaults to the Railway
production URL; the token is kept in `localStorage`.

## 2. Auth (everything)

- Reads AND writes are gated by `state_is_authorized()` → send
  `Authorization: Bearer <STATE_API_TOKEN>`.
- `STATE_API_TOKEN` is a Railway env var (the user has the value; don't hardcode
  it into the HTML).
- CORS is fully permissive (`GET, POST, PATCH, DELETE, OPTIONS`, headers
  `Authorization, Content-Type`), so the `file://` dashboard can call the API.
- Only `/health` is public.

## 3. API surface (the contract for the UI)

### Positions (beta — manual log, no broker, human logs every entry/exit)

Two tables: `positions` (one trade idea: symbol + direction + status + opened/closed)
and `position_instruments` (each leg: SHARE / CALL / PUT, with strike, expiration,
quantity, entry_price, entry_time, exit_price, exit_time, status OPEN/CLOSED/ROLLED).
Rolls link legs both ways via `rolled_from_id` / `rolled_to_id`.

- `POST /positions`
  ```json
  {"symbol":"AMC","direction":"LONG","origin_timeframe":"15","origin_event":"STRONG START",
   "notes":"...","instrument":{"type":"CALL","strike":2.5,"expiration":"2026-09-18",
   "quantity":2,"entry_price":0.30,"entry_time":"2026-08-12T14:30:00Z"}}
  ```
  `type` is SHARE|CALL|PUT; SHARE must NOT have strike, CALL/PUT require strike.
  `opened_at` = the first instrument's `entry_time`. Returns 201 + full detail.
- `GET /positions?symbol=AMC&status=OPEN` → `{"count":N,"positions":[{...position
  fields, instrument_count, open_instrument_count}]}` (no instruments array here).
- `GET /positions/<id>` → position fields + `instruments[]` + `dna_context`
  (`{symbol, timeframe_count, states[]}` — the latest alert per timeframe since
  opened, shaped exactly like `/state_all`).
- `PATCH /positions/<id>` body `{status, closed_at, notes, exit_price, exit_time}`
  → when `status="CLOSED"`, closes **all open legs** with `exit_price`/`exit_time`.
- `POST /positions/<id>/instruments` body `{type, strike, expiration, quantity,
  entry_price, entry_time, rolled_from_id?}` → adds a leg (the "opened" half of a roll).
- `PATCH /positions/<id>/instruments/<iid>` body `{exit_price, exit_time, status,
  rolled_to_id, notes}` → close/update one leg.
- `DELETE /positions/<id>` and `DELETE /positions/<id>/instruments/<iid>`.

### Valuation (near-live, Massive free plan)

- `GET /positions/<id>/valuation` → values only the OPEN legs:
  ```json
  {
    "position_id": 1, "symbol": "AMC",
    "underlying": {"symbol":"AMC","current":2.53,"prev":2.4},
    "options": [{
      "contract": {"type":"CALL","strike":2.5,"expiration":"2026-09-18"},
      "contracts": 2, "avg_cost": 0.3, "current_price": 0.3, "prev_price": 0.24,
      "market_value": 60.0, "cost_basis": 0.6, "first_entry": "2026-08-12T14:30:00Z",
      "breakeven": 2.8, "itm": true,
      "today_pnl": 12.0, "today_return_pct": 25.0,
      "total_pnl": 0.0, "total_return_pct": 0.0, "leg_ids": [4]
    }],
    "stock": {"shares":100,"avg_cost":2.53,"current_price":2.53,"prev_price":2.4,
      "market_value":253.0,"cost_basis":253.0,"first_entry":"...","today_pnl":13.0,
      "today_return_pct":5.42,"total_pnl":0.0,"total_return_pct":0.0,"leg_ids":[3]},
    "summary": {"options_contracts":2,"options_value":60.0,"options_today_pnl":12.0,
      "options_total_pnl":0.0,"stock_shares":100,"stock_value":253.0,
      "stock_today_pnl":13.0,"stock_total_pnl":0.0,"total_value":313.0,
      "total_today_pnl":25.0,"total_pnl":0.0},
    "as_of": "2026-08-13T06:40:15+00:00"
  }
  ```
  Definitions: `breakeven` = call `strike+avg_cost` / put `strike−avg_cost`;
  `itm` = underlying above/below strike; `market_value` = price × qty × 100 for
  options, price × shares for stock; `today_pnl` = (current − prev) × qty × mult.
  **"current" is the latest option *close* (delayed), not a real-time quote.**

### Options chain

- `GET /options/chain/<symbol>` → `{"symbol":"AMC","expirations":["2026-08-14",...],
  "contracts":[{"ticker":"O:AMC260918C00002500","contract_type":"CALL","strike":2.5,
  "expiration":"2026-09-18","shares_per_contract":100}]}` (cached 1h).

### Stock OHLC

- `GET /ohlc/<symbol>/<timeframe>` → `{"symbol","timeframe","source":"massive",
  "adjusted":true,"bar_count","start","end","cached","bars":[{"t","o","h","l","c","v"}]}`
  (`t` is epoch **ms**). Ladder: `3m 5m 15m 30m 1H 2H 3H 4H D` (also accepts the
  webhook's numeric labels `5 15 30 60 120 180 240 1D`).

### Alerts / state

- `GET /assets` → `{"asset_count", "assets":[{symbol, timeframe_count, alert_count, last_updated}]}`.
- `GET /state_all/<symbol>` → `{symbol, timeframe_count, states:[{symbol, timeframe,
  phase, health, confidence, momentum, recent_event, exhaustion_warning, reload_quality,
  htf_phase, campaign_alignment, last_fail_type, close, bar_time, rsi, ema21_distance_atr,
  session, active_trade, active_entry, active_stop, active_target, active_trade_source,
  active_trade_open_pct, next_event_after_signal, signal_event, signal_time,
  signal_bar_extension_label}]}`.

## 4. Current dashboard structure (top → bottom)

1. Header (title, base URL, token, Load).
2. **Asset header + verdict** for the selected asset.
3. **"+ Open a position in <sym>"** — a button that expands the entry form
   (direction, Shares/Call/Put, contract picker populated from `/options/chain`,
   qty, entry $, entry time, notes).
4. **Portfolio**:
   - Main summary: Total value · Today · Total return · Realized P&L.
   - **Shares** section (secondary teal): Shares · Value · Today · Total return,
     then holdings (`AMC LONG — 100 shares`).
   - **Options** section (secondary teal): Strategies · Contracts · Options value ·
     Today · Total return, then strategies (`AMC LONG $2.50 CALL SEP 18 2026 (ITM)`).
   - Rows expand (click) to a per-contract detail grid, with **Close…** (prompts an
     exit price, PATCHes the specific legs) and **✕** (deletes the specific legs).
5. **Needs attention** — triage rail of asset cards.
6. **The flow / What to do / raw table** for the selected asset.

## 5. Conventions & gotchas

- **Timestamps are ISO strings** for positions/alerts (`entry_time`, `exit_time`,
  `opened_at`, `received_at`), but **epoch-ms** for OHLC bar `t`. Convert ISO→ms in
  the frontend for chart-marker alignment; don't introduce a second format.
- **Massive free plan = 5 req/min** (token-bucket limiter now bursts the first 5).
  Options **snapshot/real-time quotes + Greeks are 403 on the free plan** — the
  chain + OHLCV bars are free. No live bid/ask or delta/theta.
- **Intraday Massive bars are anchored to 04:00 ET** (extended session), not 9:30
  RTH; 2H/3H/4H can drift across DST. Real consolidated RAW prices, but the x-axis
  won't match a TradingView RTH chart exactly.
- **Pine v12.6.21** adds Trade Box zone fields to the webhook payload (additive);
  the user still needs to paste it into TradingView for live zones to flow. Zones
  are already surfaced through `/state_all`.
- The dashboard is a single self-contained HTML file (inline CSS+JS), opened via
  `file://`. It uses `localStorage` keys `dna_api_base` / `dna_api_token`.
- Dead code left in `dna_dashboard.html` (not called, harmless): `loadPositions`,
  `renderPosition`, `renderPositionRow`, `renderValuationBody`, `contractLabels`,
  `statCard`. Remove or ignore.

## 6. Suggested next UI work (not started)

- **Closed-trades report** — the data is already recorded (`exit_price`/`exit_time`
  per leg); add a "closed" view / realized-P&L history to the dashboard.
- **Price chart with Trade Box zones** — `/ohlc` + the zone values from
  `/state_all` + position entry/exit markers (the packet `CHART_OHLC_TASK_PACKET.md`
  specs this; rendering was always scoped to the frontend).
- Any visual polish on the sections above.
