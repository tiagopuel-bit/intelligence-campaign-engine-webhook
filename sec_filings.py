"""SEC EDGAR filing watcher — isolated, cloud-only module.

Owns the watched-form constants, SEC request and response normalization,
safe accession/document URL construction, exact-form/variant matching, and
SQLite initialization/upsert/query helpers. Exposes one deterministic
``poll_symbol(...)`` entry point that can be tested with a mocked SEC response.

Deliberately does NOT import Flask or webhook_receiver: this module is used by
both the Flask read endpoint and the standalone polling script, and must stay
free of request/response concerns so its unit tests need no app context.

Fair-access and identity rules enforced here:
- A declared ``SEC_USER_AGENT`` env var is required; if absent, no request is
  made and an honest configuration error is returned.
- Requests carry ``User-Agent`` and ``Accept-Encoding: gzip, deflate`` and an
  explicit timeout; callers should not poll faster than MIN_POLL_INTERVAL.
- Filing document URLs are built only from SEC-returned accession/document
  fields and always resolve under https://www.sec.gov/Archives/edgar/data/.
"""

from __future__ import annotations

import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# --- watched symbols --------------------------------------------------------

SYMBOL_TO_CIK = {
    "AMC": "0001411579",
}

# base form -> (category, severity). Raw forms are preserved; variants (e.g.
# "S-3ASR", ".../A") map to a base form and carry an explicit variant label.
WATCHED_FORMS = {
    "424B5": ("DILUTION_WATCH", "HIGH"),
    "FWP": ("DILUTION_WATCH", "HIGH"),
    "S-3": ("DILUTION_WATCH", "MEDIUM"),
    "8-K": ("MATERIAL_FILING", "MEDIUM"),
    "10-Q": ("MATERIAL_FILING", "INFO"),
    "10-K": ("MATERIAL_FILING", "INFO"),
    "3": ("INSIDER_FILING", "INFO"),
    "4": ("INSIDER_FILING", "INFO"),
    "5": ("INSIDER_FILING", "INFO"),
}

CATEGORIES = ("DILUTION_WATCH", "MATERIAL_FILING", "INSIDER_FILING")
SEVERITIES = ("HIGH", "MEDIUM", "INFO")

_S3_SHELF_VARIANTS = {"S-3ASR", "S-3MEF", "S-3D"}

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik}.json"
SEC_ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data"

MIN_POLL_INTERVAL_SECONDS = 300
REQUEST_TIMEOUT_SECONDS = 10
DEFAULT_ALERT_WINDOW_HOURS = 72
STALE_AFTER_SECONDS = 24 * 3600


# --- database path (mirrors webhook_receiver.resolve_db_path) ---------------

def resolve_db_path() -> Path:
    if os.environ.get("DATABASE_PATH"):
        return Path(os.environ["DATABASE_PATH"]).expanduser()
    if os.environ.get("RAILWAY_VOLUME_MOUNT_PATH"):
        return Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]) / "dna_alerts.db"
    return Path(__file__).parent / "dna_alerts.db"


# --- form normalization -----------------------------------------------------

def normalize_form(raw) -> tuple[str | None, str | None]:
    """Return (base_form, variant) for a raw SEC form string.

    Preserves the raw form elsewhere; here we only derive the watched base and
    an honest variant label. Unknown/unwatched forms return (None, None).
    """
    form = (raw or "").strip().upper()
    if not form:
        return None, None
    variant = None
    if form.endswith("/A"):
        form = form[:-2]
        variant = "amendment"
    if form in _S3_SHELF_VARIANTS:
        form = "S-3"
        variant = variant or "automatic shelf registration"
    if form not in WATCHED_FORMS:
        return None, None
    return form, variant


# --- safe URL construction --------------------------------------------------

def build_filing_url(cik, accession, primary_document) -> str | None:
    """Construct an SEC Archives document URL from SEC-returned fields only.

    Rejects anything that would leave https://www.sec.gov/Archives/edgar/data/
    (unsafe document paths, non-numeric CIK/accession). Returns None on bad
    input instead of raising.
    """
    if not cik or not accession or not primary_document:
        return None
    cik_clean = str(cik).lstrip("0")
    acc_clean = str(accession).replace("-", "").strip()
    if not re.fullmatch(r"\d+", cik_clean) or not re.fullmatch(r"\d+", acc_clean):
        return None
    doc = str(primary_document).strip()
    if not doc or doc.startswith(("/", "\\")) or ".." in doc or "://" in doc:
        return None
    return f"{SEC_ARCHIVES_BASE}/{cik_clean}/{acc_clean}/{doc}"


# --- SEC request ------------------------------------------------------------

def user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "").strip()


