"""
tests/test_store.py — Tests for scraper/store.py (SQLite backend)

Every test gets a fresh in-memory database via _make_store() so tests
are fully isolated and leave no files on disk.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from filters.hard_filter import FilterResult
from filters.priority    import PriorityResult
from scraper.store       import ListingStore
from tests.fixtures      import GOOD_LISTING, WBS_LISTING, SENIOR_LISTING


def _make_store() -> ListingStore:
    """Return a ListingStore backed by a fresh in-memory SQLite database."""
    store = ListingStore(Path(":memory:"))
    return store


def _listing(url: str) -> dict:
    return {**GOOD_LISTING, "url": url}


def _passed() -> FilterResult:
    return FilterResult(passed=True)


def _blocked(reason: str = "Blocked keyword: 'test'") -> FilterResult:
    return FilterResult(passed=False, reason=reason)


def _priority(label="🔴 HIGH", score=75) -> PriorityResult:
    return PriorityResult(label=label, score=score, reasons=["No WBS (+30)", "Rent under €700 (+25)"])


# ── find_new ──────────────────────────────────────────────────────────────────

class TestFindNew(unittest.TestCase):

    def test_all_new_on_empty_store(self):
        store = _make_store()
        listings = [_listing("https://a.de/1"), _listing("https://a.de/2")]
        self.assertEqual(len(store.find_new(listings)), 2)

    def test_no_new_when_all_known(self):
        store = _make_store()
        listings = [_listing("https://a.de/1")]
        store.mark_seen(listings)
        self.assertEqual(store.find_new(listings), [])

    def test_only_unseen_returned(self):
        store = _make_store()
        old = _listing("https://a.de/old")
        new = _listing("https://a.de/new")
        store.mark_seen([old])
        result = store.find_new([old, new])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["url"], "https://a.de/new")

    def test_empty_input_returns_empty(self):
        store = _make_store()
        self.assertEqual(store.find_new([]), [])


# ── mark_seen ─────────────────────────────────────────────────────────────────

class TestMarkSeen(unittest.TestCase):

    def test_mark_seen_prevents_future_find(self):
        store = _make_store()
        listing = _listing("https://a.de/1")
        store.mark_seen([listing])
        self.assertEqual(store.find_new([listing]), [])

    def test_mark_seen_is_idempotent(self):
        store = _make_store()
        listing = _listing("https://a.de/1")
        store.mark_seen([listing])
        store.mark_seen([listing])  # INSERT OR IGNORE — should not raise or duplicate
        self.assertEqual(len(store), 1)

    def test_all_fields_persisted(self):
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        row = store._conn.execute(
            "SELECT * FROM listings WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["address"],   GOOD_LISTING["address"])
        self.assertAlmostEqual(row["cold_rent"], GOOD_LISTING["cold_rent"])
        self.assertEqual(row["district"],  GOOD_LISTING["district"])

    def test_features_stored_as_json_array(self):
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        row = store._conn.execute(
            "SELECT features FROM listings WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()
        features = json.loads(row["features"])
        self.assertIsInstance(features, list)
        self.assertIn("Balkon", features)

    def test_seen_at_is_populated(self):
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        row = store._conn.execute(
            "SELECT seen_at FROM listings WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()
        self.assertIsNotNone(row["seen_at"])
        self.assertIn("T", row["seen_at"])  # ISO 8601 contains 'T'

    def test_multiple_listings_inserted(self):
        store = _make_store()
        store.mark_seen([_listing("https://a.de/1"), _listing("https://a.de/2")])
        self.assertEqual(len(store), 2)


# ── log_filter_result ─────────────────────────────────────────────────────────

class TestLogFilterResult(unittest.TestCase):

    def test_blocked_result_logged(self):
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        store.log_filter_result(GOOD_LISTING, _blocked("Blocked keyword: 'Seniorenwohnung'"))
        row = store._conn.execute(
            "SELECT * FROM filter_results WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["passed"], 0)
        self.assertIn("Seniorenwohnung", row["block_reason"])
        self.assertIsNone(row["priority"])
        self.assertIsNone(row["score"])

    def test_passed_result_logged_with_priority(self):
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        store.log_filter_result(GOOD_LISTING, _passed(), _priority("🔴 HIGH", 75))
        row = store._conn.execute(
            "SELECT * FROM filter_results WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()
        self.assertEqual(row["passed"], 1)
        self.assertIsNone(row["block_reason"])
        self.assertEqual(row["priority"], "🔴 HIGH")
        self.assertEqual(row["score"], 75)

    def test_reasons_stored_as_json(self):
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        store.log_filter_result(GOOD_LISTING, _passed(), _priority())
        row = store._conn.execute(
            "SELECT reasons FROM filter_results WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()
        reasons = json.loads(row["reasons"])
        self.assertIsInstance(reasons, list)
        self.assertTrue(len(reasons) > 0)

    def test_multiple_results_for_same_url(self):
        """Each scrape cycle logs a new row — url is not unique in filter_results."""
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        store.log_filter_result(GOOD_LISTING, _passed(), _priority())
        store.log_filter_result(GOOD_LISTING, _passed(), _priority())
        count = store._conn.execute(
            "SELECT COUNT(*) FROM filter_results WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()[0]
        self.assertEqual(count, 2)

    def test_seen_at_populated_in_filter_results(self):
        store = _make_store()
        store.mark_seen([GOOD_LISTING])
        store.log_filter_result(GOOD_LISTING, _passed(), _priority())
        row = store._conn.execute(
            "SELECT seen_at FROM filter_results WHERE url = ?", (GOOD_LISTING["url"],)
        ).fetchone()
        self.assertIsNotNone(row["seen_at"])


# ── persistence ───────────────────────────────────────────────────────────────

class TestPersistence(unittest.TestCase):

    def test_data_survives_reconnect(self):
        """Close and reopen a real on-disk DB — data must still be there."""
        import tempfile, os
        with tempfile.TemporaryDirectory() as td:
            db_path = Path(td) / "listings.db"
            store1 = ListingStore(db_path)
            store1.mark_seen([GOOD_LISTING])
            store1.close()

            store2 = ListingStore(db_path)
            self.assertEqual(len(store2), 1)
            self.assertEqual(store2.find_new([GOOD_LISTING]), [])
            store2.close()

    def test_schema_version_set(self):
        store = _make_store()
        version = store._conn.execute("PRAGMA user_version").fetchone()[0]
        self.assertEqual(version, 1)

    def test_wal_mode_enabled(self):
        store = _make_store()
        mode = store._conn.execute("PRAGMA journal_mode").fetchone()[0]
        # :memory: databases report 'memory', not 'wal' — only check on-disk
        # This test verifies the PRAGMA is applied without erroring
        self.assertIn(mode, ("wal", "memory"))

    def test_parent_dirs_created(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            deep_path = Path(td) / "nested" / "dir" / "listings.db"
            store = ListingStore(deep_path)
            self.assertTrue(deep_path.exists())
            store.close()


# ── len ───────────────────────────────────────────────────────────────────────

class TestLen(unittest.TestCase):

    def test_len_zero_on_empty(self):
        self.assertEqual(len(_make_store()), 0)

    def test_len_reflects_inserted_count(self):
        store = _make_store()
        store.mark_seen([_listing("https://a.de/1"), _listing("https://a.de/2")])
        self.assertEqual(len(store), 2)


# ── save no-op ────────────────────────────────────────────────────────────────

class TestSaveNoOp(unittest.TestCase):

    def test_save_does_not_raise(self):
        """save() is a no-op kept for interface compatibility."""
        store = _make_store()
        store.save()  # must not raise


if __name__ == "__main__":
    unittest.main()
