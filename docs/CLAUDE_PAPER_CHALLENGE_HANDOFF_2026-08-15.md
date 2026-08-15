# Claude handoff — AMC PAPER_ONLY Portfolio Challenge

Date: 2026-08-15 (America/Los_Angeles)

## User intent and boundary

Finish activation of the AMC Portfolio Challenge. It is **PAPER_ONLY**: orders are simulated in the Railway database and must never reach a broker. The dashboard is the persistent system of record; a future dedicated “DNA Paper Trade Desk” chat is the conversational review/approval layer.

## Production checkpoint

- Repository: `https://github.com/tiagopuel-bit/intelligence-campaign-engine-webhook`
- Local repo: `/Users/tiago/Desktop/Campaing Inteligence Engine/webhook`
- Deployed commit before this handoff: `35c550a` (`Activate PAPER_ONLY portfolio challenge infrastructure`)
- Railway base: `https://dna-tradingview-webhook-production.up.railway.app`
- Webhook: `https://dna-tradingview-webhook-production.up.railway.app/webhook`
- Dashboard: `https://dna-tradingview-webhook-production.up.railway.app/dashboard`
- Authenticated paper health: `GET /paper/health`
- `/health` and `/dashboard` returned HTTP 200 after deployment.
- Full local suite before deployment: **340/340 tests passed**; dashboard inline JS syntax check and secret scan passed.

## What is deployed

- Paper API mounted under `/paper/*`.
- Separate authoritative underlying and option heartbeat storage/ingestion through `/webhook`.
- Ordinary DNA alerts cannot masquerade as price heartbeats.
- Exact `position_ref` / `instrument_ref` validation for option relays.
- Atomic experiment activation only after AMC underlying plus every held option has a fresh verified relay.
- Starting paper cash: **$100**; live holdings are snapshotted atomically at activation.
- Event-driven paper runner tick after accepted heartbeats; no laptop service or sleeping loop.
- PAPER_ONLY proposal, approval, revalidation, simulated order/fill, SEC-veto and audit ledgers.
- P3 Asset Page UI: portfolio challenge, daily report, proposal queue, decisions and blockers.
- Pine relay source: `pine_research/DNA_PRICE_HEARTBEAT_RELAY_V1.pine`.

## Current live paper health

Immediately after deployment:

```json
{
  "active_experiment_id": null,
  "authoritative_provider_ready": false,
  "paper_only": true,
  "runner_ready": false,
  "blockers": [
    "BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT",
    "BLOCKED_NO_FRESH_OPTION_HEARTBEAT:6",
    "BLOCKED_NO_FRESH_OPTION_HEARTBEAT:8",
    "BLOCKED_NO_FRESH_OPTION_HEARTBEAT:9",
    "BLOCKED_NO_FRESH_OPTION_HEARTBEAT:10"
  ]
}
```

Do not force activation or bypass these gates.

## Exact open AMC holdings for relay binding

| Position ref | Instrument ref | Holding | TradingView/OPRA contract |
|---:|---:|---|---|
| 4 | 6 | AMC $1.50 CALL, 2027-01-15, qty 2 | `AMC270115C00001500` |
| 5 | 7 | AMC shares, qty 622 | underlying relay uses `AMC`; no option relay |
| 6 | 8 | AMC $1.50 CALL, 2026-12-18, qty 1 | `AMC261218C00001500` |
| 7 | 9 | AMC $1.50 CALL, 2026-09-18, qty 7 | `AMC260918C00001500` |
| 8 | 10 | AMC $1.50 CALL, 2026-08-21, qty 2 | `AMC260821C00001500` |

TradingView may display option symbols with an `OPRA:` exchange prefix. Verify the selected strike and expiration visually; do not rely on a guessed exchange prefix.

## Required TradingView alerts

Create five 1-minute alerts using `DNA Price Heartbeat Relay v1 (PAPER ONLY)` and the production webhook URL.

1. Underlying chart: AMC, 1 minute.
   - Relay type: `UNDERLYING_HEARTBEAT`
   - Underlying symbol: `AMC`
   - Position/instrument refs blank.
2. Option 2027-01-15 $1.50 CALL, 1 minute.
   - Relay type: `OPTION_HEARTBEAT`
   - `position_ref=4`, `instrument_ref=6`
3. Option 2026-12-18 $1.50 CALL, 1 minute.
   - `position_ref=6`, `instrument_ref=8`
4. Option 2026-09-18 $1.50 CALL, 1 minute.
   - `position_ref=7`, `instrument_ref=9`
5. Option 2026-08-21 $1.50 CALL, 1 minute.
   - `position_ref=8`, `instrument_ref=10`

For every alert:

- Condition: **Any alert() function call** from the relay.
- Webhook URL: `https://dna-tradingview-webhook-production.up.railway.app/webhook`
- No custom message; the Pine `alert()` emits the canonical JSON.
- No secret in Pine. Existing webhook authentication remains TradingView source-IP based.
- Use 1-minute charts. The relay intentionally emits only on confirmed 1-minute bars.

## TradingView browser state at handoff

- User successfully signed into TradingView in the Codex in-app browser.
- The relay source was pasted and the corrected 21-line source compiled without editor problems.
- The chart used during compilation was AAPL 5m, so it is **not an activated heartbeat**.
- One stale failed indicator instance still showed a `Runtime error` toolbar from an earlier duplicate-paste attempt; one corrected relay instance was also present. Remove the stale runtime-error instance before configuring AMC.
- The relay source was not verified as saved to the user’s TradingView script library. Prefer saving it with the exact title before creating alerts.

## Pine correction made after deployment

`DNA_PRICE_HEARTBEAT_RELAY_V1.pine` changed its JSON string construction from single-quoted Pine strings to escaped double-quoted strings. The corrected editor source had exactly 21 lines and no editor problem after clean replacement. Commit/push this change with this handoff.

## Activation verification

The market is closed at handoff time. Alert creation alone will not make a fresh heartbeat until a confirmed 1-minute bar arrives. At the next live eligible session:

1. Confirm Railway receives the underlying heartbeat and all four exact option heartbeats.
2. Call authenticated `GET /paper/health`.
3. Expected: no heartbeat blockers, `authoritative_provider_ready=true`, experiment atomically created/activated, and `runner_ready=true` subject to all other safety gates.
4. Confirm the dashboard shows the active challenge and populated insight/report surfaces.
5. Never synthesize a heartbeat or substitute Massive delayed bars to clear a gate.

## Insight/UI behavior expected

Insights must be computed, not redundant descriptions. They should combine:

- multi-timeframe DNA state and the fresh 1-minute underlying heartbeat;
- fresh held-option premium movement, volume/activity, unchanged-print quality and expiry context;
- SEC/catalyst vetoes;
- portfolio goal, drawdown, allocation and exposure limits;
- proposal action, confidence, invalidation and approval deadline.

The dashboard displays state and history. A dedicated Trade Desk chat may discuss or approve proposals, but Railway remains the authoritative state. Very-high-confidence auto actions remain PAPER_ONLY and are restricted by the frozen policy, freshness, SEC and kill-switch gates.

## Safety reminders

- No broker integration or live order path.
- Do not lower freshness, exact-instrument, allocation, SEC, approval or kill-switch gates.
- Do not expose `STATE_API_TOKEN` in chat, Pine, logs or commits.
- Do not use Massive daily/delayed data as a live execution reference.
- If an option has no verified live relay, report `NO_LIVE_CONTRACT_SOURCE` / heartbeat blocker honestly.

