# DNA Asset Page — DeepSeek / Claude Handoff (2026-08-14)

## Current status

The approved Asset Page is implemented in `ui/dna_dashboard.html` and reads live Railway data through the existing authenticated API. The layout is no longer a static mockup.

Current live sections:

- Portfolio Campaign Radar (top of page; asset selector)
- Market Read / Recommended Action / Next Confirmation / Main Risk
- Asset, stock-position, and options-position summary band
- Position Manager with selectable stock and option holdings
- Entry-to-expiration timeline
- Lightweight Charts v5 underlying and option chart
- Timeframe signal ladder
- Action Plan and Why This Matters
- Trade Progression
- Empty News Stream / Media Sources placeholder

The dashboard defaults to AMC when AMC exists in `/assets`.

## Changes in the latest UI pass

1. Position risk and action guidance is now generated for the selected holding, not copied generically across the asset.
   - Shares incorporate entry, holding age, P&L, and the primary live DNA tier.
   - Options additionally incorporate contract type, strike, expiration/DTE, ITM state, and time-decay context.
   - The Position Manager shows concise action bullets beneath the holding-specific risk summary.
2. The entry-to-expiration track now runs green → amber → red and displays `N days left` at the current-time marker.
3. Clicking a different option now forces Option chart mode, clears the old timeframe override, and redraws using that contract's ticker and average entry.
4. Chart draws have a sequence guard so a slow response from the previously selected holding cannot overwrite the current contract chart.
5. Trade Progression is now the left half of a two-column row. The right half is reserved for News Stream / Media Sources and intentionally remains empty until verified sources exist.

## Data contract already available

- `GET /assets`
- `GET /state_all/<symbol>`
- `GET /positions`
- `GET /positions/<position_id>/valuation`
- `GET /ohlc/<symbol>/<timeframe>`
- `GET /options/ohlc/<contract_ticker>/<timeframe>`
- `GET /options/chain/<symbol>`
- Position create/update/close endpoints documented in `docs/UI_HANDOFF.md`

All protected requests use `Authorization: Bearer <STATE_API_TOKEN>`. Do not put the token in source control, documentation, screenshots, prompts, or generated fixtures.

## DeepSeek research task — DNA vocabulary and insight library

Build a research-only vocabulary/decision-copy library for position navigation. Do not change production code, Pine, signals, alerts, database rows, or trading logic.

### Required scope

Create a structured matrix for:

- Instrument: shares, long call, long put, multi-leg option (future-ready)
- Campaign condition: constructive, expanding, repairing, weakening, broken, uncertain
- Selected holding state: profitable/loss, ITM/OTM, new/mature, low/medium/high DTE pressure
- Timeframe relationship: lower-TF weakness contained, weakness propagating, higher-TF intact, multi-TF confirmation, conflicting evidence
- Navigation intent: hold, wait, protect, reduce, close/stand aside, add only after confirmation, consider roll, monitor time decay

For every library item provide:

1. short status label;
2. one-sentence plain-language conclusion;
3. two or three observable evidence bullets;
4. a decision-change condition;
5. prohibited/overconfident wording;
6. exact fields required from the current API;
7. a confidence/evidence-boundary label.

### Research rules

- Separate market structure from contract mechanics. A bullish campaign does not automatically make an expiring option safe.
- Separate evidence from action. Do not claim predicted returns or guaranteed direction.
- Never invent Greeks, IV, quotes, news, or probability. The current free data plan does not provide trustworthy Greeks.
- Prefer established market language where it improves comprehension, but retain the distinctive DNA event vocabulary (Ignition, Reload, Add, Manage, Peak, Fail) when it refers to an actual engine event.
- Identify ambiguous terms and propose one canonical term plus acceptable UI synonyms.
- Test the matrix against representative AMC, SPY, U, GME, LULU, PYPL, RBLX, TSLA, and VALE examples without modifying their stored data.

### Deliverables

- `reports/DNA_POSITION_VOCABULARY_RESEARCH.md`
- `tables/dna_position_insight_library.csv`
- `tables/dna_term_dictionary.csv`
- `tests/` fixtures that prove each rule selects only from supplied facts
- A short integration contract for Claude/GPT describing deterministic inputs and outputs

## DeepSeek chart regression task

Validate the selected-holding chart lifecycle across at least:

- shares → option A → option B → shares;
- cached and uncached OHLC responses;
- rapid switching while requests are still in flight;
- option entry inside and outside available chart history;
- Underlying/Option manual mode toggles after a holding switch.

Acceptance evidence must show that title, ticker, premium series, average-entry line, entry marker, timeframe active state, and status text all belong to the same selected holding. Do not change the data provider or fabricate missing bars.

## Claude implementation task after research

Integrate the approved insight library as a deterministic renderer behind the Position Manager. Preserve the current visual layout and current API shapes. Add tests for every rule family and explicit empty/unknown states. The UI must always show which evidence caused an action suggestion and what condition would change it.

For News Stream, build only the visual/data boundary until a verified source is approved. The empty state is intentional; no scraped or synthetic headlines should appear.

## Safety and scope boundaries

- Advisory navigation only; the dashboard does not place broker orders.
- Manual position records remain the source of truth for holdings.
- No Pine, DNA engine, webhook ingestion, Railway database schema, alert, or research artifact changes unless separately authorized.
- Preserve RAW/HA provenance and reconstructed/live distinctions wherever shown.
- No deployment without explicit user authorization.

## Verification command

```bash
PYTHONPYCACHEPREFIX=/tmp/dna_dashboard_verify python3 -m unittest discover -s tests -v
```

