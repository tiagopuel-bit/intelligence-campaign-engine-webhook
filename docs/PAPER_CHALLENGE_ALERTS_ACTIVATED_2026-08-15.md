# Paper challenge — TradingView alerts finished, awaiting live market open

Date: 2026-08-15 (America/Los_Angeles). Continues
`CLAUDE_PAPER_CHALLENGE_HANDOFF_2026-08-15.md` — read that first for the
full activation plan, position_ref/instrument_ref table, and safety
boundary. This doc only records what changed since that handoff.

## What got done

- **Relay script saved.** `DNA Price Heartbeat Relay v1 (PAPER ONLY)` is
  now actually saved to the TradingView script library (the original
  handoff explicitly flagged this as unverified — it was in fact not
  saved). Verified the 21-line source has correct indentation: `common` /
  `optionFields` / `alert(...)` all at 4-space indent inside the `if`
  block, `plot(...)` back at column 0 outside it. Matches
  `pine_research/DNA_PRICE_HEARTBEAT_RELAY_V1.pine` in this repo exactly.
- **Stale duplicate indicator instance removed** from the option chart(s)
  (the leftover `Runtime error` copy from an earlier duplicate-paste
  attempt, called out in the original handoff).
- **All 5 alerts created and active**: 1 `UNDERLYING_HEARTBEAT` (AMC) + 4
  `OPTION_HEARTBEAT` (one per held contract), all on 1-minute charts,
  webhook pointed at the production URL, condition "Any alert() function
  call," no custom message.

## A real bug caught and fixed before it could bite

The first pass at the 4 option alerts was wrong: TradingView freezes an
indicator's *current input values* into an alert at the moment
**Create Alert** is clicked — those inputs live on the indicator's own
Settings → Inputs panel, not in the alert-creation dialog itself, and are
easy to miss. All 4 option alerts were created before the Relay type
input was switched from its default `UNDERLYING_HEARTBEAT` to
`OPTION_HEARTBEAT`, so they baked in `(UNDERLYING_HEARTBEAT, AMC, , )`
instead of the real `(OPTION_HEARTBEAT, AMC, <position_ref>,
<instrument_ref>)`. Confirmed by clicking into the alert's full title
text (visible in the Alerts list) — the empty refs were the tell. Since
`optionFields` only gets included in the emitted JSON when
`relayType == "OPTION_HEARTBEAT"`, these would have pinged the backend as
extra (unwanted) underlying heartbeats forever, and
`BLOCKED_NO_FRESH_OPTION_HEARTBEAT:*` would never have cleared no matter
how long the market was open — a silent, permanent block that wouldn't
have thrown an error anywhere.

Fix applied: for each of the 4 option contracts, set the indicator's
Inputs (Relay type = `OPTION_HEARTBEAT`, Position ref, Instrument ref —
see table in the original handoff) *first*, confirm with OK, *then*
create the alert. Deleted the 4 broken alerts. Re-verified all 4 new
alerts by opening their full title text and confirming real numbers
appear, e.g. `(OPTION_HEARTBEAT, AMC, 7, 9)` — no blanks.

**If anyone touches these alerts again**: this failure mode (input values
frozen wrong at creation time, invisible from the Edit-alert dialog
afterward) is easy to reintroduce. Always confirm the indicator's
Settings → Inputs are correct *before* clicking Create Alert, and always
spot-check by clicking the alert's full title afterward rather than
trusting the alert-list summary (which truncates).

## Current `/paper/health` (2026-08-15, ~05:26 America/New_York, Saturday)

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

This is the **correct resting state** — market is closed for the weekend,
so no confirmed 1-minute bar can exist yet regardless of alert
correctness. Not a fault; nothing further to do until the next live
session.

## Next live session checklist

Same as the original handoff's "Activation verification" section:
1. Confirm Railway receives the underlying heartbeat and all 4 option
   heartbeats (check `/paper/health` blockers clearing one by one).
2. Expect `authoritative_provider_ready=true`, an experiment
   atomically created/activated, `runner_ready=true` subject to other
   safety gates.
3. Confirm the dashboard shows the active challenge.
4. Never synthesize a heartbeat or substitute Massive delayed bars to
   clear a gate.

## Tooling note (not project-relevant, but worth recording)

Browser automation against TradingView's multi-panel "AMC 6TF" layout was
unreliable this session (unresponsive clicks, broken partial renders).
Root cause found: **TradingView enforces one active session per account**
per market-data regulation — every time the user's own real browser
touched TradingView, it silently disconnected the automated session
(and vice versa), which looked exactly like random tool instability
until a "Session disconnected" modal surfaced it. The actual alert
creation and the input-value bug fix above were done by the user
directly in their own TradingView session, following exact configuration
values and step-by-step instructions relayed in chat.
