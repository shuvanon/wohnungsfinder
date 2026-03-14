"""
tests/test_formatter.py — Tests for notifier/formatter.py

Verifies that the notification message contains the right fields and
that the priority label appears prominently.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from filters.priority import PriorityResult
from notifier.formatter import format_notification
from tests.fixtures import GOOD_LISTING, HIGH_SCORE_LISTING


def _result(label="🔴 HIGH", score=75, reasons=None) -> PriorityResult:
    if reasons is None:
        reasons = ["No WBS required (+30)", "Rent under €700 (+25)"]
    return PriorityResult(label=label, score=score, reasons=reasons)


class TestFormatNotification(unittest.TestCase):

    def test_contains_priority_label(self):
        msg = format_notification(GOOD_LISTING, _result("🔴 HIGH"))
        self.assertIn("🔴 HIGH", msg)

    def test_contains_score(self):
        msg = format_notification(GOOD_LISTING, _result(score=75))
        self.assertIn("75", msg)

    def test_contains_address(self):
        msg = format_notification(GOOD_LISTING, _result())
        self.assertIn("Siegfriedstraße", msg)

    def test_contains_rent(self):
        msg = format_notification(GOOD_LISTING, _result())
        self.assertIn("469", msg)

    def test_contains_wbs_status(self):
        msg = format_notification(GOOD_LISTING, _result())
        self.assertIn("nicht erforderlich", msg)

    def test_contains_url_link(self):
        msg = format_notification(GOOD_LISTING, _result())
        self.assertIn(GOOD_LISTING["url"], msg)

    def test_contains_reasons(self):
        msg = format_notification(GOOD_LISTING, _result(reasons=["No WBS (+30)"]))
        self.assertIn("No WBS (+30)", msg)

    def test_no_reasons_omits_breakdown_section(self):
        msg = format_notification(GOOD_LISTING, _result(reasons=[]))
        self.assertNotIn("Priority breakdown", msg)

    def test_features_included(self):
        msg = format_notification(GOOD_LISTING, _result())
        self.assertIn("Balkon", msg)

    def test_medium_label(self):
        msg = format_notification(GOOD_LISTING, _result("🟡 MEDIUM", score=30))
        self.assertIn("🟡 MEDIUM", msg)

    def test_low_label(self):
        msg = format_notification(GOOD_LISTING, _result("⚪ LOW", score=10))
        self.assertIn("⚪ LOW", msg)

    def test_missing_optional_fields_dont_crash(self):
        """Listings with None fields should still produce a valid message."""
        sparse = {
            "url":   "https://example.de/sparse",
            "title": "",
            "address": "",
            "district": "",
            "rooms": None, "size_m2": None,
            "cold_rent": None, "total_rent": None,
            "wbs": None, "available": None,
            "floor": None, "year_built": None,
            "features": [],
            "raw_text": "",
        }
        msg = format_notification(sparse, _result())
        self.assertIn("https://example.de/sparse", msg)

    def test_output_is_string(self):
        msg = format_notification(GOOD_LISTING, _result())
        self.assertIsInstance(msg, str)

    def test_output_is_non_empty(self):
        msg = format_notification(GOOD_LISTING, _result())
        self.assertTrue(len(msg) > 50)


if __name__ == "__main__":
    unittest.main()
