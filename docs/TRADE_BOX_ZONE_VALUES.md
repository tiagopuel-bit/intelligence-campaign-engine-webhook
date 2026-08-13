# Trade Box Zone Values — Source Confirmation

**Status:** CONFIRMED — Pine additive fields required (not present today).

## Question (from `CHART_OHLC_TASK_PACKET.md`)

Whether the open position's Trade Box zones (entry / stop / target) need to be
added to the Pine `alert()` JSON payload, or whether another source already
supplies them.

## Answer

The webhook payload does **not** carry the zone values today. They must be
added to the Pine `alert()` JSON as additive fields — the same additive pattern
used for the `session` tag in v12.6.20 (no logic/threshold/trigger change).

The values already exist as Pine series in `Pine/DNA_v12.6.20.pine`; they are
just not serialized into the alert message:

| Pine variable | Line (v12.6.20) | Meaning |
|---|---|---|
| `activeEntry` | 1350, 1395, 1522 | Trade Box reference entry price |
| `activeStop` | 1351, 1396, 1523 | Active stop (or hard floor when cross-TF aligned) |
| `activeTarget` | 1353, 1405, 1525 | Reward target |
| `activeTradeSource` | 1357, 1408, 1528 | Why the box opened (e.g. `CROSS-TF ALIGNED (n/4 TFs)`) |
| `activeTrade` | (trade-open boolean) | Whether a box is currently open |
| `activeTradeOpenPct` | 1533 | Unrealized open P&L % |
| `activeRisk` | 1405 | Entry − stop risk amount |
| `boxEntryScore` | 1428 | Entry quality score (0–100) |

These are reset to `na` / `"NONE"` on every exit (lines 1522–1528), so a
payload emit at the same `barstate.isconfirmed` point as the existing `alert()`
(which is `alert.freq_once_per_bar_close`) naturally reports the *live* zone
state each bar.

## Current payload (v12.6.20, lines 1971–1978) sends

```
symbol, timeframe, phase, health, score, confidence, momentum, status, action,
exhaustion_warning, reload_quality, htf_phase, campaign_alignment, last_fail_type,
event, rsi, ema21_distance_atr, entry_signal_state, entry_signal_extension,
session, close, time
```

No `activeEntry` / `activeStop` / `activeTarget` / `activeTradeSource`.

## Recommended additive fields (next Pine patch, e.g. v12.6.21)

Emit alongside the existing payload, using the existing `na(x) ? "N/A" : x`
guard so `na` values serialize cleanly:

```pine
,"active_trade": <0|1>
,"active_entry": <activeEntry or "N/A">
,"active_stop": <activeStop or "N/A">
,"active_target": <activeTarget or "N/A">
,"active_trade_source": <activeTradeSource or "N/A">
,"active_trade_open_pct": <activeTradeOpenPct or "N/A">
```

Receiver-side, these map directly to new nullable columns on the `alerts` row
and to `_shape_state`, so `/state_all/<symbol>` can serve the zone values next
to `close`/`bar_time` for the frontend to draw real zones.

## Boundary (unchanged)

This is an additive payload change only, matching the v12.6.19→v12.6.20
`session` precedent. No Trade Box logic, thresholds, triggers, or strategy
behavior change. The frontend chart rendering itself stays with Claude Code.
