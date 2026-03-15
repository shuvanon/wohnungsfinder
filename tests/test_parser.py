"""
tests/test_parser.py — Tests for scraper/parser.py (Livewire snapshot parser)

The parser now reads structured JSON from wire:snapshot attributes rather than
scraping HTML text. Tests build minimal synthetic snapshot HTML that mirrors
the real site's Livewire component structure.
"""

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
from scraper.parser import (
    _parse_german_float,
    _parse_year,
    _features_from_attribute_ids,
    _get_snapshots,
    _parse_listing_snapshots,
    parse_listings,
)


# ── Snapshot HTML builder ──────────────────────────────────────────────────────

def _snap_html(name: str, data: dict, memo_extras: dict = None, tag: str = "div", classes: str = "") -> str:
    """Build a minimal wire:snapshot HTML element."""
    memo = {
        "id": f"test-{name[-8:]}",
        "name": name,
        "path": "wohnungsfinder",
        "method": "GET",
        "release": "a-a-a",
        "children": [],
        "scripts": [],
        "assets": [],
        "errors": [],
        "locale": "de",
    }
    if memo_extras:
        memo.update(memo_extras)
    snapshot = json.dumps({
        "data": data,
        "memo": memo,
        "checksum": "abc123",
    })
    class_attr = f' class="{classes}"' if classes else ""
    # Escape for HTML attribute
    snapshot_escaped = snapshot.replace('"', "&quot;")
    return f'<{tag}{class_attr} wire:snapshot="{snapshot_escaped}"></{tag}>'


def _make_listing_html(
    item_id: int = 1001,
    deeplink: str = "https://www.gewobag.de/test",
    title: str = "Schöne Wohnung",
    rooms: str = "2,0",
    area: str = "58,50",
    rent_net: str = "650,00",
    rent_gross: float = 810.0,
    occupation_date: str = "01.05.2026",
    created_at: str = "2026-03-14T10:00:00.000000Z",
    construction_year: str = "1990",
    level: int = 2,
    levels_total: int = 5,
    street: str = "Teststraße",
    number: str = "42",
    zip_code: str = "10365",
    district: str = "Lichtenberg",
    attr_ids: list = None,
) -> str:
    """Build the cluster of snapshots that represents one listing."""
    if attr_ids is None:
        attr_ids = [5, 9, 17]  # Balkon, Aufzug, Keller

    item_data = {
        "item": [
            {
                "id": item_id,
                "title": title,
                "objectId": f"obj-{item_id}",
                "deeplink": deeplink,
                "rooms": rooms,
                "area": area,
                "occupationDate": occupation_date,
                "level": level,
                "levelsTotal": levels_total,
                "bathrooms": 1,
                "constructionYear": construction_year,
                "rentNet": rent_net,
                "extraCosts": "150,00",
                "rentGross": rent_gross,
                "createdAt": created_at,
                "hasWbs": ("wbs" in title.lower()),
                "attributes": [[{"id": 1, "flat_id": item_id, "flat_attribute_id": aid} for aid in attr_ids], {"s": "arr"}],
                "company": [{"name": "Test GmbH"}, {"s": "arr"}],
            },
            {"s": "arr"},
        ]
    }

    title_data = {
        "itemId": item_id,
        "rooms": rooms,
        "area": area,
        "rentNet": rent_net,
        "street": street,
        "number": number,
        "zipCode": zip_code,
        "district": district,
        "createdAt": created_at,
        "collapseEnabled": True,
    }

    attr_data = {
        "iconMap": [{"5": "fa-window-restore", "9": "fa-elevator", "17": "fa-box-archive"}, {"s": "arr"}],
        "itemAttributes": [attr_ids, {"s": "arr"}],
        "data": [
            [[{"id": 1, "flat_id": item_id, "flat_attribute_id": aid} for aid in attr_ids], {"s": "arr"}],
            {"s": "arr"},
        ],
    }

    return (
        _snap_html("apartment-finder.item.apartment-item", item_data, tag="div", classes="mb-3") +
        _snap_html("apartment-finder.item.partials.collapsible-apartment-title", title_data, tag="span", classes="block") +
        _snap_html("apartment-finder.item.partials.attributes", attr_data, tag="div", classes="text-sm mb-2 grid")
    )


def _make_page(listings_html: str, results_count: int = 10) -> BeautifulSoup:
    """Wrap listing snapshots in a minimal page with results-counter snapshot."""
    counter = _snap_html(
        "apartment-finder.partials.results-counter",
        {"resultsCount": results_count},
    )
    html = f"<html><body>{counter}{listings_html}</body></html>"
    return BeautifulSoup(html, "lxml")


