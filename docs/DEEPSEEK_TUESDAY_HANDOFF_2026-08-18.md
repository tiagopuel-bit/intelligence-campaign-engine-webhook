# Handoff — DS picks this up today (2026-08-17 evening) to get AMC running tomorrow (2026-08-18)

**From:** Claude, 2026-08-17 evening. **For:** DeepSeek.

## Where things stand right now

- Tiago reset all 5 TradingView alerts himself this afternoon (1
  `UNDERLYING_HEARTBEAT` + 4 `OPTION_HEARTBEAT`, same position/instrument
  refs as before). He's checking Railway directly right now for the item
  below — don't duplicate that unless he asks.
- **Production is 502ing.** `GET /health` and `GET /paper/health` both
  returned `{"status":"error","code":502,"message":"Application failed to
  respond"}` as of ~this evening (checked repeatedly over several minutes,
  not a one-off blip). Tiago is looking at the Railway dashboard himself.
  If he asks you to check logs/DB over SSH, do that; otherwise don't touch
  deploy/infra — just note whether it's still down when you start and
  report current status in your log entry.
- This morning's live diagnostic (`docs/DEEPSEEK_HEARTBEAT_LIVE_TRACE_TASK.md`
  → `docs/DEEPSEEK_HEARTBEAT_FIX_TASK.md`) found two distinct root causes:
  1. **Underlying heartbeat**: `_tradingview_ip_authorized()`'s fixed 4-IP
     allowlist was silently dropping ~50% of deliveries (401, invisible to
     TradingView). Fix path: use the existing `_manual_secret_authorized()`
     fallback (`webhook_receiver.py:353`, reads `X-Webhook-Secret` header or
     `payload["secret"]` against `WEBHOOK_SECRET`) instead of touching IP
     logic. **This code path already exists and is unchanged/working** — I
     verified it's still in place (`webhook_receiver.py:576`,
     `elif _manual_secret_authorized(payload):`). What's still open: whether
     Tiago actually added a `"secret"` field to the Pine heartbeat script,
     and **the dedicated test proving the payload-field path works for a
     `kind=UNDERLYING_HEARTBEAT`/`OPTION_HEARTBEAT` payload specifically**
     (requirement #3 of the fix task) — I checked `tests/test_webhook.py`
     and this test was not added (the only pending diff there is unrelated,
     a partial-option-close test). **This is your first concrete task.**
  2. **Option heartbeats**: firing ~once per 10 min instead of every minute.
     Working hypothesis is the option's own 1m TradingView chart isn't
     forming live candles (Massive's options data is EOD-only — a known
     project constraint, not a bug). Tiago was going to confirm this
     visually; don't re-diagnose from code, just ask him for the visual
     confirmation result if you need it for your log entry, or note it as
     unconfirmed if he hasn't said.

## What you can do today (useful with or without Railway being back up)

1. **Add the missing auth test** (read/write to `tests/test_webhook.py`,
   no server/schema changes): a test that posts a `kind="UNDERLYING_HEARTBEAT"`
   (and one for `OPTION_HEARTBEAT`) payload to `/webhook` with **no** IP
   match but a correct `"secret"` field matching `WEBHOOK_SECRET`, and
   asserts 200 + the heartbeat actually lands in the right table
   (`underlying_heartbeats` / `option_heartbeats`) — not just that auth
   passes. Also assert a wrong/missing secret + no IP match still 401s.
   Full suite (currently 471 passing) + `git diff --check` clean when done.
2. **If Railway is back up by the time you check**: confirm `GET
   /paper/health` — report the exact JSON (blockers, `authoritative_
   provider_ready`, `runner_ready`) so we know if today's alert reset
   already cleared anything, or if it's still closed-market/no-heartbeat as
   expected this late in the day.
3. **If Railway is still down**: this is a stop-and-report item, not
   something to fix — infra/deploy is out of scope for you per the standing
   boundary. Just note it clearly in your log entry with timestamp so
   Claude has it fresh in the morning.
4. Log whatever you find/do to `docs/PAPER_TRADE_DESK_LOG.md` in the
   file's existing format — that's the single place all three of us pick
   up context from cold.

## Tomorrow morning (2026-08-18)

Claude is covering the market-open activation watch tomorrow morning
(reversal of today's coverage) — poll `/paper/health` from ~9:30am ET,
watch the blockers clear in order, confirm `authoritative_provider_ready`
and `runner_ready` flip as expected. You don't need to cover that unless
Railway is still down when Claude checks in, in which case flag it loudly
in the log tonight so it's the first thing addressed.

## Boundary (same as every task this week)

No schema/gate/threshold changes. No touching `TRADINGVIEW_WEBHOOK_IPS` or
IP-check logic. No deploy/commit/push — hand back for review. No
approving/rejecting proposals, no kill-switch. If Railway is down, that's
report-only, not yours to fix.

## What to report back

1. Auth test added — file/line, and confirmation it actually exercises the
   payload-field path (not just header-based auth, since the Pine script
   uses the JSON field).
2. Full suite result + `git diff --check` result.
3. Current `/paper/health` status (or confirmation it's still 502ing) with
   timestamp.
4. Whether Tiago confirmed the option-chart live-candle question, if you
   have it.
