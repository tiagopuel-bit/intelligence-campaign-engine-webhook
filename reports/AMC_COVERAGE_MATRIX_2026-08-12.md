# AMC Coverage Matrix — 2026-08-12 (live + historical)

**Live source:** `https://dna-tradingview-webhook-production.up.railway.app/state_all/AMC`
(fresh data, timestamps 2026-08-12).
**Historical source:** frozen Massive RTH snapshot + freshly pulled ETH ladder.

## Live (real-time alerts via `/state_all/AMC`) — 8 timeframes

| Timeframe | Status | Phase | Recent event | Health |
|---|---|---|---|---|
| 3m | **MISSING** | — | — | — |
| 5m | LIVE | ACCUMULATION | STRONG START | 99 |
| 15m | LIVE | EXPANSION | ADD | 34 |
| 30m | LIVE | ACCUMULATION | STRONG START | 66 |
| 1H | LIVE | WAIT | — | 84 |
| 2H | LIVE | ACCUMULATION | STRONG START | 69 |
| 3H | LIVE | WAIT | — | 80 |
| 4H | LIVE | WAIT | — | 53 |
| Daily | LIVE | WAIT | — | 92 |
| Weekly | **MISSING** (expected — no bar closed) | — | — | — |

**Gaps to close on the live side:**
1. **3m is not wired** — the TradingView watchlist isn't emitting 3m alerts yet (Track 2).
2. **Weekly** — expected empty until a weekly bar closes/sends.

## Historical (data pipeline) — full coverage

| Timeframe | RTH bars | ETH bars |
|---|---:|---:|
| 3m | 64,830 (auction-folded) | 126,765 |
| 5m | 38,903 | 81,688 |
| 15m | 12,971 | 30,165 |
| 30m | 6,488 | 15,655 |
| 1H | 3,492 | 8,455 |
| 2H | 1,994 | 4,493 |
| 3H | 1,498 | 3,497 |
| 4H | 997 | 2,500 |
| Daily | 501 | n/a (no ETH daily) |
| Weekly | 105 (context-only) | n/a |

Consistency: 3m RTH volume == 5m RTH volume (diff 0.0); ETH RTH slice == frozen RTH snapshot (byte-identical).

## Notes / blockers

- `/assets` is **404 on Railway** — the deployed receiver predates that endpoint. The
  full multi-asset list (beyond AMC) needs the redeploy in `docs/REDEPLOY_CHECKLIST.md`.
- The `session` tag (RTH/PRE/POST) is captured locally but **not yet deployed**; the live
  `/state_all/AMC` has no `session` field, so the RTH/ETH split on stored alerts is still
  pending that deployment + migration.
- Source provenance (watchlist vs manual) is still not derivable — no `source` column exists.
