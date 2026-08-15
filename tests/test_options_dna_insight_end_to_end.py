"""End-to-end scenario: insight actions over real assembled Options DNA rows.

Loads the frozen AMC expansion causal ledger (provenance only) and maps each
causal row into a contract-specific insight observation, verifying the insight
library returns only advisory actions and never leaks future outcomes.
"""
import gzip
import csv
import unittest
from pathlib import Path

from options_dna_insight import ACTIONS, contract_insight

ROOT = Path(__file__).resolve().parents[1]
CAUSAL_PATH = ROOT / "reports" / "options_dna_expansion" / "entry_calibration_v1" / "entry_causal.csv.gz"

_FAMILY_TONE = {
    "ENTRY_FORMING": "pos",
    "CONTINUATION": "pos",
    "RISK_OR_EXHAUSTION": "warn",
    "THESIS_PRESSURE": "neg",
}


def _number(value):
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _observation(row):
    family = str(row.get("underlying__event_family") or row.get("event_family") or "")
    premium = _number(row.get("contract__option_return") or row.get("option_return"))
    dte = _number(row.get("dte"))
    moneyness = _number(row.get("moneyness_pct"))
    ctype = str(row.get("contract_type") or "CALL")
    return {
        "underlying": {
            "campaign_tone": _FAMILY_TONE.get(family, "neu"),
            "upper_neg": family == "THESIS_PRESSURE",
            "exhaustion_warning": family == "RISK_OR_EXHAUSTION",
        },
        "contract": {
            "premium_return": premium,
            "volume_ratio": _number(row.get("contract__volume_ratio")),
            "unchanged_print": premium is None or premium == 0.0,
            "dte": dte,
            "itm": (moneyness > 0.0) if moneyness is not None else None,
        },
        "catalyst": {"sec_veto": False, "sec_active": False},
        "position": {"exists": False},
    }


class InsightEndToEndTest(unittest.TestCase):
    def test_insight_over_real_ledger(self):
        if not CAUSAL_PATH.exists():
            self.skipTest("AMC causal ledger not assembled")
        with gzip.open(CAUSAL_PATH, "rt", encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreater(len(rows), 0)
        actions_seen = set()
        for row in rows[:200]:
            result = contract_insight(_observation(row))
            self.assertIn(result["action"], ACTIONS)
            self.assertIn("confidence", result)
            actions_seen.add(result["action"])
        self.assertTrue(actions_seen, "at least one action should be produced")
        self.assertTrue(actions_seen.issubset(set(ACTIONS)))


if __name__ == "__main__":
    unittest.main()
