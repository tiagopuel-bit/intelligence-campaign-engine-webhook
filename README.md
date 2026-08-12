# DNA TradingView Webhook — Campaign Intelligence Engine

Flask receiver for TradingView alerts from the DNA/CIF Pine script.
Stores alert history in SQLite and exposes campaign state to `decision_engine.py`
and `poll_and_recommend.py`.

No trades are placed. Read-only, informational.

## Files

| File | Purpose |
|------|---------|
| `webhook_receiver.py` | Flask app — receives alerts, stores history, tracks signal watch state |
| `decision_engine.py` | Position-aware recommendation engine |
| `poll_and_recommend.py` | Polls receiver state and runs single-TF + multi-TF recommendations |
| `requirements.txt` | Python runtime dependencies |
| `railway.json` | Railway deployment config |
| `tests/test_webhook.py` | Automated test suite |

## Railway deployment (recommended — always-on)

### Prerequisites

- A Railway account with the CLI installed (`brew install railway` or `npm i -g @railway/cli`)
- A Railway project linked to this directory

### Deploy

```sh
cd webhook
railway up
```

### Required environment variables (set in Railway dashboard)

| Variable | Purpose |
|----------|---------|
| `WEBHOOK_SECRET` | Authenticates incoming webhook calls |
| `PORT` | Injected by Railway automatically — do not set manually |

### Required volume

Attach one Railway volume mounted at `/data`. The app stores `dna_alerts.db` at `$RAILWAY_VOLUME_MOUNT_PATH/dna_alerts.db`.

### Health check

```
GET /health  →  {"status": "ok"}
```

### TradingView alert configuration

- Alert type: "Any alert() function call"
- Webhook URL: `https://<your-railway-domain>/webhook`

The alert message must include a `secret` field matching `WEBHOOK_SECRET`:

```json
{
  "secret": "<same as WEBHOOK_SECRET>",
  "symbol": "{{ticker}}",
  "timeframe": "{{interval}}",
  "close": {{close}}
}
```

Keep all existing DNA/CIF fields in the actual message; the snippet only shows the authentication field.

Each TradingView timeframe needs its own alert instance if separate timeframe state is desired.

For non-TradingView clients, the secret may alternatively be sent as the `X-Webhook-Secret` header.

## Local development (ngrok tunnel)

If you need a local receiver with a public tunnel for testing:

### Start the receiver

```sh
cd webhook
python3 webhook_receiver.py
```

The receiver listens on port 5000 by default, or `$PORT` if set.

### Start the tunnel

```sh
ngrok http 5000
```

### Find the current public URL

```sh
curl -s http://localhost:4040/api/tunnels | python3 -c "import sys, json; d = json.load(sys.stdin); print(d['tunnels'][0]['public_url'] + '/webhook')"
```

Free ngrok URLs change after each restart.

### Stop the receiver and tunnel

```sh
# Find and stop the receiver
lsof -i :5000
kill <pid>

# Stop ngrok
pkill ngrok
```

## Polling state

### Single-timeframe recommendation

```sh
cd webhook
python3 poll_and_recommend.py <SYMBOL> --timeframe 240
```

### Multi-timeframe synthesis (recommended)

```sh
cd webhook
python3 poll_and_recommend.py <SYMBOL>
```

### Custom receiver URL

```sh
python3 poll_and_recommend.py <SYMBOL> --receiver https://your-railway-domain
```

## State and history endpoints

```sh
curl http://localhost:5000/state/<SYMBOL>/<TIMEFRAME>
curl http://localhost:5000/state_all/<SYMBOL>
curl http://localhost:5000/history/<SYMBOL>/<TIMEFRAME>
curl http://localhost:5000/health
```

## Running tests

```sh
cd webhook
python3 -m unittest discover -s tests -v
```

## Security

- `WEBHOOK_SECRET` is required in production (Railway)
- Locally without `RAILWAY_ENVIRONMENT`, auth is optional
- `dtrailing_alerts.db` and its sidecars are gitignored
- Do not commit real tokens or secrets
- No trades are placed — informational only