# ── TestParseGermanFloat ───────────────────────────────────────────────────────

class TestParseGermanFloat(unittest.TestCase):

    def test_german_format(self):
        self.assertAlmostEqual(_parse_german_float("1.234,56"), 1234.56)

    def test_plain_number(self):
        self.assertAlmostEqual(_parse_german_float("650,00"), 650.0)

    def test_no_decimals(self):
        self.assertEqual(_parse_german_float("900"), 900.0)

    def test_empty_string(self):
        self.assertIsNone(_parse_german_float(""))

    def test_none_input(self):
        self.assertIsNone(_parse_german_float(None))

    def test_non_numeric(self):
        self.assertIsNone(_parse_german_float("unbekannt"))


# ── TestParseYear ──────────────────────────────────────────────────────────────

class TestParseYear(unittest.TestCase):

    def test_four_digit_year(self):
        self.assertEqual(_parse_year("1930"), 1930)

    def test_year_in_sentence(self):
        self.assertEqual(_parse_year("Gebaut im Jahr 2024"), 2024)

    def test_no_year(self):
        self.assertIsNone(_parse_year("unbekannt"))

    def test_empty(self):
        self.assertIsNone(_parse_year(""))

    def test_partial_year_ignored(self):
        self.assertIsNone(_parse_year("Zimmer 123"))

    def test_integer_input(self):
        self.assertEqual(_parse_year(2025), 2025)


# ── TestWbsFromHasWbsField ────────────────────────────────────────────────────

class TestWbsFromHasWbsField(unittest.TestCase):
    """WBS is now read directly from the hasWbs boolean field in the snapshot."""

    def _listing_with_wbs(self, has_wbs: bool) -> dict:
        html = _make_listing_html(
            title="WBS Wohnung" if has_wbs else "Freie Wohnung",
            item_id=1,
        )
        snaps = _get_snapshots(BeautifulSoup(html, "lxml"))
        listings = _parse_listing_snapshots(snaps)
        return listings[0] if listings else {}

    def test_has_wbs_true_returns_erforderlich(self):
        listing = self._listing_with_wbs(True)
        self.assertEqual(listing["wbs"], "erforderlich")

    def test_has_wbs_false_returns_nicht_erforderlich(self):
        listing = self._listing_with_wbs(False)
        self.assertEqual(listing["wbs"], "nicht erforderlich")


# ── TestFeaturesFromAttributeIds ──────────────────────────────────────────────

class TestFeaturesFromAttributeIds(unittest.TestCase):

    def test_known_ids_mapped(self):
        features = _features_from_attribute_ids([5, 9, 17])
        self.assertIn("Balkon", features)
        self.assertIn("Aufzug", features)
        self.assertIn("Keller", features)

    def test_unknown_id_ignored(self):
        features = _features_from_attribute_ids([999])
        self.assertEqual(features, [])

    def test_empty_list(self):
        self.assertEqual(_features_from_attribute_ids([]), [])

    def test_no_duplicates(self):
        # IDs 10 and 11 both map to Stellplatz
        features = _features_from_attribute_ids([10, 11])
        self.assertEqual(features.count("Stellplatz"), 1)


# ── TestGetSnapshots ──────────────────────────────────────────────────────────

class TestGetSnapshots(unittest.TestCase):

    def test_extracts_snapshot_data(self):
        html = _snap_html("test.component", {"foo": "bar"})
        soup = BeautifulSoup(html, "lxml")
        snaps = _get_snapshots(soup)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]["data"]["foo"], "bar")

    def test_skips_invalid_json(self):
        html = '<div wire:snapshot="not-valid-json"></div>'
        soup = BeautifulSoup(html, "lxml")
        snaps = _get_snapshots(soup)
        self.assertEqual(len(snaps), 0)

    def test_extracts_multiple_snapshots(self):
        html = (
            _snap_html("component.a", {"x": 1}) +
            _snap_html("component.b", {"y": 2})
        )
        soup = BeautifulSoup(html, "lxml")
        snaps = _get_snapshots(soup)
        self.assertEqual(len(snaps), 2)


# ── TestParseListingSnapshots ─────────────────────────────────────────────────

