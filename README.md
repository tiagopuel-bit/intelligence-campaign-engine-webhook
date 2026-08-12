# DNA TradingView Webhook — Campaign Intelligence Engine

Flask receiver for TradingView alerts from the DNA/CIF Pine script.
Stores alert history in a persistent SQLite database on Railway and exposes
campaign state to `decision_engine.py` and `poll_and_recommend.py`.

No trades are placed. Read-only, informational. Cloud-hosted on Railway.

## Files

| File | Purpose |
|------|---------|
| `webhook_receiver.py` | Flask app — receives alerts, stores history, tracks signal watch state |
| `decision_engine.py` | Position-aware recommendation engine |
| `poll_and_recommend.py` | Polls receiver state and runs single-TF + multi-TF recommendations |
| `requirements.txt` | Python runtime dependencies |
| `railway.json` | Railway deployment config |
| `tests/test_webhook.py` | 41 automated tests (unittest) |

## Public endpoint

```
https://dna-tradingview-webhook-production.up.railway.app
```

## TradingView alert configuration

- **Alert type:** "Any alert() function call"
- **Webhook URL:** `https://dna-tradingview-webhook-production.up.railway.app/webhook`
- **No secret field required.** Authentication is by TradingView's source IP.

The Pine script's existing `alert()` JSON message works unchanged. No `secret`
field, no custom message, no credential in the URL.

Each timeframe needs its own TradingView alert instance if separate timeframe
state is desired.

## Authentication

### POST /webhook (alerts)

TradingView alerts are authenticated by source IP. The receiver checks
`X-Real-IP` (set by Railway's edge) against the official TradingView webhook
sender IPs:

```
52.89.214.238, 34.212.75.30, 54.218.53.128, 52.32.178.7
```

An optional `WEBHOOK_SECRET` (env var) is available for manual smoke tests
via `X-Webhook-Secret` header or JSON `secret` field. Not used in production.

Configure via `TRADINGVIEW_WEBHOOK_IPS` env var (comma-separated, defaults
to the four IPs above).

### GET /state, /state_all, /history, /export (reads)

Protected by `STATE_API_TOKEN`. Pass it as:

```
Authorization: Bearer <STATE_API_TOKEN>
```

Set via the `STATE_API_TOKEN` env var on Railway.

### GET /health

Public — no authentication required.

## Polling state

### Single-timeframe recommendation

```sh
python3 poll_and_recommend.py AMC --timeframe 5 \
  --receiver https://dna-tradingview-webhook-production.up.railway.app \
  --token $STATE_API_TOKEN
```

### Multi-timeframe synthesis (recommended)

```sh
python3 poll_and_recommend.py AMC \
  --receiver https://dna-tradingview-webhook-production.up.railway.app \
  --token $STATE_API_TOKEN
```

The `--token` flag accepts a token directly or falls back to the
`STATE_API_TOKEN` environment variable. The token is never printed.

## Weekly backup download

Download a complete SQLite backup:

```sh
TOKEN="$(cat /path/to/token/file)"
curl -H "Authorization: Bearer $TOKEN" \
  -o "dna_alerts_$(date +%Y%m%d).db" \
  https://dna-tradingview-webhook-production.up.railway.app/export/db
```

Download alerts as CSV:

```sh
curl -H "Authorization: Bearer $TOKEN" \
  -o "dna_alerts_$(date +%Y%m%d).csv" \
  https://dna-tradingview-webhook-production.up.railway.app/export/csv
```

The laptop is only needed when you manually run these downloads. The
receiver runs 24/7 on Railway, independent of your laptop.

## State and history endpoints

```sh
# Single timeframe state
curl -H "Authorization: Bearer $TOKEN" \
  https://dna-tradingview-webhook-production.up.railway.app/state/AMC/5

# All timeframes for a symbol
curl -H "Authorization: Bearer $TOKEN" \
  https://dna-tradingview-webhook-production.up.railway.app/state_all/AMC

# Recent alert history
curl -H "Authorization: Bearer $TOKEN" \
  https://dna-tradingview-webhook-production.up.railway.app/history/AMC/5
```

## Railway deployment

### Environment variables (set in Railway dashboard)

| Variable | Required | Purpose |
|----------|----------|---------|
| `STATE_API_TOKEN` | Yes | Bearer token for all read endpoints |
| `TRADINGVIEW_WEBHOOK_IPS` | No | Comma-separated IP allowlist (defaults to official 4) |
| `WEBHOOK_SECRET` | No | Optional secret for manual test clients |
| `PORT` | No | Injected by Railway automatically |

### Volume

A Railway volume is attached at `/data`. The database survives redeploys
and restarts. Path: `$RAILWAY_VOLUME_MOUNT_PATH/dna_alerts.db`.

### Deploy from GitHub

```sh
railway up   # or push to the connected GitHub repo for auto-deploy
```

## Running tests

```sh
cd webhook
python3 -m unittest discover -s tests -v
```

All 41 tests use temporary SQLite databases. The import does not touch
any real database.

## Security

- TradingView alerts are authenticated by source IP (no credential in Pine)
- Read endpoints require `STATE_API_TOKEN` (Bearer)
- `/health` is public and reveals no data
- `dna_alerts.db*`, `backups/`, `runtime/`, `.env`, `*.pem`, `*.key` are gitignored
- Do not commit real tokens, secrets, or database files
- No trades are placed — informational only
