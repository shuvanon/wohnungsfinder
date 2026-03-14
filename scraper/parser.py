"""
parser.py — HTML → structured listing dicts.

Parses every apartment card on the Wohnungsfinder page into a clean dict.
District resolution uses a two-step approach:
  1. Read the district directly from the parsed address field (most reliable).
  2. Fall back to a full Berlin postcode→Bezirk lookup when no name is present.

If neither step resolves a district, the field is left as an empty string and
a warning is logged so you can investigate and improve coverage.
"""

import json
import logging
import re
from pathlib import Path
from typing import Optional

from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# Path to the postcode mapping shipped with the project
_POSTCODE_MAP_PATH = Path(__file__).parent.parent / "data" / "berlin_postcodes.json"
_postcode_map: dict[str, str] = {}


def _load_postcode_map() -> dict[str, str]:
    """Load postcode→district mapping once, on first use."""
    global _postcode_map
    if not _postcode_map:
        try:
            with open(_POSTCODE_MAP_PATH) as f:
                raw = json.load(f)
            # Strip the comment key if present
            _postcode_map = {k: v for k, v in raw.items() if not k.startswith("_")}
            logger.debug(f"Loaded {len(_postcode_map)} postcode entries")
        except FileNotFoundError:
            logger.error(f"Postcode map not found at {_POSTCODE_MAP_PATH}")
    return _postcode_map


# ── Helpers ────────────────────────────────────────────────────────────────────

def _parse_float(text: str) -> Optional[float]:
    """'1.234,56 €'  →  1234.56"""
    if not text:
        return None
    cleaned = re.sub(r"[^\d,]", "", text).replace(",", ".")
    # Guard against strings like '.' after cleaning
    if cleaned in ("", "."):
        return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _parse_year(text: str) -> Optional[int]:
    """Extract a 4-digit year from arbitrary text."""
    if not text:
        return None
    match = re.search(r"\b(1[89]\d{2}|20[012]\d)\b", text)
    return int(match.group(1)) if match else None


def _dt_value(container: Tag, label: str) -> str:
    """
    Find a <dt> whose text contains `label` (case-insensitive) and return
    the text of its following <dd>.  Returns '' if not found.
    """
    for dt in container.select("dt"):
        if label.lower() in dt.get_text(strip=True).lower():
            dd = dt.find_next_sibling("dd")
            return dd.get_text(" ", strip=True) if dd else ""
    return ""


def _extract_features(container: Tag, raw_text: str) -> list[str]:
    """
    Collect feature labels (Balkon, Aufzug, etc.).
    The site renders these as standalone text nodes or small tags — we scan
    for known keywords rather than relying on a specific CSS class.
    """
    known_features = [
        "Balkon", "Loggia", "Terrasse", "Garten",
        "Aufzug", "Barrierefrei", "Rollstuhlgerecht",
        "Badewanne", "Dusche", "Keller", "Auto-Stellplatz", "Gäste WC",
    ]
    found = []
    lower_text = raw_text.lower()
    for feature in known_features:
        if feature.lower() in lower_text:
            found.append(feature)
    return found


# ── District resolution ────────────────────────────────────────────────────────

def _district_from_address(address: str) -> str:
    """
    Try to extract the Bezirk from a formatted address string.

    The site's address format is typically:
        "Straßenname NR, POSTCODE, Bezirk"
    e.g. "Wickeder Straße 6B, 13507, Reinickendorf"

    Strategy:
      1. Take the last comma-separated segment — often the Bezirk name directly.
      2. If that segment is purely numeric (just a postcode) or empty, look up
         the postcode in the Berlin postcode map.
      3. Log a warning if resolution fails so the map can be extended.
    """
    if not address:
        return ""

    parts = [p.strip() for p in address.split(",")]

    # Last segment is usually the district name — but only trust it when
    # there are multiple comma segments (i.e. a full address, not a bare word)
    last = parts[-1] if parts else ""
    if len(parts) >= 2 and last and not last.isdigit() and len(last) > 3:
        return last  # e.g. "Reinickendorf" — we're done

    # Fallback: find the postcode in the address and look it up
    postcode_match = re.search(r"\b(\d{5})\b", address)
    if postcode_match:
        postcode = postcode_match.group(1)
        district = _load_postcode_map().get(postcode, "")
        if district:
            return district
        else:
            logger.warning(
                f"Unknown postcode '{postcode}' in address '{address}'. "
                f"Add it to data/berlin_postcodes.json."
            )

    # Could not resolve
    logger.warning(f"Could not determine district from address: '{address}'")
    return ""