class TestParseListingSnapshots(unittest.TestCase):

    def _get_snaps(self, html: str) -> list[dict]:
        soup = BeautifulSoup(html, "lxml")
        return _get_snapshots(soup)

    def test_parses_single_listing(self):
        html = _make_listing_html()
        snaps = self._get_snaps(html)
        listings = _parse_listing_snapshots(snaps)
        self.assertEqual(len(listings), 1)

    def test_url_extracted(self):
        html = _make_listing_html(deeplink="https://gewobag.de/abc")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertEqual(listing["url"], "https://gewobag.de/abc")

    def test_district_from_title_snapshot(self):
        html = _make_listing_html(district="Pankow")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertEqual(listing["district"], "Pankow")

    def test_address_assembled(self):
        html = _make_listing_html(street="Musterstraße", number="5", zip_code="10115", district="Mitte")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertIn("Musterstraße", listing["address"])
        self.assertIn("10115", listing["address"])
        self.assertIn("Mitte", listing["address"])

    def test_rooms_parsed(self):
        html = _make_listing_html(rooms="3,0")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertEqual(listing["rooms"], 3.0)

    def test_cold_rent_parsed(self):
        html = _make_listing_html(rent_net="750,00")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertAlmostEqual(listing["cold_rent"], 750.0)

    def test_total_rent_parsed(self):
        html = _make_listing_html(rent_gross=950.0)
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertAlmostEqual(listing["total_rent"], 950.0)

    def test_year_built_parsed(self):
        html = _make_listing_html(construction_year="1985")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertEqual(listing["year_built"], 1985)

    def test_features_extracted(self):
        html = _make_listing_html(attr_ids=[5, 9])  # Balkon, Aufzug
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertIn("Balkon", listing["features"])
        self.assertIn("Aufzug", listing["features"])

    def test_wbs_from_title(self):
        html = _make_listing_html(title="Wohnung WBS 160 erforderlich")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertEqual(listing["wbs"], "erforderlich")

    def test_no_wbs_in_title(self):
        html = _make_listing_html(title="Helle Wohnung in Mitte")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertEqual(listing["wbs"], "nicht erforderlich")

    def test_posted_date_formatted(self):
        html = _make_listing_html(created_at="2026-03-14T10:00:00.000000Z")
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertEqual(listing["posted"], "14.03.2026")

    def test_floor_assembled(self):
        html = _make_listing_html(level=3, levels_total=5)
        snaps = self._get_snaps(html)
        listing = _parse_listing_snapshots(snaps)[0]
        self.assertIn("3", listing["floor"])
        self.assertIn("5", listing["floor"])

    def test_no_duplicate_urls(self):
        html = _make_listing_html(item_id=1, deeplink="https://gewobag.de/same") * 2
        snaps = self._get_snaps(html)
        listings = _parse_listing_snapshots(snaps)
        urls = [l["url"] for l in listings]
        self.assertEqual(len(urls), len(set(urls)))

    def test_multiple_listings_parsed(self):
        html = (
            _make_listing_html(item_id=1, deeplink="https://gewobag.de/1") +
            _make_listing_html(item_id=2, deeplink="https://gewobag.de/2")
        )
        snaps = self._get_snaps(html)
        listings = _parse_listing_snapshots(snaps)
        self.assertEqual(len(listings), 2)


# ── TestParseListings ─────────────────────────────────────────────────────────

class TestParseListings(unittest.TestCase):
    """Integration tests for the public parse_listings() function."""

    def test_returns_list(self):
        soup = _make_page(_make_listing_html())
        results = parse_listings(soup)
        self.assertIsInstance(results, list)

    def test_parses_single_listing(self):
        soup = _make_page(_make_listing_html())
        results = parse_listings(soup)
        self.assertEqual(len(results), 1)

    def test_empty_page_returns_empty(self):
        soup = BeautifulSoup("<html><body><p>Keine Angebote</p></body></html>", "lxml")
        results = parse_listings(soup)
        self.assertEqual(results, [])

    def test_no_pagination_without_session(self):
        """Without session, only page 1 is returned (no Livewire calls)."""
        html = _make_listing_html(item_id=1, deeplink="https://gewobag.de/1")
        soup = _make_page(html, results_count=50)
        results = parse_listings(soup, session=None, csrf_token="")
        self.assertEqual(len(results), 1)

    def test_all_required_fields_present(self):
        soup = _make_page(_make_listing_html())
        result = parse_listings(soup)[0]
        for field in ["url", "title", "address", "district", "rooms", "size_m2",
                      "cold_rent", "total_rent", "wbs", "available", "posted",
                      "floor", "year_built", "features"]:
            self.assertIn(field, result, f"Field '{field}' missing from listing")


if __name__ == "__main__":
    unittest.main()
