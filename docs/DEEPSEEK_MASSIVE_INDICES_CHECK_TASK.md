# Quick check — verify Massive Indices access from the live Railway environment

**For:** DeepSeek. Small, fast, read-only. Unblocks the VIX vol-regime spec.

## Why

Tiago just enabled "Indices Basic" (free, $0/mo) on his Massive account.
Need to confirm the actual `MASSIVE_API_KEY` deployed on Railway can reach
it. Local testing was inconclusive — the local `runtime/.env` copy of the
key is stale and fails even on ordinary stock queries, so it proves
nothing either way. Test needs to run where the real key lives.

## What to check

SSH into the Railway service (same access as tonight's other tasks) and
run, using the actual deployed `MASSIVE_API_KEY`:

```bash
curl -s "https://api.massive.com/v2/aggs/ticker/I:VIX/range/1/day/2026-08-10/2026-08-16?adjusted=true&sort=asc&limit=50000&apiKey=$MASSIVE_API_KEY"
```

Report the exact response:
- `200` with real OHLC bars → Indices access confirmed, VIX spec is
  unblocked.
- `401`/`403` with an error message → report the exact error text (e.g.,
  "Unknown API Key" vs. a plan/entitlement-specific message — these mean
  different things: the former suggests a key problem, the latter
  suggests the product isn't actually enabled on the key yet even though
  Tiago enabled it in the dashboard, possibly a propagation delay).
- Also sanity-check the same key against a known-good stock ticker (e.g.
  AMC) in the same call style, so we know whether any failure is
  Indices-specific or a broader key issue.

## Boundary

Read-only. No code changes, no writes. Just report the raw result.
