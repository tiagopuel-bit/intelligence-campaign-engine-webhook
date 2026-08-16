"""Portfolio-construction policy for the multi-asset experiment (PAPER_ONLY).

Pure, deterministic policy functions for the spec's §2 (30% AMC floor), §5
(per-asset eligibility gate) and §6 (equal-weight allocation), plus a
read-only book-value valuation of the paper ledger. No I/O beyond the given
connection and the static reliability CSV; no broker path.
"""
from __future__ import annotations

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ANCHOR_SYMBOL = "AMC"
AMC_FLOOR_PCT = 0.30
MIN_CLASSIFIED_BARS = 25
OPTION_MULTIPLIER = 100
# §6: the remaining 70% is split equally across the non-anchor tracked assets.
REMAINING_WEIGHT_PCT = 0.70
RELIABILITY_CSV = ROOT / "tables" / "dna_campaign_lifecycle_reliability.csv"
# §5: the tiers a symbol must clear to be trade-eligible, and their timeframes.
REQUIRED_TIERS = {
    "timing": ("15m", "30m"),
    "confirm": ("1H", "2H"),
    "owner": ("3H", "4H"),
}


def projected_amc_weight(amc_value: float, total_value: float, notional: float) -> float:
    """Projected AMC weight if a non-AMC deployment of `notional` executes."""
    if total_value + notional <= 0:
        return 0.0
    return amc_value / (total_value + notional)


def amc_floor_breached(amc_value: float, total_value: float, notional: float) -> bool:
    """R1: a non-AMC open/add whose projected AMC weight drops below the floor."""
    return projected_amc_weight(amc_value, total_value, notional) < AMC_FLOOR_PCT


def non_anchor_weight_cap(non_anchor_count: int) -> float:
    """§6: equal-weight cap for each non-anchor asset (0.70 / N)."""
    if non_anchor_count <= 0:
        return 0.0
    return REMAINING_WEIGHT_PCT / non_anchor_count


def legs_notional(legs) -> float:
    """Summed notional of reconstructed legs (price x qty x contract multiplier)."""
    total = 0.0
    for leg in legs or []:
        price = _num(leg.get("price_reference"))
        qty = _num(leg.get("quantity"))
        if price is None or qty is None:
            continue
        instrument = str(leg.get("instrument_type") or "SHARE").upper()
        multiplier = OPTION_MULTIPLIER if instrument in {"CALL", "PUT"} else 1
        total += price * qty * multiplier
    return total


def _num(value) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def load_reliability_mask(path: Path = RELIABILITY_CSV) -> dict[str, dict[str, tuple[int, int]]]:
    """{symbol: {timeframe: (classified_bars, reliable)}} from the static CSV."""
    mask: dict[str, dict[str, tuple[int, int]]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            bars = int(row["classified_bars"]) if row.get("classified_bars") else 0
            reliable = 1 if row.get("reliable") == "1" else 0
            mask.setdefault(row["symbol"], {})[row["timeframe"]] = (bars, reliable)
    return mask


def asset_eligible(mask: dict[str, dict[str, tuple[int, int]]], symbol: str) -> bool:
    """§5: every timeframe in the required tiers clears the sample + reliability floor."""
    rows = mask.get(symbol, {})
    for timeframes in REQUIRED_TIERS.values():
        for tf in timeframes:
            bars, reliable = rows.get(tf, (0, 0))
            if bars < MIN_CLASSIFIED_BARS or reliable != 1:
                return False
    return True


def paper_portfolio_value(conn, experiment_id: int) -> dict:
    """Read-only book-value valuation of the isolated paper ledger.

    Cash plus each position valued at its latest paper fill price (falling
    back to the frozen starting market value). This is a book-value proxy,
    not a marked-to-market valuation; it is only used for the 30% floor gate.
    """
    cash = conn.execute(
        "SELECT cash FROM pe_paper_cash WHERE experiment_id=?", (experiment_id,)
    ).fetchone()
    total = float(cash["cash"]) if cash else 0.0
    by_symbol: dict[str, float] = {}

    for position in conn.execute(
        "SELECT symbol, instrument_type, ticker, quantity FROM pe_paper_positions "
        "WHERE experiment_id=?", (experiment_id,)
    ).fetchall():
        symbol = position["symbol"]
        instrument_type = str(position["instrument_type"] or "SHARE").upper()
        multiplier = OPTION_MULTIPLIER if instrument_type in {"CALL", "PUT"} else 1
        quantity = float(position["quantity"] or 0.0)
        price = _last_fill_price(conn, experiment_id, position["ticker"])
        if price is None:
            price = _frozen_market_value_per_unit(conn, experiment_id, position["ticker"], quantity)
        value = quantity * (price or 0.0) * multiplier
        by_symbol[symbol] = by_symbol.get(symbol, 0.0) + value
        total += value

    return {
        "total_value": total,
        "amc_value": by_symbol.get(ANCHOR_SYMBOL, 0.0),
        "by_symbol": by_symbol,
    }


def _last_fill_price(conn, experiment_id: int, ticker: str) -> float | None:
    row = conn.execute(
        "SELECT f.fill_price FROM pe_paper_fills f "
        "JOIN pe_paper_orders o ON o.id = f.order_id "
        "WHERE o.proposal_id IN (SELECT id FROM pe_order_proposals WHERE experiment_id=?) "
        "AND o.ticker=? ORDER BY f.id DESC LIMIT 1",
        (experiment_id, ticker),
    ).fetchone()
    return float(row["fill_price"]) if row and row["fill_price"] is not None else None


def _frozen_market_value_per_unit(conn, experiment_id: int, ticker: str, quantity: float) -> float:
    row = conn.execute(
        "SELECT market_value, quantity FROM pe_starting_holdings "
        "WHERE experiment_id=? AND ticker=? LIMIT 1", (experiment_id, ticker),
    ).fetchone()
    if row is None or not row["quantity"]:
        return 0.0
    return float(row["market_value"]) / float(row["quantity"])
