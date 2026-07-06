"""
api/queries.py — Read-only queries for the listings database.

Opens the SQLite store in query-only mode (`PRAGMA query_only=ON`), so it is
safe to run alongside the scraper's WAL writes and can never modify data.
Returns plain dicts (features deserialized) for the HTTP layer.
"""

import json
import sqlite3

# Columns returned in list responses. detail_text is omitted here (it's large);
# fetch the single-listing endpoint to get it.
_LIST_COLUMNS = (
    "url", "title", "address", "district", "rooms", "size_m2",
    "cold_rent", "total_rent", "wbs", "wbs_tier", "available", "posted",
    "floor", "year_built", "features", "heizkosten", "deposit",
    "energy_class", "heating_type", "pets_allowed", "description_summary",
    "seen_at", "detail_fetched_at",
)


def _connect(db_path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only=ON")  # enforce read-only; WAL-safe
    return conn


def _row_to_dict(row: sqlite3.Row) -> dict:
    d = dict(row)
    feats = d.get("features")
    if isinstance(feats, str):
        try:
            d["features"] = json.loads(feats)
        except (json.JSONDecodeError, TypeError):
            d["features"] = []
    return d


def health(db_path) -> dict:
    conn = _connect(db_path)
    try:
        count = conn.execute("SELECT COUNT(*) FROM listings").fetchone()[0]
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        return {"status": "ok", "listing_count": count, "schema_version": version}
    finally:
        conn.close()


def list_listings(db_path, *, limit=50, offset=0, district=None,
                  min_rent=None, max_rent=None, wbs=None) -> list[dict]:
    cols = ", ".join(_LIST_COLUMNS)
    where, params = [], {}
    if district:
        where.append("district = :district"); params["district"] = district
    if min_rent is not None:
        where.append("total_rent >= :min_rent"); params["min_rent"] = min_rent
    if max_rent is not None:
        where.append("total_rent <= :max_rent"); params["max_rent"] = max_rent
    if wbs:
        where.append("wbs = :wbs"); params["wbs"] = wbs
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    params["limit"], params["offset"] = limit, offset

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"SELECT {cols} FROM listings {clause} "
            f"ORDER BY seen_at DESC LIMIT :limit OFFSET :offset",
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_listing(db_path, url) -> dict | None:
    conn = _connect(db_path)
    try:
        row = conn.execute("SELECT * FROM listings WHERE url = ?", (url,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def list_candidates(db_path, *, limit=50, offset=0, since=None) -> list[dict]:
    """
    Passed listings — the latest filter_results decision per url is passed=1 —
    joined with the datasheet plus priority/score. This is the feed a
    downstream applier consumes.
    """
    cols = ", ".join(f"l.{c}" for c in _LIST_COLUMNS)
    params = {"limit": limit, "offset": offset}
    since_clause = ""
    if since:
        since_clause = "AND l.seen_at > :since"
        params["since"] = since

    conn = _connect(db_path)
    try:
        rows = conn.execute(
            f"""
            SELECT {cols}, f.priority AS priority, f.score AS score
            FROM listings l
            JOIN filter_results f ON f.url = l.url
            WHERE f.id = (SELECT MAX(id) FROM filter_results WHERE url = l.url)
              AND f.passed = 1
              {since_clause}
            ORDER BY l.seen_at DESC
            LIMIT :limit OFFSET :offset
            """,
            params,
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()