# ── Card parsing ───────────────────────────────────────────────────────────────

def _parse_card(container: Tag) -> Optional[dict]:
    """
    Parse one apartment card into a dict.  Returns None if no detail URL
    can be found (used to skip non-listing elements).
    """
    # The "Alle Details" link is our unique identifier for this listing
    link = container.find("a", href=True, string=re.compile(r"Alle Details", re.I))
    if not link:
        # Broader fallback: any link pointing to a known provider domain
        link = container.find("a", href=re.compile(
            r"(gewobag|degewo|howoge|gesobau|stadtundland|wbm|berlinovo)\.de", re.I
        ))
    if not link:
        return None

    url = link["href"].strip()

    # Full text of the card for keyword searches
    raw_text = container.get_text(" ", strip=True)

    address  = _dt_value(container, "Adresse")
    district = _district_from_address(address)

    # Title: first heading inside the card
    title_tag = container.select_one("h2, h3, h4, .wf-title, .title, p strong")
    title = title_tag.get_text(strip=True) if title_tag else ""

    return {
        "url":        url,
        "title":      title,
        "address":    address,
        "district":   district,
        "rooms":      _parse_float(_dt_value(container, "Zimmeranzahl") or _dt_value(container, "Zimmer")),
        "size_m2":    _parse_float(_dt_value(container, "Wohnfläche")),
        "cold_rent":  _parse_float(_dt_value(container, "Kaltmiete")),
        "total_rent": _parse_float(_dt_value(container, "Gesamtmiete")),
        "wbs":        _dt_value(container, "WBS"),
        "available":  _dt_value(container, "Bezugsfertig"),
        "posted":     _dt_value(container, "Eingestellt"),
        "floor":      _dt_value(container, "Etage"),
        "year_built": _parse_year(_dt_value(container, "Baujahr")),
        "features":   _extract_features(container, raw_text),
        "raw_text":   raw_text,
    }


# ── Public interface ───────────────────────────────────────────────────────────

def parse_listings(soup: BeautifulSoup) -> list[dict]:
    """
    Extract all apartment listings from a Wohnungsfinder page.

    Tries a CSS-selector approach first (targeting known card classes), then
    falls back to walking every "Alle Details" link and climbing the DOM tree
    to find a suitable container with dt/dd pairs.
    """
    listings = []
    seen_urls: set[str] = set()

    # ── Pass 1: target known card wrapper classes ──────────────────────────
    selectors = [
        "div.wf-item",
        "article.wf-item",
        "div[class*='wohnungs']",
        "div[class*='listing']",
        "div[class*='apartment']",
    ]
    cards: list[Tag] = []
    for sel in selectors:
        cards = soup.select(sel)
        if cards:
            logger.debug(f"Pass 1: found {len(cards)} cards via selector '{sel}'")
            break

    for card in cards:
        result = _parse_card(card)
        if result and result["url"] not in seen_urls:
            seen_urls.add(result["url"])
            listings.append(result)

    # ── Pass 2: fallback — anchor-climb if pass 1 found nothing ───────────
    if not listings:
        logger.info("Pass 1 found no cards; falling back to anchor-climb strategy")
        provider_pattern = re.compile(
            r"(gewobag|degewo|howoge|gesobau|stadtundland|wbm|berlinovo)\.de", re.I
        )
        for anchor in soup.find_all("a", href=provider_pattern):
            url = anchor["href"].strip()
            if url in seen_urls:
                continue

            # Climb up the DOM until we find a container with dt/dd pairs
            container = anchor
            for _ in range(8):
                container = container.parent
                if container is None:
                    break
                if container.find("dt"):
                    break
            else:
                continue

            if container is None:
                continue

            result = _parse_card(container)
            if result and result["url"] not in seen_urls:
                seen_urls.add(result["url"])
                listings.append(result)

    logger.info(f"Parsed {len(listings)} listings total")
    return listings
