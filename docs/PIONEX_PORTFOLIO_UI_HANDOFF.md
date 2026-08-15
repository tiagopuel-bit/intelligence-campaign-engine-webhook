# Pionex Portfolio — UI Handoff

## Implementation status

Implemented locally on 2026-08-14. The deployable bridge now lives at
`webhook/pionex_bridge.py`; this replaces the originally proposed `sys.path`
import of the sibling development folder because that folder is outside the
webhook Git/Railway repository. The bridge reads `PIONEX_API_KEY` and
`PIONEX_API_SECRET` from Railway environment variables first and uses the
sibling `Pionex/.env` only as a local-development fallback.

The authenticated `GET /portfolio/pionex` route and the Pionex card above the
Asset list are wired. The response explicitly reports
`scope: "spot_wallet_only"` and `bots_included: false`. Provider exceptions are
mapped to a generic 502 without returning sensitive upstream details.

Before deployment, set both Pionex variables in Railway. Do not copy or commit
the local `.env` file. No deployment is implied by this handoff.

## Goal

Surface the user's **Pionex spot wallet** on the DNA dashboard as a read-only
card, so the portfolio view includes crypto balances alongside the existing
equity/options positions.

## What already exists (do not rebuild)

- Bridge: `Campaing Inteligence Engine/Pionex/pionex_bridge.py` — pure stdlib
  (no new deps). Verified working against the live API.
  - `portfolio_summary()` -> `{ "balances": [...], "total_value_usd": float, "unpriced_coins": [...] }`
  - `get_balances()` -> raw `GET /api/v1/account/balances`
  - `get_tickers()` -> public `GET /api/v1/market/tickers`
  - `load_env()` reads `Pionex/.env` (key/secret). `.env` is already populated.
- Credentials already work (no auth changes needed).

**Important limitation:** Pionex's balance endpoint only returns the *trading*
account — it **excludes bot and earn balances**. Bot positions are NOT exposed
by the API. Do not attempt to show bot P&L; the card is spot wallet only.

## Part 1 — Backend endpoint

File: `webhook/webhook_receiver.py` (Flask). Add one read-only route, gated by
`state_is_authorized()` exactly like `/assets`, `/news/<symbol>`, etc.

```python
@app.route("/portfolio/pionex", methods=["GET"])
def get_pionex_portfolio():
    if not state_is_authorized():
        return jsonify({"error": "unauthorized"}), 401
    try:
        import pionex_bridge
        data = pionex_bridge.portfolio_summary()
        return jsonify({"source": "pionex", **data})
    except Exception as exc:  # noqa: BLE001
        return jsonify({"error": "pionex", "detail": str(exc)}), 502
```

The bridge lives one directory up from `webhook/`, so add its folder to
`sys.path` near the other imports at the top of `webhook_receiver.py`:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "Pionex"))
```

(`pionex_bridge.py` already locates its own `.env` via `Path(__file__).parent`,
so importing it from `webhook_receiver.py` works without any path changes.)

### Endpoint response shape (what the UI will consume)

```json
{
  "source": "pionex",
  "total_value_usd": 81.15,
  "balances": [
    { "coin": "DOGE", "free": 1150.0, "frozen": 0.0, "total": 1150.0,
      "price_usd": 0.069857, "value_usd": 80.34 }
  ],
  "unpriced_coins": []
}
```

- `value_usd` and `price_usd` can be `null` for coins with no resolvable USDT pair.
- `balances` is pre-sorted descending by `value_usd`.
- `total_value_usd` is rounded to 2 decimals.

## Part 2 — UI card

File: `webhook/ui/dna_dashboard.html` (single-file IIFE, vanilla JS, no build).

### 2a. Where to render

The landing view is `renderAssetList()` (the accordion list). The legacy
`renderPortfolioStrip()` is defined but not currently called. Add the Pionex
card **above the asset list** — insert its HTML at the top of `renderAssetList()`'s
return, before the `'<div class="stage-head">…Assets…</div>'` block, or as its
own `stage-head` section right after the strip if you re-wire the strip.

Keep it a self-contained panel so it also works on the `renderApprovedAsset()`
view if desired, but the minimum is the list view.

### 2b. Static markup (rendered synchronously, then filled async)

Use a `data-role="pionex"` container so an async loader can populate it after
`paint()`, matching the existing `loadNewsStream()` pattern (which queries
`.dna-news[data-sym]` after `app.innerHTML` is set):

```html
<section class="dna-panel pionex-wallet" data-role="pionex">
  <div class="stage-head"><h2>Pionex wallet</h2><span class="hint">spot · read-only · bots excluded</span></div>
  <div class="pionex-body">Loading…</div>
</section>
```

### 2c. Loader function (add near `loadNewsStream()`)

```js
function loadPionex() {
  var el = document.querySelector('[data-role="pionex"]');
  if (!el) return;
  var base = baseInput.value.trim().replace(/\/$/, "");
  fetch(base + "/portfolio/pionex", { headers: authHeaders() })
    .then(function (r) { return r.ok ? r.json() : null; })
    .catch(function () { return null; })
    .then(function (d) {
      var body = el.querySelector(".pionex-body");
      if (!d || !d.balances) {
        body.innerHTML = '<div class="dna-news-empty">Pionex wallet unavailable.</div>';
        return;
      }
      var rows = d.balances.slice(0, 12).map(function (b) {
        var val = b.value_usd == null ? "—" : "$" + Number(b.value_usd).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
        return '<div class="pionex-row">' +
          '<span class="pionex-coin">' + esc(b.coin) + '</span>' +
          '<span class="pionex-qty tabular">' + Number(b.total).toLocaleString(undefined, { maximumFractionDigits: 6 }) + '</span>' +
          '<span class="pionex-val tabular">' + val + '</span></div>';
      }).join("");
      body.innerHTML =
        '<div class="pionex-total">Total <b>$' + Number(d.total_value_usd).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '</b></div>' +
        rows;
    });
}
```

Call `loadPionex()` inside `paint()` right after `loadNewsStream()`.

Reuse the existing `esc()` helper (already in the file) and `authHeaders()`.

### 2d. CSS (add to the existing `<style>` block)

Use the existing design tokens (`--surface`, `--line`, `--accent`, etc.):

```css
.pionex-wallet{margin-bottom:16px}
.pionex-total{font-family:var(--font-display);font-size:15px;font-weight:700;margin-bottom:8px}
.pionex-row{display:grid;grid-template-columns:1fr auto auto;gap:8px;padding:7px 11px;border:1px solid var(--line);border-radius:8px;background:var(--surface-2);margin-bottom:6px;font-size:12px}
.pionex-coin{font-family:var(--font-display);font-weight:700}
.pionex-qty{color:var(--muted)}
.pionex-val{font-family:var(--font-display);font-weight:600}
```

## Conventions to respect

- Auth: all reads use `authHeaders()` (Bearer `STATE_API_TOKEN`). The new route
  must call `state_is_authorized()`.
- CORS: already permissive via `_add_cors_headers` (no change needed).
- Escape user/external strings in the UI with the existing `esc()`.
- No framework, no build step — plain JS strings like the rest of the file.
- Do not add Python dependencies; the bridge is stdlib `urllib`.

## Verify

1. `curl -H "Authorization: Bearer <token>" https://<base>/portfolio/pionex`
   -> returns the JSON shape above (200), or 401 without a token.
2. Load the dashboard: the Pionex card shows `Total $81.15` with a DOGE-led
   breakdown, and no errors in the console.
