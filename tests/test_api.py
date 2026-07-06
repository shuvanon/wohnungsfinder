"""
tests/test_api.py — Tests for api/queries.py (the read-only query layer).

The FastAPI routes in api/server.py are thin wrappers over these functions, so
testing the query layer covers the behaviour without needing an HTTP client or
the fastapi/uvicorn dependencies at test time.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.store import ListingStore
from filters.hard_filter import FilterResult
from filters.priority import PriorityResult
from api import queries
from tests.fixtures import GOOD_LISTING


def _seed(db_path: Path) -> None:
    store = ListingStore(db_path)
    l1 = {**GOOD_LISTING, "url": "https://x.de/1", "district": "Mitte", "total_rent": 600.0}
    l2 = {**GOOD_LISTING, "url": "https://x.de/2", "district": "Pankow", "total_rent": 900.0}
    store.mark_seen([l1, l2])
    store.log_filter_result(l1, FilterResult(passed=True), PriorityResult("🔴 HIGH", 70, ["No WBS (+30)"]))
    store.log_filter_result(l2, FilterResult(passed=False, reason="Total rent too high"))
    store.close()


class TestQueries(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = Path(self._tmp.name) / "listings.db"
        _seed(self.db)

    def tearDown(self):
        self._tmp.cleanup()

    def test_health(self):
        h = queries.health(self.db)
        self.assertEqual(h["status"], "ok")
        self.assertEqual(h["listing_count"], 2)
        self.assertEqual(h["schema_version"], 3)

    def test_list_listings_excludes_detail_text_and_parses_features(self):
        rows = queries.list_listings(self.db)
        self.assertEqual(len(rows), 2)
        self.assertNotIn("detail_text", rows[0])
        self.assertIsInstance(rows[0]["features"], list)

    def test_list_respects_limit(self):
        self.assertEqual(len(queries.list_listings(self.db, limit=1)), 1)

    def test_filter_by_district(self):
        rows = queries.list_listings(self.db, district="Mitte")
        self.assertEqual([r["url"] for r in rows], ["https://x.de/1"])

    def test_filter_by_max_rent(self):
        rows = queries.list_listings(self.db, max_rent=700)
        self.assertEqual({r["url"] for r in rows}, {"https://x.de/1"})

    def test_get_listing_includes_detail_text(self):
        r = queries.get_listing(self.db, "https://x.de/1")
        self.assertEqual(r["district"], "Mitte")
        self.assertIn("detail_text", r)  # single-listing view has the full row

    def test_get_listing_missing_returns_none(self):
        self.assertIsNone(queries.get_listing(self.db, "https://x.de/nope"))

    def test_candidates_only_passed_with_priority(self):
        c = queries.list_candidates(self.db)
        self.assertEqual([x["url"] for x in c], ["https://x.de/1"])
        self.assertEqual(c[0]["priority"], "🔴 HIGH")
        self.assertEqual(c[0]["score"], 70)

    def test_candidates_since_filters(self):
        # A future timestamp excludes everything.
        self.assertEqual(queries.list_candidates(self.db, since="2099-01-01"), [])

    def test_connection_is_read_only(self):
        conn = queries._connect(self.db)
        try:
            with self.assertRaises(Exception):
                conn.execute("INSERT INTO listings(url, seen_at) VALUES ('x', 'y')")
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
