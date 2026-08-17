"""ADV (average daily volume) liquidity bands — advisory, dashboard-only.

Reduces each asset's historical 20-day rolling average-daily-volume (ADV)
distribution to a closed-vocabulary liquidity read: ``THIN / NORMAL /
NO_DATA``. This is a discrete flag — a position-sizing / carry-cost modifier
and a liquidity veto — never a score, and it does **not** feed
``paper_execution``'s evidence roots.

Data provenance (stated, not hidden):

- The precompute reads the frozen RAW_RTH daily exports already in the
  project (``Historical Data/<asset> RTH/RAW_RTH/BATS_<sym>, 1D.csv``), which
  carry a ``Volume`` column. Read-only; the exports are never modified.
- Daily volume is **not** persisted in the SQLite DB (``alerts`` stores
  replayed event rows, no volume column). The canonical production refresh
  path is the same Massive daily-bars endpoint ``backfill.py`` already uses
  (``/v2/aggs/ticker/{sym}/range/1/day/...``) — zero new source, zero new
  credential — but it requires ``MASSIVE_API_KEY`` at runtime, which lives on
  Railway, not locally.

Choice of method (declared): ADV is the trailing 20-trading-day mean of daily
volume; the band is the distribution of that rolling ADV over the asset's full
history (median / p10 / p90, ``statistics.quantiles(method='inclusive')``).
``THIN`` is raised when the latest daily volume is below the asset's own ADV
p10; below ``MIN_ADV_OBS`` rolling observations the read is ``NO_DATA``
(no-basis). Zero/NaN volume rows are dropped as missing/placeholder bars.
"""
from __future__ import annotations

import csv
import json
import statistics
from pathlib import Path

WINDOW = 20            # ADV window (trading days)
MIN_ADV_OBS = 60       # minimum rolling-ADV observations for a band (no-basis below)
THIN_PCT = 0.10        # latest volume below the ADV p10 => THIN

ROOT = Path(__file__).resolve().parent
TABLES_DIR = ROOT / "tables"
TABLE_PATH = TABLES_DIR / "dna_liquidity_adv.csv"

# Frozen RAW_RTH daily exports (existing source data; read-only). Asset ->
# Historical Data folder name.
ASSET_DIRS = {
    "AMC": "AMC RTH",
    "GME": "GME RTH",
    "PYPL": "PYPL RTH",
    "RBLX": "RBLX RTH",
    "SPY": "SPDR S&P 500 ETF RTH",
    "U": "U RTH",
    "VALE": "VALE RTH",
}

HISTORICAL_DATA_DIR = ROOT.parent / "Historical Data"

COLUMNS = [
    "symbol", "adv_median", "adv_p10", "adv_p90", "adv_obs",
    "latest_date", "latest_volume", "liquidity",
]


def rolling_adv(volumes, window=WINDOW):
    """Trailing ``window``-day mean of ``volumes``, one value per window's
    last index (length ``len(volumes) - window + 1``)."""
    out = []
    running = 0.0
    for i, v in enumerate(volumes):
        running += v
        if i >= window:
            running -= volumes[i - window]
        if i >= window - 1:
            out.append(running / window)
    return out


def adv_band(volumes, window=WINDOW, min_obs=MIN_ADV_OBS):
    """median/p10/p90 of the rolling-ADV distribution, or None (no-basis)."""
    adv = rolling_adv(volumes, window)
    if len(adv) < min_obs:
        return None
    deciles = statistics.quantiles(adv, n=10, method="inclusive")
    return {
        "median": statistics.median(adv),
        "p10": deciles[0],
        "p90": deciles[8],
        "n_obs": len(adv),
    }


def liquidity_flag(latest_volume, band):
    """Closed-vocabulary read. ``NO_DATA`` when there is no latest volume or
    the band has no basis; ``THIN`` when latest volume is below the ADV p10."""
    if latest_volume is None or band is None:
        return "NO_DATA"
    if latest_volume < band["p10"]:
        return "THIN"
    return "NORMAL"


def _clean_pairs(pairs):
    """Drop non-positive / non-finite volumes and empty dates (missing or
    placeholder bars), keeping (date, volume) aligned."""
    out = []
    for d, v in pairs:
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        if f > 0 and f == f and d:
            out.append((d, f))
    return out


def load_asset_pairs(csv_path):
    """Read ``(date, volume)`` pairs from a frozen RAW_RTH 1D export."""
    raw = []
    with open(csv_path, encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            raw.append(((row.get("time") or "").strip(), row.get("Volume")))
    return _clean_pairs(raw)


def asset_row(symbol, pairs):
    pairs = _clean_pairs(pairs)
    band = adv_band([v for _, v in pairs])
    latest_volume = pairs[-1][1] if pairs else None
    latest_date = pairs[-1][0] if pairs else ""

    def _whole(x):
        return int(round(x)) if x is not None else None

    return {
        "symbol": symbol,
        "adv_median": _whole(band["median"]) if band else None,
        "adv_p10": _whole(band["p10"]) if band else None,
        "adv_p90": _whole(band["p90"]) if band else None,
        "adv_obs": band["n_obs"] if band else None,
        "latest_date": latest_date,
        "latest_volume": _whole(latest_volume) if latest_volume is not None else None,
        "liquidity": liquidity_flag(latest_volume, band),
    }


def compute_rows(loaders=None):
    """One row per tracked asset. ``loaders`` (optional) maps symbol ->
    list[(date, volume)] for tests; defaults to reading the frozen exports."""
    rows = []
    for symbol in ASSET_DIRS:
        if loaders is not None:
            pairs = loaders.get(symbol, [])
        else:
            csv_path = (HISTORICAL_DATA_DIR / ASSET_DIRS[symbol]
                        / "RAW_RTH" / f"BATS_{symbol}, 1D.csv")
            pairs = load_asset_pairs(csv_path)
        rows.append(asset_row(symbol, pairs))
    return rows


def write_table(rows, path=TABLE_PATH):
    """Write the precomputed table (same storage pattern as the reliability /
    silence-baseline CSVs in ``tables/``)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
    return path


def embedded_object(rows):
    """Compact per-asset object for the dashboard JS embed (LIQUIDITY_ADV)."""
    obj = {}
    for r in rows:
        obj[r["symbol"]] = {
            "median": r["adv_median"],
            "p10": r["adv_p10"],
            "p90": r["adv_p90"],
            "latest": r["latest_volume"],
            "latest_date": r["latest_date"],
            "liquidity": r["liquidity"],
        }
    return obj


def main():
    rows = compute_rows()
    path = write_table(rows)
    print(f"wrote {path}")
    print(json.dumps(rows, indent=2))
    print("--- embedded object ---")
    print("var LIQUIDITY_ADV = " + json.dumps(embedded_object(rows)) + ";")


if __name__ == "__main__":
    main()
