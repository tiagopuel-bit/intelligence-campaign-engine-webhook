# AMC Paper Execution — API and Runner (P2)

`PAPER_ONLY`. All mutations require `Authorization: Bearer <STATE_API_TOKEN>`.
Clients submit intent only; `very_high`, evidence roots, freshness, price source
and policy eligibility are reconstructed server-side from authoritative state
and cannot be overridden by the client. Position-changing intent identifies
the exact `position_ref` and `instrument_ref`; the server verifies both and
never selects an arbitrary open holding.

## Endpoints

| method | path | auth | purpose |
|---|---|---|---|
| GET | `/paper/health` | public | aggregate readiness (no secrets) |
| GET | `/paper/experiments/<id>` | bearer | read one experiment |
| POST | `/paper/proposals` | bearer | create a proposal (server-side eligibility) |
| GET | `/paper/proposals` | bearer | list proposals |
| GET | `/paper/proposals/<id>` | bearer | read one proposal |
| POST | `/paper/proposals/<id>/approve` | bearer | approve |
| POST | `/paper/proposals/<id>/reject` | bearer | reject |
| POST | `/paper/proposals/<id>/cancel` | bearer | cancel |
| POST | `/paper/proposals/<id>/modify` | bearer | new version, original preserved |
| GET | `/paper/reports` | bearer | daily reports |

## Synthetic examples

```bash
TOKEN="<STATE_API_TOKEN>"
BASE="https://dna-tradingview-webhook-production.up.railway.app"

# health (public)
curl -s "$BASE/paper/health"

# create a proposal (client sends intent only)
curl -s -X POST "$BASE/paper/proposals" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"close","symbol":"AMC","experiment_id":1,"position_ref":"7","instrument_ref":"11","idempotency_key":"close-001"}'

# list
curl -s "$BASE/paper/proposals" -H "Authorization: Bearer $TOKEN"

# approve (CAS on PENDING_APPROVAL)
curl -s -X POST "$BASE/paper/proposals/1/approve" -H "Authorization: Bearer $TOKEN"

# modify -> new version, original preserved and cancelled
curl -s -X POST "$BASE/paper/proposals/1/modify" \
  -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" \
  -d '{"action":"partial_reduce","position_ref":"7","instrument_ref":"11","idempotency_key":"close-001-v2"}'
```

A client that attempts to inject `very_high`, `evidence`, `freshness`,
`price_source`, `price_reference`, `policy_*`, or `mode` receives `400` with the
offending field names.

## Railway runner

Scheduled command (documented, not created/deployed here):

```bash
python scripts/run_paper_once.py --db /data/paper.db
```

Recommended cadence: every five minutes. The runner uses the independently
gated atomic claim and fresh revalidation; without a verified live AMC/option
heartbeat it cancels proposals honestly (`NO_AUTHORITATIVE_STATE` /
`CANCELLED_REVALIDATION`) and never substitutes a delayed Massive close.

`GET /paper/health` reports `active_experiment_id`,
`authoritative_provider_ready`, `runner_ready`, and machine-readable
`blockers`. Readiness remains false until distinct underlying-heartbeat and
live-contract relay tables are present; event alerts are not treated as a
heartbeat. Orders, fills, lifecycle completion, execution provenance, and the
isolated paper cash/position ledger commit as one transaction.
