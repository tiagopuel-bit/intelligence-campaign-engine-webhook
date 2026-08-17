# Follow-up — heartbeat fixes, based on your own live diagnosis

**For:** DeepSeek. Great diagnostic work in
`docs/DEEPSEEK_HEARTBEAT_LIVE_TRACE_TASK.md`'s response — the underlying
flicker (fires constantly, lands ~50%) and the option relay (fires once
in 10 min, should fire every minute) are two separate, correctly
distinguished problems. This packet is the fix step for both, now that
the root causes are understood.

## 1. Underlying heartbeat — switch off the flaky IP-check

Root cause per your own analysis: `_tradingview_ip_authorized()` depends
on a fixed 4-IP allowlist matched against `X-Real-IP`, which is dropping
some fraction of deliveries silently (401, invisible to TradingView).

**Fix path — use the existing secret-based fallback instead of touching
the IP logic:** `_manual_secret_authorized()` (`webhook_receiver.py:353`)
already exists as a fallback auth path, checking a `"secret"` field
against `WEBHOOK_SECRET`. This bypasses the IP allowlist problem entirely
without changing any server-side auth code.

1. **Tiago will check Railway's dashboard for whether `WEBHOOK_SECRET` is
   set** (not your task — he's doing this directly, don't ask him for the
   value in chat).
2. Once he confirms it's set (or sets one), the Pine script
   (`pine_research/DNA_MTF_RELAY_V1.pine`'s heartbeat variant, or whatever
   the actual heartbeat script file is — locate it) needs a `"secret"`
   field added to its JSON payload construction. Tiago will paste the
   actual secret value into the script himself in TradingView — your job
   is to tell him exactly which line to add it to and the exact JSON key
   (`"secret"`), not to know or handle the value.
3. Verify server-side: `_manual_secret_authorized()` reads
   `request.headers.get("X-Webhook-Secret") or payload.get("secret")` —
   confirm the payload-field path works for a heartbeat-shaped payload
   specifically (write a test if one doesn't already cover this exact
   case for `kind=UNDERLYING_HEARTBEAT`/`OPTION_HEARTBEAT` payloads, not
   just the general webhook auth tests).

## 2. Option heartbeats — diagnose per your own third hypothesis

Your read: the Jan 2027 option's own TradingView chart may not be forming
a fresh 1-minute candle every minute (matches the project's known gap —
no real-time option bid/ask; Massive's free options data is EOD-only).
Tiago is checking this visually (watching the option's own 1m chart for
candle formation) — not your task to verify from code, since you can't
see a live TradingView chart. If he confirms the chart isn't updating
live, that's a data-availability limit, not a bug — document it plainly
as a known constraint rather than something to keep debugging.

If the chart *is* updating live but the alert still doesn't fire, the
next things to check (once Tiago confirms live chart data):
- `position_ref`/`instrument_ref` in the script inputs exactly match a
  real, currently-OPEN option instrument from `/positions` (a mismatch
  409s per `webhook_receiver.py:491` — silent to TradingView same as the
  IP-auth case, worth checking the logs for 409s specifically).
- The alert is genuinely on that option's own 1m chart, not the
  underlying's.

## Boundary

This is fix work, not read-only diagnostic — but stay within what's
scoped: the auth fallback wiring and test coverage for it. Do not modify
`TRADINGVIEW_WEBHOOK_IPS` or the IP-check logic itself — the secret-based
fix sidesteps the problem without needing to fix or expand the IP list,
which is the safer change (adding IPs to an allowlist without being
certain of TradingView's actual current egress range risks either still
missing some, or being overly permissive). Full suite + `git diff --check`
clean. No deploy/commit/push — hand back for review, same as tonight.

## What to report back

Which script file needed the `secret` field, the exact line/change, the
new/updated auth test proving the payload-field path works for a
heartbeat payload, and full suite result.
