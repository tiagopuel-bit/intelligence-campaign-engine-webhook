# Receiver Redeploy Checklist — 2026-08-12

**Situation:** the Railway deployment (`dna-tradingview-webhook-production.up.railway.app`)
is running an **older build** of `webhook_receiver.py` than the local copy. Verified by
probing the live endpoints.

## Live vs. local — endpoint diff

| Endpoint | Local | Deployed | Note |
|---|---|---|---|
| `/webhook` (POST) | ✓ | ✓ | |
| `/health` | ✓ | ✓ (200) | |
| `/state/<symbol>/<tf>` | ✓ | ✓ (200) | |
| `/state_all/<symbol>` | ✓ | ✓ (200) | |
| `/history/<symbol>/<tf>` | ✓ | ✓ (200) | |
| `/export/db` | ✓ | ✓ (200) | |
| `/export/csv` | ✓ | ✓ (200) | |
| **`/assets`** | ✓ (line 377) | **✗ (404)** | **missing on Railway** |

## Data-schema diff (session capture — prepared, not yet deployed)

| Change | File | Deployed? |
|---|---|---|
| `session TEXT` column in `CREATE TABLE alerts` | `webhook_receiver.py` | ✗ |
| `session` + `payload.get("session")` in the INSERT | `webhook_receiver.py` | ✗ |
| Migration `ALTER TABLE alerts ADD COLUMN session TEXT` | `migrations/001_add_session_column.sql` | ✗ |
| `session` in the `/state*` response | `_shape_state()` | ✗ (not yet added — stored but not served) |

Confirmed: the live `/state_all/AMC` response has **no `session` field**, so the session
column has not shipped.

## What to do to finish the "live read" for the landing page

1. **Deploy the current `webhook_receiver.py`** (redeploy via `railway up` / git push) so
   `/assets` and the `session` INSERT ship.
2. **Run the migration once** on the Railway DB so existing rows gain the nullable
   `session` column with no data loss:
   ```sql
   ALTER TABLE alerts ADD COLUMN session TEXT;
   ```
   (Either via a one-off `railway run` command, or a startup guard in the app.)
3. **Decide on `_shape_state()`:** if the coverage matrix should read `session` through
   `/state_all/<symbol>`, add `"session": latest["session"]` to `_shape_state()`. Until
   then `session` is captured but not exposed by the read endpoints.

## Do NOT ship yet (pending)

- `scripts/cleanup_test_symbols.py` (test-symbol removal) — still needs a go before `--apply`.
- The coordinator / anything beyond the read-only landing-page endpoints.
