# TradingView Alert Capacity Plan

Status: deferred until the Plus-plan technical-alert limit becomes restrictive.

## Current allowance and usage model

TradingView Plus provides separate allowances of 100 price alerts and 100
technical alerts. DNA Pine `alert()` webhooks count as technical alerts.

The fully tracked universe currently implies approximately:

- 9 assets;
- 10 timeframes per fully tracked asset: 3m, 5m, 15m, 30m, 1H, 2H, 3H,
  4H, Daily and Weekly;
- 90 technical alerts if every asset/timeframe uses an independent alert;
- 10 remaining technical-alert slots.

Plus does not provide the Premium watchlist-alert allowance, so the capacity
plan must not assume that existing watchlist alerts remain available.

## Immediate fallback if capacity is reached

Keep full ten-timeframe coverage for AMC and assets with open positions or an
active campaign. Reduce passive radar assets to the core monitoring ladder:
15m, 30m, 1H, 4H, Daily and Weekly. Preserve spare slots for newly opened
positions, validation alerts and temporary investigations.

No automatic removal or reprioritization of existing alerts is authorized by
this document.

## Preferred engineering solution

Build a separate research-only **DNA MTF Webhook Relay** that uses one alert
per asset and requests the remaining timeframes inside Pine. Every webhook
must retain the source timeframe, event identity, bar timestamp and price so
Railway continues storing independent timeframe state.

Do not replace the production alerts immediately. Run the relay beside AMC's
native per-timeframe alerts and compare:

1. event type and event priority;
2. signal-bar and decision timestamps;
3. price and relevant DNA fields;
4. deduplication and bar-close behavior;
5. behavior across market sessions and higher-timeframe boundaries.

Only retire native alerts after the relay demonstrates acceptable parity.
The expected end state is approximately nine technical alerts for nine assets
instead of approximately ninety.

## Safety constraints

- Preserve the production DNA engine until fidelity is demonstrated.
- Confirm higher-timeframe bars before emitting events; avoid repainting.
- Deduplicate per symbol, timeframe, event and confirmed bar.
- Avoid alert storms: TradingView can stop a script alert if it triggers more
  than 15 times in three minutes.
- Recreate TradingView alerts after any Pine code or input change because an
  active alert retains its creation-time script/settings snapshot.
- Massive Stocks Basic is end-of-day and cannot independently replace
  TradingView for live intraday DNA monitoring.

## Activation trigger

Revisit this plan when any of the following occurs:

- technical-alert usage reaches 85–90 active alerts;
- a tenth asset requires full monitoring;
- multiple new positions require full timeframe coverage;
- watchlist alerts become unavailable after the Plus subscription begins.

