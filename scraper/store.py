"""
store.py — SQLite-backed listing store.

Two tables:
  listings       — every apartment we have ever seen, with all parsed fields
  filter_results — one row per new listing, recording what the filter/scorer decided

Public interface is unchanged from the JSON version so nothing else in the
codebase needs to care about the storage backend:

    store = ListingStore(Path("data/listings.db"))
    new_ones = store.find_new(scraped_listings)
    store.mark_seen(new_ones)
    store.log_filter_result(listing, filter_result, priority_result)
    # no explicit save() needed — SQLite writes are transactional

The database file is created automatically on first run.
All schema changes are applied via _migrate() so the file can be updated
in place without losing data.
"""

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from filters.hard_filter import FilterResult
from filters.priority    import PriorityResult

logger = logging.getLogger(__name__)

# Increment this when the schema changes. _migrate() handles upgrades.
_SCHEMA_VERSION = 1


class ListingStore:
    """
    Persistent store for apartment listings and filter audit log.

    Usage:
        store = ListingStore(Path("data/listings.db"))

        new_ones = store.find_new(scraped_listings)
        store.mark_seen(new_ones)

        # After filtering and scoring each new listing:
        store.log_filter_result(listing, filter_result, priority_result)
    """

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._path = path
        self._conn = self._connect()
        self._migrate()
        count = self._conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        logger.info(f"Store opened: {count} listings in {path}")

    # ── Public API ─────────────────────────────────────────────────────────────

    def find_new(self, listings: list[dict]) -> list[dict]:
        """Return only listings whose URL is not yet in the database."""
        if not listings:
            return []
        candidate_urls = [l["url"] for l in listings]
        placeholders = ",".join("?" * len(candidate_urls))
        seen = {
            row[0]
            for row in self._conn.execute(
                f"SELECT url FROM listings WHERE url IN ({placeholders})",
                candidate_urls,
            )
        }
        return [l for l in listings if l["url"] not in seen]

    def mark_seen(self, listings: list[dict]) -> None:
        """
        Insert listings into the database.

        Called immediately after find_new() so that even if the process
        crashes before notifications are sent, we don't re-notify on restart.
        Each listing is inserted in its own transaction — a failure on one
        does not roll back the others.
        """
        now = _utcnow()
        for listing in listings:
            try:
                self._conn.execute(
                    """
                    INSERT OR IGNORE INTO listings
                        (url, title, address, district, rooms, size_m2,
                         cold_rent, total_rent, wbs, available, posted,
                         floor, year_built, features, seen_at)
                    VALUES
                        (:url, :title, :address, :district, :rooms, :size_m2,
                         :cold_rent, :total_rent, :wbs, :available, :posted,
                         :floor, :year_built, :features, :seen_at)
                    """,
                    {**listing, "features": json.dumps(listing.get("features", [])), "seen_at": now},
                )
                self._conn.commit()
            except sqlite3.Error as e:
                logger.error(f"Failed to insert listing {listing.get('url')}: {e}")

    def log_filter_result(
        self,
        listing:         dict,
        filter_result:   FilterResult,
        priority_result: Optional[PriorityResult] = None,
    ) -> None:
        """
        Write one row to filter_results for audit / later admin queries.

        Call this for every new listing regardless of whether it passed or was
        blocked — the full history is what makes the audit log useful.
        """
        try:
            self._conn.execute(
                """
                INSERT INTO filter_results
                    (url, seen_at, passed, block_reason, priority, score, reasons)
                VALUES
                    (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    listing["url"],
                    _utcnow(),
                    1 if filter_result.passed else 0,
                    filter_result.reason if not filter_result.passed else None,
                    priority_result.label   if priority_result else None,
                    priority_result.score   if priority_result else None,
                    json.dumps(priority_result.reasons) if priority_result else None,
                ),
            )
            self._conn.commit()
        except sqlite3.Error as e:
            logger.error(f"Failed to log filter result for {listing.get('url')}: {e}")

    def save(self) -> None:
        """
        No-op — kept for interface compatibility with the old JSON store.
        SQLite writes are committed immediately after each insert.
        """

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]

    def close(self) -> None:
        """Close the database connection. Called on shutdown."""
        self._conn.close()
        logger.debug("Store connection closed")

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        # Write-Ahead Logging: faster writes, safe concurrent reads for future API
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _migrate(self) -> None:
        """
        Create tables on first run; apply incremental migrations thereafter.
        The current schema version is stored in PRAGMA user_version so each
        migration block runs exactly once, in order, and is never repeated.
        """
        current = self._conn.execute("PRAGMA user_version").fetchone()[0]
        logger.debug(f"DB schema version: {current}, target: {_SCHEMA_VERSION}")

        if current < 1:
            logger.info("Applying schema migration v1 — creating tables")
            self._conn.executescript("""
                CREATE TABLE IF NOT EXISTS listings (
                    url         TEXT PRIMARY KEY,
                    title       TEXT,
                    address     TEXT,
                    district    TEXT,
                    rooms       REAL,
                    size_m2     REAL,
                    cold_rent   REAL,
                    total_rent  REAL,
                    wbs         TEXT,
                    available   TEXT,
                    posted      TEXT,
                    floor       TEXT,
                    year_built  INTEGER,
                    features    TEXT,
                    seen_at     TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_listings_district
                    ON listings(district);
                CREATE INDEX IF NOT EXISTS idx_listings_cold_rent
                    ON listings(cold_rent);
                CREATE INDEX IF NOT EXISTS idx_listings_seen_at
                    ON listings(seen_at);

                CREATE TABLE IF NOT EXISTS filter_results (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    url          TEXT NOT NULL REFERENCES listings(url),
                    seen_at      TEXT NOT NULL,
                    passed       INTEGER NOT NULL,
                    block_reason TEXT,
                    priority     TEXT,
                    score        INTEGER,
                    reasons      TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_filter_results_url
                    ON filter_results(url);
                CREATE INDEX IF NOT EXISTS idx_filter_results_passed
                    ON filter_results(passed);

                PRAGMA user_version = 1;
            """)
            self._conn.commit()
            logger.info("Schema migration v1 complete")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _utcnow() -> str:
    """Return current UTC time as an ISO 8601 string."""
    return datetime.now(timezone.utc).isoformat()
