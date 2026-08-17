# Urgent — trace why underlying heartbeats aren't landing despite firing

**For:** DeepSeek, right now, market open. Read-only, live diagnostic.

## The discrepancy

Tiago confirms TradingView is firing the "DNA Price Heartbeat Relay v1"
alert on AMC repeatedly (visually confirmed, multiple pop-ups). But
`/paper/health` shows `BLOCKED_NO_FRESH_UNDERLYING_HEARTBEAT` again after
one brief clear. This means TradingView-side firing isn't the problem
anymore — something between the webhook delivery and the DB write is
failing for most (not all — one got through) of these fires.

## What to check, live, on the Railway service (SSH, same access as tonight)

1. **Tail the live server logs** while alerts are firing (Tiago says
   they're currently coming in) — Railway's log stream or however you can
   watch stdout/stderr in real time. Look for:
   - Any `/webhook` requests arriving at all in the last few minutes.
   - Any 400/401/500 responses, or logged exceptions, specifically around
     heartbeat payloads.
2. **Query the DB directly** for the actual row history, not just the
   latest:
   ```sql
   SELECT bar_time, close, received_at FROM underlying_heartbeats
   WHERE symbol='AMC' ORDER BY bar_time DESC LIMIT 10;
   ```
   Does this show one row (matches "fired once, then stopped") or several
   rows with gaps (matches "landing intermittently")? The exact pattern
   changes the diagnosis.
3. **Check `webhook_is_authorized()`** — `_tradingview_ip_authorized()`
   vs `_manual_secret_authorized(payload)`. The heartbeat payload Tiago
   shared has no `"secret"` field, so it must be passing on the
   TradingView-IP check. If TradingView's outbound webhook IP ever
   changes or the request doesn't match the expected IP range for some
   deliveries, those specific requests would get silently 401'd with no
   visible error on Tiago's end (TradingView doesn't surface webhook HTTP
   response codes to the user in the alert popup). Check whether
   `_tradingview_ip_authorized()`'s IP list/logic could be flaky —
   report exactly what it checks.
4. **Look for a pattern by timestamp** — do successful deliveries cluster
   in a way that suggests a specific window, a restart, or something
   Railway-side (like a cold start dropping requests during a redeploy)?

## Boundary

Read-only. No code/config changes without reporting back first — if you
find the actual bug (e.g., the IP-auth check is wrong), report exactly
what's wrong and wait before fixing, since this touches the live
authorization path for the production webhook and Tiago wants to
understand the actual cause before anything changes.

## What to report back

The real log/DB evidence — not a guess. Specifically: how many
`/webhook` requests with `kind=UNDERLYING_HEARTBEAT` actually arrived
in the last 10-15 minutes, how many succeeded vs failed and why (exact
error/status code), and the row history from the query above.
