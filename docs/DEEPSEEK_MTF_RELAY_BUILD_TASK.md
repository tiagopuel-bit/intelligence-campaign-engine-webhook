# Task packet — DNA MTF Webhook Relay (build)

**Requested by:** Tiago, 2026-08-16. **For:** DeepSeek. Build authorized —
this is not spec-then-build, the engineering approach is already specified
in `docs/TRADINGVIEW_ALERT_CAPACITY_PLAN.md` ("Preferred engineering
solution" section). Read that doc in full before starting; this packet
narrows scope and sets boundaries, it doesn't replace it.

## Why now

Tracked-asset capacity is effectively maxed: 9 assets × 10 timeframes ≈ 90
of TradingView Plus's 100 technical-alert slots already used. Tiago found
two live candidates worth deep-diving today (ARB, MARA — see chart reads in
this session) and wants headroom to track more assets going forward, not
just these two. The relay is what unlocks that: one alert per asset instead
of one alert per timeframe, collapsing ~90 alerts to ~9 and freeing room to
add assets without hitting the ceiling again.

## What to build

Per the plan doc's spec exactly:

1. **Pine side**: a relay script/alert that fires once per asset and pulls
   the other tracked timeframes via `request.security()` (or the
   equivalent multiway construct) instead of relying on one alert per
   timeframe. Every emitted webhook payload must retain: source timeframe,
   event identity, bar timestamp, and price — `webhook_receiver.py` depends
   on all four to store independent per-timeframe state correctly.
2. **Ingestion side**: whatever `webhook_receiver.py` changes are needed to
   accept and correctly attribute relay payloads carrying multiple
   timeframes' worth of events per delivery, without breaking how existing
   native per-timeframe alerts are ingested.
3. **Validation harness**: a way to run the relay's output side-by-side
   against AMC's existing native per-timeframe alerts and compare, per the
   plan doc's five points — event type/priority, signal-bar and decision
   timestamps, price and DNA fields, dedup/bar-close behavior, and behavior
   across sessions and higher-timeframe boundaries. This comparison is what
   determines "acceptable parity," not a code review.

## Hard boundaries — read before touching anything

- **Do not modify, disable, or replace any existing production TradingView
  alert.** AMC's native per-timeframe alerts keep running unchanged
  throughout this task. The relay runs *alongside* them for comparison —
  this is explicit in the plan doc ("Do not replace the production alerts
  immediately... Only retire native alerts after the relay demonstrates
  acceptable parity").
- **You cannot deploy or activate anything on TradingView's platform** —
  Pine script publishing/alert creation happens in TradingView's UI, which
  is Tiago's action alone. Your deliverable is the Pine script source,
  webhook_receiver.py changes, and the validation harness/report — not a
  live alert. Say explicitly in your report which parts still need Tiago
  to manually create/activate in TradingView.
- **No `paper_execution` changes.** This is data-ingestion plumbing, not a
  trading-logic change — don't touch anything under `paper_execution/`.
- **No changes to alert content/thresholds for existing assets.** The
  relay must reproduce what native alerts already say, not improve or
  change the DNA logic itself.
- **Respect the alert-storm safety limit** already documented (TradingView
  kills a script's alerts if it fires >15 times in 3 minutes) — design
  around it explicitly, don't discover it in production.
- **Full suite + `git diff --check` clean before reporting done.** No
  deploy/commit/push — hand back for review, same as every task.

## What to report back

- The Pine script source and exactly what Tiago needs to do manually in
  TradingView to activate it (new alert config, symbol/timeframe scope).
- The `webhook_receiver.py` diff and how it distinguishes relay payloads
  from native ones (or unifies them — your call, document which).
- The comparison harness and, if you can run it against any available
  historical/replay data, the actual parity results per the plan doc's
  five comparison points. If live side-by-side isn't possible without
  Tiago activating the TradingView alert first, say so plainly and report
  what's ready for him to switch on.
