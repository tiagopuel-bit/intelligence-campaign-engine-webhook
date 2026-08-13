# Task Packet — Live OHLC for AMC + GME Position Charting

**Requested by:** Tiago, 2026-08-12 (GME added 2026-08-12, same day). **For:** DeepSeek.
**Decision made (do not relitigate):** real OHLC via Massive, not a TradingView embed. The Trade Box overlay (entry zone / target / invalidation drawn directly on price, per Tiago's original reference sketch) needs full control over rendering that a TradingView widget can't give — their embeds don't expose custom shape overlays, and the private Pine script wouldn't render there anyway.

**Scope note — read before starting:** this covers **two assets, AMC and GME**. This is OHLC/charting data only, not a live webhook timeframe rollout — it does not touch or reinterpret the "don't expand until AMC's ladder is clean" rule from the freeze point, which is specifically about TradingView alert timeframes. Pulling chart-support OHLC for GME is a separate, lower-risk data task, same as the historical Massive pulls already covering multiple assets in the Campaign Pattern Atlas.

## Goal

The DNA Asset Landing Page needs a real price chart — for AMC first, then GME to the same completeness — with the open position's Trade Box zones drawn on it, not the sparse alert-event points `/history` currently returns.

## What exists already (don't rebuild)

- Massive API integration is already proven in this project (`research/data_expansion/snapshot_pipeline.py`, `api.massive.com`, `MassiveProvider.base`) — this is an extension of that, not a new integration.
- `webhook_receiver.py` already has the Trade Box fields available per-timeframe via `/state_all/<symbol>` (`close`, `bar_time`) but not the entry/stop/target zone values themselves — those live in Pine's `activeEntry`/`activeStop`/`activeTarget`/`activeTradeSource` variables and are **not currently sent in the webhook payload**. Check whether that needs adding to the Pine `alert()` JSON (same additive pattern as the `session` tag in v12.6.20) before the chart can draw real zones, or whether there's another intended source for those values.

## What's needed

1. **Near-live OHLC feed for AMC, then GME to the same completeness — starting at 3m and building out from there** (3m, 5m, 15m, 30m, 1H, 2H, 3H, 4H, D — same ladder as the live webhook coverage). Recent history is enough (exact window your call, e.g. a few days per timeframe) — this doesn't need to be tick-real-time, just current enough that the chart isn't stale. AMC is the priority; bring GME up to the same coverage once AMC's working, not in parallel from scratch.
2. **A single endpoint exposing it, parameterized by symbol** (e.g. `GET /ohlc/<symbol>/<timeframe>`) in the same style as the existing `/state_all` endpoint — read-only, same auth gate (`state_is_authorized()`), same CORS treatment as `/assets`. No need for asset-specific endpoints.
3. **Confirm the Trade Box zone values path** — either the Pine payload needs the additive fields, or flag back if there's a different intended source, before the frontend can draw the actual zones. GME's Trade Box zones depend on the same fix once it applies there too.

## Explicitly not in scope for this packet

- The chart rendering itself (canvas/SVG, zone drawing) — that's frontend work, stays with Claude Code once the data exists.
- Any asset beyond AMC and GME.
- The live webhook timeframe rollout for GME (or anyone else) — unaffected by this packet, still gated on its own rule.

## What to report back

Same discipline as everything else in this project: a real data pull + endpoint response, not a description of what it's supposed to return.
