"""
api/server.py — Read-only HTTP API over the listings database.

FastAPI app exposing listings and passed "candidates" as JSON so other tools
(e.g. an auto-applier) can consume them over the network. Read-only — it never
writes to the database. Bind it to your Tailscale IP so it stays private.

Run (dev):   python -m api.server
Run (prod):  uvicorn api.server:app --host <tailscale-ip> --port 8002
"""

from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query

from config.loader import load_config
from api import queries

BASE_DIR = Path(__file__).parent.parent

_cfg = load_config()
_DB_PATH = BASE_DIR / _cfg["scraper"]["store_file"]

app = FastAPI(
    title="Wohnungsfinder API",
    description="Read-only access to scraped Berlin apartment listings.",
    version="1.0",
)


@app.get("/health")
def health():
    """Liveness + row count + schema version."""
    return queries.health(_DB_PATH)


@app.get("/listings")
def listings(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    district: Optional[str] = None,
    min_rent: Optional[float] = None,
    max_rent: Optional[float] = None,
    wbs: Optional[str] = None,
):
    """All listings (datasheet without the bulky detail_text), newest first."""
    return queries.list_listings(
        _DB_PATH, limit=limit, offset=offset, district=district,
        min_rent=min_rent, max_rent=max_rent, wbs=wbs,
    )


@app.get("/listing")
def listing(url: str):
    """A single listing's full datasheet (incl. detail_text), by its URL."""
    result = queries.get_listing(_DB_PATH, url)
    if result is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    return result


@app.get("/candidates")
def candidates(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    since: Optional[str] = None,
):
    """
    Passed listings, newest first — the feed for a downstream applier.
    Pass `since=<ISO seen_at>` to poll only listings newer than last seen.
    """
    return queries.list_candidates(_DB_PATH, limit=limit, offset=offset, since=since)


def main():
    import uvicorn
    api_cfg = _cfg.get("api", {})
    uvicorn.run(app, host=api_cfg.get("host", "127.0.0.1"), port=api_cfg.get("port", 8002))


if __name__ == "__main__":
    main()
