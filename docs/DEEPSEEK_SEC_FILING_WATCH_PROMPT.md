# DeepSeek Task — Cloud SEC Filing Watch for DNA Catalyst Watch

## Objective

Build a production-safe, cloud-only SEC EDGAR filing watcher for the DNA Asset Page. It must detect newly disseminated AMC filings and surface them inside the existing Catalyst Watch without anything running on the user's laptop.

Target forms:

- Dilution / financing watch: `424B5`, `S-3`, `FWP`
- Material company filings: `8-K`, `10-Q`, `10-K`
- Insider ownership filings: `3`, `4`, `5`

Preserve the raw SEC form. Treat amendments or related variants (`/A`, `S-3ASR`) as explicitly labeled variants, not silently as the exact base form.

## Non-negotiable boundaries

- Railway + GitHub + the existing persistent SQLite volume only. No laptop daemon, LaunchAgent, ngrok, local JSON state, yfinance, broker connection, or TradingView change.
- Advisory flags only. Do not place trades, send orders, change Pine, change DNA signal definitions, or create entry/exit alerts.
- Do not call every filing bearish. Forms `3/4/5` are ownership disclosures; without parsing transaction codes, they are context only—not automatically buying or selling.
- Do not call an `S-3` immediate dilution. It is registration/financing capacity. `424B5`/`FWP` can be more immediate offering evidence, but the UI must still describe the actual form rather than inventing transaction terms.
- Never use `contact@example.com` or another fake SEC identity. Require a Railway environment variable such as `SEC_USER_AGENT="DNA Campaign Engine admin-contact@real-domain"`. If it is absent, return an honest configuration error and do not call SEC.
- Respect SEC fair-access rules. Fetch only the AMC submissions JSON needed, cache it, default polling no faster than every 300 seconds, use timeouts, and never approach 10 requests/second.
- First run must seed silently. Existing historical filings must not appear as new alerts.
- Newness must persist across redeploys and must not be consumed by the first browser that reads it.
- No secrets in source, logs, tests, reports, commits, or screenshots.
- Preserve all unrelated work and the untracked `docs/DEEPSEEK_LIGHTWEIGHT_CHARTS_UPGRADE_PROMPT.md`.
- Do not push or deploy until the final checkpoint is reviewed.

## Authoritative SEC source

- AMC CIK: `0001411579`
- Submissions endpoint: `https://data.sec.gov/submissions/CIK0001411579.json`
- Filing document URLs must be constructed only from SEC-returned accession/document fields and must use `https://www.sec.gov/Archives/edgar/data/...`.
- Use a declared `User-Agent`, `Accept-Encoding: gzip, deflate`, and an explicit timeout.

The SEC says the submissions JSON is updated throughout the day as filings are disseminated and typically contains at least one year or 1,000 recent filings. Do not scrape HTML search pages.

## Required architecture

### 1. Isolated SEC module

Create a small module such as `sec_filings.py` that owns:

- watched-form constants and severity/category mapping;
- SEC request and response normalization;
- safe accession/document URL construction;
- exact-form and variant matching;
- SQLite initialization/upsert/query helpers;
- one deterministic `poll_symbol(...)` function that can be tested with a mocked SEC response;
- a result contract separating `seeded`, `new_filings`, `recent_filings`, `errors`, and timestamps.

Do not embed all logic directly in `webhook_receiver.py`.

### 2. Persistent SQLite tables

Add idempotent schema creation to the existing database startup. Suggested fields:

`sec_filing_watch_state`

- `symbol` primary key
- `cik`
- `seeded_at`
- `last_polled_at`
- `last_success_at`
- `last_error`

`sec_filings`

- `accession` primary key
- `symbol`, `cik`, `form`, `base_form`, `filing_date`, `acceptance_time`
- `primary_document`, `filing_url`
- `category` (`DILUTION_WATCH`, `MATERIAL_FILING`, `INSIDER_FILING`)
- `severity` (`HIGH`, `MEDIUM`, `INFO`)
- `first_seen_at`
- `seed_record` boolean

Use accession number as the durable identity. Upserts must be idempotent and concurrency-safe. The Railway volume at `/data` remains authoritative.

Do not add a global `seen_accessions` JSON blob.

### 3. Polling command suitable for Railway

Create `scripts/poll_sec_filings.py` with:

- `--symbol AMC` default;
- `--once` deterministic one-shot mode;
- nonzero exit on configuration or upstream failure;
- concise JSON output with counts, never secrets;
- database path resolved through the existing `DATABASE_PATH` / `RAILWAY_VOLUME_MOUNT_PATH` contract;
- no infinite loop required for production scheduling.

