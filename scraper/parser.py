"""
parser.py — Livewire snapshot → structured listing dicts.

The inberlinwohnen.de Wohnungsfinder is built with Livewire v3 (Laravel).
Each page renders 10 listings as Livewire component snapshots embedded in
wire:snapshot attributes. The full listing data is in these JSON blobs —
no HTML text scraping needed.

Parsing strategy:
  1. On the initial page, extract:
     - The main apartment-finder component snapshot (for pagination)
     - All apartment-finder.item.list-view snapshots (the 10 listings)
     - The shared iconMap (attribute ID → feature name)
  2. For pages 2–N, call the Livewire /update endpoint (via fetcher) and
     parse the returned HTML fragments the same way.
  3. For each listing snapshot, pair it with its
     apartment-finder.item.partials.collapsible-apartment-title snapshot
     to get the structured address fields (street, number, zipCode, district).

Feature ID → name mapping (from iconMap in every attributes snapshot):
    3  → Stellplatz (person-circle-plus = parking/concierge)
    4  → Loggia (window-maximize)
    5  → Balkon (window-restore)
    6  → Barrierefrei (person-walking-with-cane)
    7  → Parkett (shoe-prints)
    9  → Aufzug (elevator)
    10 → Stellplatz (square-parking)
    11 → Tiefgarage (square-parking)
    12 → Einbauküche (right-to-bracket)
    13 → Dusche (shower)
    14 → Badewanne (bath)
    15 → Gäste WC (toilet)
    16 → Möbliert (couch)
    17 → Keller (box-archive)
    18 → Garten (leaf)
    19 → Rollstuhlgerecht (wheelchair)
"""

import json
import logging
import math
import re
import time
from typing import Optional

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Human-readable names for flat_attribute_id values
# Derived from the iconMap in apartment-finder.item.partials.attributes snapshots
_ATTRIBUTE_NAMES: dict[int, str] = {
    3:  "Stellplatz",
    4:  "Loggia",
    5:  "Balkon",
    6:  "Barrierefrei",
    7:  "Parkett",
    8:  "WBS-Schein",
    9:  "Aufzug",
    10: "Stellplatz",
    11: "Tiefgarage",
    12: "Einbauküche",
    13: "Dusche",
    14: "Badewanne",
    15: "Gäste WC",
    16: "Möbliert",
    17: "Keller",
    18: "Garten",
    19: "Rollstuhlgerecht",
}

_ITEMS_PER_PAGE = 10


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_german_float(text: str) -> Optional[float]:
    """'1.234,56'  →  1234.56"""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,]", "", str(text)).replace(",", ".")
    if cleaned in ("", "."):
        return None
    # Guard: if there are multiple dots, only keep the last (e.g. "1.234.56" → bad)
    parts = cleaned.split(".")
    if len(parts) > 2:
        cleaned = "".join(parts[:-1]) + "." + parts[-1]
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_year(text) -> Optional[int]:
    """Extract a 4-digit year from a string or number."""
    if text is None:
        return None
    match = re.search(r"\b(1[89]\d{2}|20[012]\d)\b", str(text))
    return int(match.group(1)) if match else None


def _extract_wbs(title: str) -> str:
    """
    Derive WBS status from listing title.
    If 'WBS' appears in the title → 'erforderlich', else → 'nicht erforderlich'.
    """
    if title and "wbs" in title.lower():
        return "erforderlich"
    return "nicht erforderlich"


def _features_from_attribute_ids(attribute_ids: list[int]) -> list[str]:
    """Map flat_attribute_id list to human-readable feature names."""
    seen = set()
    features = []
    for aid in attribute_ids:
        name = _ATTRIBUTE_NAMES.get(aid)
        if name and name not in seen:
            seen.add(name)
            features.append(name)
    return features


# ── Snapshot extraction ────────────────────────────────────────────────────────

def _get_snapshots(soup: BeautifulSoup) -> list[dict]:
    """
    Extract and parse all wire:snapshot JSON blobs from a BeautifulSoup tree.
    Returns list of parsed dicts, skipping any that fail JSON parsing.
    """
    snapshots = []
    for el in soup.find_all(attrs={"wire:snapshot": True}):
        raw = el.get("wire:snapshot", "")
        try:
            data = json.loads(raw)
            data["_tag"] = el.name
            data["_classes"] = el.get("class", [])
            snapshots.append(data)
        except json.JSONDecodeError:
            pass
    return snapshots