def fetch_submissions(cik: str, timeout: int = REQUEST_TIMEOUT_SECONDS):
    """Fetch and return the SEC submissions JSON, or (None, [error]).

    Returns (data, errors) where errors is a list of sanitized strings. Never
    raises for upstream problems. Makes no request if SEC_USER_AGENT is absent.
    """
    ua = user_agent()
    if not ua:
        return None, ["SEC_USER_AGENT not configured — no request made"]
    try:
        resp = requests.get(
            SUBMISSIONS_URL.format(cik=cik),
            headers={"User-Agent": ua, "Accept-Encoding": "gzip, deflate"},
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json(), []
    except Exception as exc:  # noqa: BLE001
        return None, [_sanitize_error(exc)]


def _sanitize_error(exc: Exception) -> str:
    """Return a bounded, secret-free description of an upstream error."""
    text = str(exc) or exc.__class__.__name__
    text = re.sub(r"(api[_-]?key|token|secret|authorization)=[^&\s]+", r"\1=<redacted>", text, flags=re.I)
    return text[:300]


def _normalize_submissions(data):
    """SEC submissions JSON -> (filings, error).

    filings is a list of watched-filing dicts. error is None on success, or a
    string when the columnar arrays are missing/malformed (fail safe).
    """
    try:
        recent = data["filings"]["recent"]
        forms = recent.get("form") or []
        dates = recent.get("filingDate") or []
        accessions = recent.get("accessionNumber") or []
        primaries = recent.get("primaryDocument") or []
        acceptances = recent.get("acceptanceDateTime") or []
        if not (len(forms) == len(dates) == len(accessions) == len(primaries) == len(acceptances)):
            return [], "SEC submissions response has mismatched columnar arrays"
    except (KeyError, TypeError, AttributeError):
        return [], "SEC submissions response is malformed"

    filings = []
    for i in range(len(forms)):
        base, variant = normalize_form(forms[i])
        if base is None:
            continue
        category, severity = WATCHED_FORMS[base]
        filings.append({
            "accession": accessions[i],
            "form": (forms[i] or "").strip().upper(),
            "base_form": base,
            "variant": variant,
            "filing_date": dates[i],
            "acceptance_time": acceptances[i],
            "primary_document": primaries[i],
            "category": category,
            "severity": severity,
        })
    return filings, None


# --- schema -----------------------------------------------------------------

def ensure_schema(conn) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sec_filing_watch_state (
            symbol TEXT PRIMARY KEY,
            cik TEXT,
            seeded_at TEXT,
            last_polled_at TEXT,
            last_success_at TEXT,
            last_error TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sec_filings (
            accession TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            cik TEXT,
            form TEXT,
            base_form TEXT,
            filing_date TEXT,
            acceptance_time TEXT,
            primary_document TEXT,
            filing_url TEXT,
            category TEXT CHECK(category IN ('DILUTION_WATCH','MATERIAL_FILING','INSIDER_FILING')),
            severity TEXT CHECK(severity IN ('HIGH','MEDIUM','INFO')),
            first_seen_at TEXT,
            seed_record INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sec_filings_symbol_seen ON sec_filings(symbol, first_seen_at)")


# --- SQLite helpers ---------------------------------------------------------

def _upsert_watch_state(conn, symbol, cik, *, seeded_at=None, last_polled_at=None,
                        last_success_at=None, last_error=None) -> None:
    conn.execute(
        "INSERT INTO sec_filing_watch_state (symbol, cik, seeded_at, last_polled_at, last_success_at, last_error) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(symbol) DO UPDATE SET "
        "cik=COALESCE(excluded.cik, sec_filing_watch_state.cik),"
        "seeded_at=COALESCE(excluded.seeded_at, sec_filing_watch_state.seeded_at),"
        "last_polled_at=COALESCE(excluded.last_polled_at, sec_filing_watch_state.last_polled_at),"
        "last_success_at=COALESCE(excluded.last_success_at, sec_filing_watch_state.last_success_at),"
        "last_error=excluded.last_error",
        (symbol, cik, seeded_at, last_polled_at, last_success_at, last_error),
    )


def _insert_filing(conn, symbol, cik, f, now_iso, seed_record) -> bool:
    url = build_filing_url(cik, f["accession"], f["primary_document"])
    cur = conn.execute(
        "INSERT OR IGNORE INTO sec_filings "
        "(accession, symbol, cik, form, base_form, filing_date, acceptance_time, "
        " primary_document, filing_url, category, severity, first_seen_at, seed_record) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (f["accession"], symbol, cik, f["form"], f["base_form"], f["filing_date"],
         f["acceptance_time"], f["primary_document"], url, f["category"], f["severity"],
         now_iso, 1 if seed_record else 0),
    )
    return cur.rowcount == 1


def _row_to_filing(row) -> dict:
    return {
        "accession": row["accession"],
        "form": row["form"],
        "base_form": row["base_form"],
        "variant": _variant_of(row["form"]),
        "filing_date": row["filing_date"],
        "acceptance_time": row["acceptance_time"],
        "category": row["category"],
        "severity": row["severity"],
        "filing_url": row["filing_url"],
        "first_seen_at": row["first_seen_at"],
        "seed_record": bool(row["seed_record"]),
    }


def _variant_of(raw_form) -> str | None:
    base, variant = normalize_form(raw_form)
    return variant


# --- deterministic poll -----------------------------------------------------

def poll_symbol(db_path, symbol: str, now=None) -> dict:
    """One deterministic poll for one symbol. Returns the result contract.

    Contract keys: symbol, cik, configured, seeded, new_filings, recent_filings,
    errors, last_polled_at, last_success_at.

    - first poll seeds silently (seeded=True, new_filings empty);
    - subsequent polls return only newly-seen accessions;
    - config/upstream errors preserve prior state and record a sanitized error.
    """
    symbol = symbol.upper()
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    result = {
        "symbol": symbol,
        "cik": SYMBOL_TO_CIK.get(symbol),
        "configured": bool(user_agent()),
        "seeded": False,
        "new_filings": [],
        "recent_filings": [],
        "errors": [],
        "last_polled_at": now_iso,
        "last_success_at": None,
    }

    if symbol not in SYMBOL_TO_CIK:
        result["errors"].append(f"symbol {symbol} is not mapped to a CIK")
        return result

    cik = SYMBOL_TO_CIK[symbol]

    if not user_agent():
        result["errors"].append("SEC_USER_AGENT not configured — no request made")
        _record_error(db_path, symbol, cik, now_iso, "SEC_USER_AGENT not configured")
        return result

    data, fetch_errors = fetch_submissions(cik)
    if data is None:
        result["errors"].extend(fetch_errors)
        _record_error(db_path, symbol, cik, now_iso, "; ".join(fetch_errors))
        return result

    filings, norm_error = _normalize_submissions(data)
    if norm_error:
        result["errors"].append(norm_error)
        _record_error(db_path, symbol, cik, now_iso, norm_error)
        return result

    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    row = conn.execute("SELECT seeded_at FROM sec_filing_watch_state WHERE symbol=?", (symbol,)).fetchone()
    is_first = row is None or row["seeded_at"] is None
    seeded_at = now_iso if is_first else row["seeded_at"]

    new_filings = []
    for f in filings:
        inserted = _insert_filing(conn, symbol, cik, f, now_iso, seed_record=is_first)
        if inserted and not is_first:
            new_filings.append(dict(f, filing_url=build_filing_url(cik, f["accession"], f["primary_document"]),
                                    first_seen_at=now_iso, seed_record=False))

    _upsert_watch_state(conn, symbol, cik, seeded_at=seeded_at,
                        last_polled_at=now_iso, last_success_at=now_iso, last_error=None)
    conn.commit()

    recent = _list_filings(conn, symbol, DEFAULT_ALERT_WINDOW_HOURS, now)
    conn.close()

    result["seeded"] = is_first
    result["new_filings"] = new_filings
    result["recent_filings"] = recent
    result["last_success_at"] = now_iso
    return result


def _record_error(db_path, symbol, cik, now_iso, error) -> None:
    conn = sqlite3.connect(str(db_path), timeout=30)
    _upsert_watch_state(conn, symbol, cik, last_polled_at=now_iso, last_error=error)
    conn.commit()
    conn.close()


# --- read helpers (used by the Flask endpoint) ------------------------------

def _list_filings(conn, symbol, window_hours, now) -> list[dict]:
    cutoff = (now - timedelta(hours=window_hours)).isoformat()
    rows = conn.execute(
        "SELECT * FROM sec_filings WHERE symbol=? AND first_seen_at >= ? "
        "ORDER BY first_seen_at DESC, acceptance_time DESC",
        (symbol, cutoff),
    ).fetchall()
    return [_row_to_filing(r) for r in rows]


def get_filings_state(db_path, symbol: str, window_hours: int = DEFAULT_ALERT_WINDOW_HOURS, now=None) -> dict:
    """Read-only state for GET /filings/<symbol>. Never makes an SEC request."""
    symbol = symbol.upper()
    now = now or datetime.now(timezone.utc)
    conn = sqlite3.connect(str(db_path), timeout=30)
    conn.row_factory = sqlite3.Row
    ws = conn.execute("SELECT * FROM sec_filing_watch_state WHERE symbol=?", (symbol,)).fetchone()
    recent = _list_filings(conn, symbol, window_hours, now)
    conn.close()

    configured = bool(user_agent())
    seeded = bool(ws and ws["seeded_at"])
    last_success_at = ws["last_success_at"] if ws else None
    stale = True
    if last_success_at:
        try:
            dt = datetime.fromisoformat(last_success_at)
            stale = (now - dt).total_seconds() > STALE_AFTER_SECONDS
        except ValueError:
            stale = True

    return {
        "symbol": symbol,
        "configured": configured,
        "seeded": seeded,
        "last_polled_at": ws["last_polled_at"] if ws else None,
        "last_success_at": last_success_at,
        "stale": stale,
        "error": (ws["last_error"] if ws else None) or None,
        "window_hours": window_hours,
        "recent": recent,
        "new": [f for f in recent if not f["seed_record"]],
    }