Document the exact Railway cron/service command and recommended five-minute cadence, but do not mutate Railway services or deploy at this checkpoint. If Railway's current free plan cannot schedule it, report that honestly and provide the smallest cloud-only fallback. Do not propose a laptop poller.

### 4. Authenticated API

Add an authenticated read endpoint:

`GET /filings/<symbol>`

Requirements:

- use existing `STATE_API_TOKEN` auth;
- initially support only mapped/validated symbols (AMC required);
- return recent watched filings and filings first seen within a bounded alert window (default 72 hours, configurable by validated query parameter);
- expose `configured`, `seeded`, `last_polled_at`, `last_success_at`, `stale`, and a sanitized error status;
- reading must not acknowledge or consume an alert;
- never make a synchronous SEC request from the browser endpoint;
- stable JSON schema documented in the handoff.

Optional admin-only poll endpoint is not desired. The scheduled command is the writer; the Flask endpoint is read-only.

### 5. Dashboard integration

Extend the existing Asset Page without redesigning it:

- Catalyst Watch must request `/filings/AMC` alongside `/news/AMC`.
- Add a dedicated `SEC filings` item or replace the generic catalyst headline when an SEC event has greater authority.
- Priority order:
  1. new `424B5` / `FWP` -> high-attention dilution/offering flag;
  2. new `S-3` or variant -> financing-capacity watch, not claimed immediate dilution;
  3. new `8-K` / `10-Q` / `10-K` -> material filing flag;
  4. new `3` / `4` / `5` -> ownership filing, direction unclassified unless real transaction parsing is later added.
- Show form, filing date/time, plain-language bounded label, and direct SEC link.
- Combine SEC event with the existing volume, premium-compression, and DNA technical-response evidence. SEC alone can activate `CATALYST RISK` for offering forms, but it must not produce an entry/exit instruction.
- Distinguish clearly among `NEW`, `recent`, `seed history`, `stale`, `not configured`, and `upstream unavailable`.
- Escape all text and allow only `https://www.sec.gov/` filing links.

### 6. Tests

Add deterministic tests covering at minimum:

1. Missing `SEC_USER_AGENT` makes no outbound request and returns a configuration error.
2. First poll silently seeds all existing watched accessions.
3. Second identical poll produces zero new filings.
4. One new filing produces exactly one durable new record.
5. Redeploy/re-init against the same DB does not repeat the alert.
6. Concurrent/idempotent upsert cannot duplicate an accession.
7. All target form categories and severities are table-tested.
8. Amendments/variants preserve raw form and are labeled honestly.
9. Unwatched forms are ignored.
10. Malformed columnar SEC arrays fail safely.
11. SEC timeout/HTTP/JSON failure preserves prior successful state and records a sanitized error.
12. API requires state auth and validates symbol/window.
13. API reads only SQLite and never calls SEC.
14. Filing URL construction rejects unsafe/non-SEC document paths.
15. Dashboard static checks prove `/filings/`, SEC status handling, and advisory-only wording.
16. Existing webhook/dashboard/position/news tests remain green.

Mock every SEC request in unit tests. No live network dependency in the test suite.

## Checkpoint discipline

### Checkpoint 1 — design and fixtures

Before production edits, report:

- exact schema and API response contract;
- form/category/severity table;
- first-run and redeploy semantics;
- Railway scheduling plan and any free-plan limitation;
- SEC fixture shape and planned tests.

Then continue to implementation unless a real blocker exists.

### Checkpoint 2 — implementation and verification

Run:

```bash
PYTHONPYCACHEPREFIX=/tmp/dna_sec_watch_pycache python3 -m unittest discover -s tests -v
git diff --check
```

Also extract the dashboard inline JavaScript and run `node --check` using the bundled Codex Node runtime if system Node is unavailable.

Report:

1. exact commands and test counts;
2. seeded/new/redeploy behavior demonstrated with fixtures;
3. endpoint examples for unconfigured, seeded/no-new, and new-filing states;
4. dashboard flag examples for each category;
5. changed files and diff summary;
6. secret scan result;
7. production/runtime files intentionally untouched;
8. any Railway environment variable or scheduling action still required.

Stop before commit, push, Railway service changes, or deployment.

## Explicitly out of scope

- yfinance/share-count monitoring in this task;
- parsing Form 4 transaction codes or claiming insider buy/sell direction;
- email/SMS/push notifications;
- brokerage integration;
- trading automation;
- Pine/DNA engine changes;
- research/backtesting changes;
- polling every tracked asset before the AMC implementation is proven.