def _find_main_component(snapshots: list[dict]) -> Optional[dict]:
    """
    Find the root apartment-finder component snapshot.
    This is the one with itemsPerPage in its data — used for pagination.
    """
    for snap in snapshots:
        memo = snap.get("memo", {})
        if memo.get("name") == "apartment-finder" or (
            isinstance(snap.get("data"), dict)
            and "itemsPerPage" in snap.get("data", {})
        ):
            return snap
    return None


def _parse_listing_snapshots(snapshots: list[dict]) -> list[dict]:
    """
    Extract structured listing dicts from a list of Livewire snapshots.

    Each listing is represented by a cluster of snapshots:
      - apartment-finder.item.list-view  → item data (rent, rooms, area, title, etc.)
      - apartment-finder.item.partials.collapsible-apartment-title → address fields
      - apartment-finder.item.partials.attributes → feature attribute IDs
    """
    # Index snapshots by name for easy lookup
    by_name: dict[str, list[dict]] = {}
    for snap in snapshots:
        name = snap.get("memo", {}).get("name", "")
        by_name.setdefault(name, []).append(snap)

    list_views = by_name.get("apartment-finder.item.list-view", [])
    titles     = by_name.get("apartment-finder.item.partials.collapsible-apartment-title", [])
    attributes = by_name.get("apartment-finder.item.partials.attributes", [])

    # Build lookup dicts by itemId / flatId
    title_by_id: dict[int, dict] = {}
    for snap in titles:
        d = snap.get("data", {})
        item_id = d.get("itemId")
        if item_id:
            title_by_id[item_id] = d

    attr_by_id: dict[int, list[int]] = {}
    for snap in attributes:
        d = snap.get("data", {})
        # itemAttributes is [[id1, id2, ...], {"s": "arr"}]
        raw_attrs = d.get("itemAttributes", [])
        if raw_attrs and isinstance(raw_attrs[0], list):
            attr_ids = raw_attrs[0]
        else:
            attr_ids = [x for x in raw_attrs if isinstance(x, int)]
        # Associate with item via flatId found in data items
        items_data = d.get("data", [])
        if items_data and isinstance(items_data[0], list):
            for item_entry in items_data[0]:
                if isinstance(item_entry, list) and item_entry:
                    first = item_entry[0]
                    if isinstance(first, dict) and "flat_id" in first:
                        attr_by_id[first["flat_id"]] = attr_ids
                        break

    listings = []
    seen_urls: set[str] = set()

    for snap in list_views:
        d = snap.get("data", {})
        raw_item = d.get("item", [])

        # item is [dict, {"s": "arr"}]
        if not raw_item or not isinstance(raw_item[0], dict):
            continue
        item = raw_item[0]

        url = item.get("deeplink", "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)

        item_id = item.get("id")

        # Get address fields from title snapshot
        title_data = title_by_id.get(item_id, {})
        street   = title_data.get("street", "")
        number   = title_data.get("number", "")
        zip_code = title_data.get("zipCode", "")
        district = title_data.get("district", "")
        address  = f"{street} {number}, {zip_code}, {district}".strip(", ")

        # Features from attribute IDs
        attr_ids = attr_by_id.get(item_id, [])
        features = _features_from_attribute_ids(attr_ids)

        title    = item.get("title", "")
        posted   = item.get("createdAt", "")
        # Convert ISO timestamp to DD.MM.YYYY
        if posted and "T" in posted:
            try:
                d_part = posted.split("T")[0]
                y, mo, day = d_part.split("-")
                posted = f"{day}.{mo}.{y}"
            except Exception:
                pass

        floor_level  = item.get("level")
        floor_total  = item.get("levelsTotal")
        floor = f"{floor_level} von (insg. {floor_total})" if floor_level is not None else ""

        listings.append({
            "url":        url,
            "title":      title,
            "address":    address,
            "district":   district,
            "rooms":      _parse_german_float(item.get("rooms", "")),
            "size_m2":    _parse_german_float(item.get("area", "")),
            "cold_rent":  _parse_german_float(item.get("rentNet", "")),
            "total_rent": float(item.get("rentGross")) if item.get("rentGross") else None,
            "wbs":        _extract_wbs(title),
            "available":  item.get("occupationDate", ""),
            "posted":     posted,
            "floor":      floor,
            "year_built": _parse_year(item.get("constructionYear")),
            "features":   features,
            "raw_text":   "",
        })

    return listings


# ── Public interface ───────────────────────────────────────────────────────────

def parse_listings(soup: BeautifulSoup, session=None, csrf_token: str = "") -> list[dict]:
    """
    Extract all apartment listings from the Wohnungsfinder.

    On the initial soup, parses page 1 from snapshots.
    If session and csrf_token are provided, paginates through all remaining
    pages via the Livewire /update endpoint.

    Args:
        soup:        BeautifulSoup of the initial page load
        session:     requests.Session from fetcher (for pagination)
        csrf_token:  CSRF token from the initial page (for pagination)

    Returns:
        List of listing dicts, deduplicated by URL.
    """
    from scraper.fetcher import fetch_livewire_page  # avoid circular at module level

    all_listings: list[dict] = []
    seen_urls: set[str] = set()

    # ── Page 1: parse from initial HTML ───────────────────────────────────
    snapshots = _get_snapshots(soup)
    page1 = _parse_listing_snapshots(snapshots)
    for listing in page1:
        if listing["url"] not in seen_urls:
            seen_urls.add(listing["url"])
            all_listings.append(listing)

    logger.debug(f"Page 1: {len(page1)} listings")

    # ── Determine total pages ──────────────────────────────────────────────
    # Find total count from results-counter snapshot
    total_listings = 0
    for snap in snapshots:
        if snap.get("memo", {}).get("name") == "apartment-finder.partials.results-counter":
            total_listings = snap.get("data", {}).get("resultsCount", 0)
            break

    if total_listings == 0 or not session or not csrf_token:
        if total_listings == 0:
            logger.warning("Could not determine total listing count — only page 1 available")
        logger.info(f"Parsed {len(all_listings)} listings total (page 1 only)")
        return all_listings

    total_pages = math.ceil(total_listings / _ITEMS_PER_PAGE)
    logger.info(f"Total: {total_listings} listings across {total_pages} pages")

    # ── Find main component for pagination ────────────────────────────────
    main_component = _find_main_component(snapshots)
    if not main_component:
        logger.warning("Main apartment-finder component not found — cannot paginate")
        return all_listings

    component_id = main_component.get("memo", {}).get("id", "")
    # We need the raw snapshot string (not the parsed dict) for the Livewire call
    # Re-extract from the soup
    main_snapshot_raw = ""
    main_checksum = main_component.get("checksum", "")
    for el in soup.find_all(attrs={"wire:snapshot": True}):
        raw = el.get("wire:snapshot", "")
        try:
            parsed = json.loads(raw)
            if parsed.get("memo", {}).get("id") == component_id:
                main_snapshot_raw = raw
                break
        except Exception:
            pass

    if not main_snapshot_raw:
        logger.warning("Could not extract main component snapshot string")
        return all_listings

    # ── Pages 2–N via Livewire /update ────────────────────────────────────
    current_snapshot = main_snapshot_raw
    current_checksum = main_checksum

    for page in range(2, total_pages + 1):
        logger.debug(f"Fetching page {page}/{total_pages}")
        time.sleep(0.5)  # be polite

        response = fetch_livewire_page(
            session=session,
            csrf_token=csrf_token,
            component_id=component_id,
            snapshot=current_snapshot,
            checksum=current_checksum,
            page=page,
        )

        if not response:
            logger.warning(f"Empty response for page {page} — stopping pagination")
            break

        # Livewire returns HTML fragments in components[0].effects.html
        components = response.get("components", [])
        if not components:
            logger.warning(f"No components in Livewire response for page {page}")
            break

        component_response = components[0]

        # Update snapshot for next iteration (Livewire returns updated state)
        new_snapshot = component_response.get("snapshot", "")
        if new_snapshot:
            current_snapshot = new_snapshot
            try:
                current_checksum = json.loads(new_snapshot).get("checksum", "")
            except Exception:
                pass

        # Parse listings from the HTML fragment
        effects = component_response.get("effects", {})
        html_fragment = effects.get("html", "")
        if not html_fragment:
            logger.warning(f"No HTML in Livewire response for page {page}")
            break

        page_soup = BeautifulSoup(html_fragment, "lxml")
        page_snapshots = _get_snapshots(page_soup)
        page_listings = _parse_listing_snapshots(page_snapshots)

        new_count = 0
        for listing in page_listings:
            if listing["url"] not in seen_urls:
                seen_urls.add(listing["url"])
                all_listings.append(listing)
                new_count += 1

        logger.debug(f"Page {page}: {new_count} new listings")

        if not page_listings:
            logger.warning(f"Page {page} returned no listings — stopping early")
            break

    logger.info(f"Parsed {len(all_listings)} listings total across {total_pages} pages")
    return all_listings
