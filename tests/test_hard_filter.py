"""
tests/test_hard_filter.py — Tests for filters/hard_filter.py

Each test targets exactly one rule so failures point to the right place.
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from filters.hard_filter import HardFilter
from tests.fixtures import (
    GOOD_LISTING,
    SENIOR_LISTING,
    EXPENSIVE_LISTING,
    WBS_LISTING,
)


def _make_filter(**overrides) -> HardFilter:
    """Create a HardFilter with sensible defaults, optionally overriding keys."""
    cfg = {
        "max_total_rent":        1200,
        "min_rooms":            1,
        "max_rooms":            None,
        "block_if_wbs_required": False,
        "block_wbs_categories": ["WBS 100", "WBS 140"],
        "block_keywords": [
            "Wohnen ab 55", "Wohnen ab 60", "Seniorenwohnung",
            "Studentenwohnung", "Studenten",
        ],
    }
    cfg.update(overrides)
    return HardFilter(cfg)


class TestKeywordBlock(unittest.TestCase):

    def test_blocks_senior_keyword(self):
        hf = _make_filter()
        result = hf.check(SENIOR_LISTING)
        self.assertFalse(result.passed)
        self.assertIn("Wohnen ab 55", result.reason)

    def test_blocks_student_keyword(self):
        hf = _make_filter()
        listing = {**GOOD_LISTING, "raw_text": "Studentenwohnung Berlin Mitte"}
        result = hf.check(listing)
        self.assertFalse(result.passed)

    def test_keyword_match_is_case_insensitive(self):
        hf = _make_filter()
        listing = {**GOOD_LISTING, "raw_text": "WOHNEN AB 55 JAHREN"}
        result = hf.check(listing)
        self.assertFalse(result.passed)

    def test_good_listing_passes_keywords(self):
        hf = _make_filter()
        result = hf.check(GOOD_LISTING)
        # Should not be blocked by keywords (may be blocked by something else,
        # but not keywords — check the reason)
        if not result.passed:
            self.assertNotIn("keyword", result.reason.lower())

    def test_blocks_keyword_in_detail_text(self):
        # Marker hidden in the detail-page body (post-enrichment), not the title.
        hf = _make_filter()
        listing = {**GOOD_LISTING, "detail_text": "Diese Seniorenwohnung liegt zentral"}
        result = hf.check(listing)
        self.assertFalse(result.passed)
        self.assertIn("keyword", result.reason.lower())

    def test_blocks_keyword_in_address(self):
        hf = _make_filter()
        listing = {**GOOD_LISTING, "address": "Studentenwerk-Straße 1, 10115"}
        result = hf.check(listing)
        self.assertFalse(result.passed)

    def test_blocks_keyword_in_description_summary(self):
        hf = _make_filter()
        listing = {**GOOD_LISTING, "description_summary": "Schöne Studentenwohnung am Campus"}
        result = hf.check(listing)
        self.assertFalse(result.passed)


class TestWBSBlock(unittest.TestCase):

    def test_allows_wbs_when_flag_is_false(self):
        hf = _make_filter(block_if_wbs_required=False)
        result = hf.check(WBS_LISTING)
        # WBS listing passes when user has a WBS
        self.assertTrue(result.passed)

    def test_blocks_wbs_when_flag_is_true(self):
        hf = _make_filter(block_if_wbs_required=True)
        result = hf.check(WBS_LISTING)
        self.assertFalse(result.passed)
        self.assertIn("WBS required", result.reason)

    def test_no_wbs_listing_always_passes_wbs_check(self):
        hf = _make_filter(block_if_wbs_required=True)
        result = hf.check(GOOD_LISTING)
        # GOOD_LISTING has wbs="nicht erforderlich" — should not be blocked for WBS
        if not result.passed:
            self.assertNotIn("WBS required", result.reason)

    def test_blocks_specific_wbs_category(self):
        hf = _make_filter(block_wbs_categories=["WBS 100"])
        listing = {**GOOD_LISTING, "raw_text": "Wohnung WBS 100 erforderlich"}
        result = hf.check(listing)
        self.assertFalse(result.passed)
        self.assertIn("WBS 100", result.reason)

    def test_allows_unlisted_wbs_category(self):
        hf = _make_filter(block_if_wbs_required=False, block_wbs_categories=["WBS 100"])
        # WBS 220 is not in the blocklist
        listing = {**GOOD_LISTING, "wbs": "erforderlich", "raw_text": "WBS 220 erforderlich"}
        result = hf.check(listing)
        self.assertTrue(result.passed)

    def test_blocks_wbs_category_in_description_summary(self):
        hf = _make_filter(block_wbs_categories=["WBS 140"])
        listing = {**GOOD_LISTING, "description_summary": "Vergabe nur mit WBS 140"}
        result = hf.check(listing)
        self.assertFalse(result.passed)
        self.assertIn("WBS 140", result.reason)

    def test_blocks_wbs_category_in_wbs_tier(self):
        hf = _make_filter(block_wbs_categories=["WBS 160"])
        listing = {**GOOD_LISTING, "wbs_tier": "WBS 160"}
        result = hf.check(listing)
        self.assertFalse(result.passed)
        self.assertIn("WBS 160", result.reason)


class TestRentBlock(unittest.TestCase):

    def test_blocks_above_max_rent(self):
        hf = _make_filter(max_total_rent=1200)
        result = hf.check(EXPENSIVE_LISTING)  # total_rent €1485
        self.assertFalse(result.passed)
        self.assertIn("1485", result.reason)

    def test_allows_at_max_rent(self):
        hf = _make_filter(max_total_rent=574.39)
        result = hf.check(GOOD_LISTING)  # exactly total_rent €574.39
        self.assertTrue(result.passed)

    def test_allows_below_max_rent(self):
        hf = _make_filter(max_total_rent=1200)
        result = hf.check(GOOD_LISTING)  # total_rent €574.39
        self.assertTrue(result.passed)

    def test_no_rent_passes_check(self):
        """Listings where rent couldn't be parsed should not be blocked by rent filter."""
        hf = _make_filter(max_total_rent=500)
        listing = {**GOOD_LISTING, "total_rent": None}
        result = hf.check(listing)
        self.assertTrue(result.passed)

    def test_no_max_rent_config_always_passes(self):
        hf = _make_filter(max_total_rent=None)
        result = hf.check(EXPENSIVE_LISTING)
        self.assertTrue(result.passed)


class TestRoomsBlock(unittest.TestCase):

    def test_blocks_below_min_rooms(self):
        hf = _make_filter(min_rooms=2)
        listing = {**GOOD_LISTING, "rooms": 1.0}
        result = hf.check(listing)
        self.assertFalse(result.passed)

    def test_blocks_above_max_rooms(self):
        hf = _make_filter(max_rooms=2)
        listing = {**GOOD_LISTING, "rooms": 3.0}
        result = hf.check(listing)
        self.assertFalse(result.passed)

    def test_allows_within_room_range(self):
        hf = _make_filter(min_rooms=1, max_rooms=3)
        result = hf.check(GOOD_LISTING)  # 2 rooms
        self.assertTrue(result.passed)

    def test_no_rooms_parsed_passes_check(self):
        hf = _make_filter(min_rooms=2)
        listing = {**GOOD_LISTING, "rooms": None}
        result = hf.check(listing)
        self.assertTrue(result.passed)


class TestGoodListingPassesAll(unittest.TestCase):

    def test_good_listing_passes_all_rules(self):
        hf = _make_filter()
        result = hf.check(GOOD_LISTING)
        self.assertTrue(result.passed, f"Expected pass but got: {result.reason}")


if __name__ == "__main__":
    unittest.main()
