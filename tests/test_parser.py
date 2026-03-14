"""
tests/test_parser.py — Tests for scraper/parser.py

Tests the two things most likely to break:
  1. District resolution logic (postcode map, name extraction, unknown codes)
  2. HTML card parsing using minimal synthetic HTML that mirrors the real site
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from bs4 import BeautifulSoup
from scraper.parser import (
    _district_from_address,
    _parse_float,
    _parse_year,
    parse_listings,
)
from tests.fixtures import POSTCODE_ONLY_LISTING, UNKNOWN_POSTCODE_LISTING


class TestParseFloat(unittest.TestCase):

    def test_german_format(self):
        self.assertAlmostEqual(_parse_float("1.234,56 €"), 1234.56)

    def test_plain_number(self):
        self.assertAlmostEqual(_parse_float("540,88"), 540.88)

    def test_no_decimals(self):
        self.assertEqual(_parse_float("900 €"), 900.0)

    def test_empty_string(self):
        self.assertIsNone(_parse_float(""))

    def test_none_input(self):
        self.assertIsNone(_parse_float(None))

    def test_non_numeric(self):
        self.assertIsNone(_parse_float("unbekannt"))


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
        # 3-digit numbers should not match
        self.assertIsNone(_parse_year("Zimmer 123"))


class TestDistrictFromAddress(unittest.TestCase):
    """
    District resolution has three paths:
      1. Name is explicit in the last comma segment
      2. Postcode lookup (name missing, but postcode known)
      3. Unknown postcode → empty string + warning logged
    """

    def test_district_in_address(self):
        addr = "Siegfriedstraße 21A, 10365, Lichtenberg"
        self.assertEqual(_district_from_address(addr), "Lichtenberg")

    def test_district_hyphenated(self):
        addr = "Singerstraße 83, 10243, Friedrichshain-Kreuzberg"
        self.assertEqual(_district_from_address(addr), "Friedrichshain-Kreuzberg")

    def test_postcode_only_resolves_to_district(self):
        # 10437 → Pankow
        addr = POSTCODE_ONLY_LISTING["address"]  # "Lychener Straße 61, 10437"
        result = _district_from_address(addr)
        self.assertEqual(result, "Pankow")

    def test_known_postcode_reinickendorf(self):
        self.assertEqual(_district_from_address("Wickeder Straße 6B, 13507"), "Reinickendorf")

    def test_known_postcode_marzahn(self):
        self.assertEqual(_district_from_address("Wittenberger Straße 40, 12689"), "Marzahn-Hellersdorf")

    def test_unknown_postcode_returns_empty(self):
        addr = UNKNOWN_POSTCODE_LISTING["address"]
        result = _district_from_address(addr)
        self.assertEqual(result, "")

    def test_empty_address(self):
        self.assertEqual(_district_from_address(""), "")

    def test_no_postcode_no_name(self):
        self.assertEqual(_district_from_address("Irgendwo"), "")


class TestParseListings(unittest.TestCase):
    """
    Feed synthetic HTML that mirrors the real site structure and verify
    that parse_listings extracts the right fields.
    """

    def _make_html(self, listings: list[dict]) -> BeautifulSoup:
        """Build minimal HTML containing one card per listing dict."""
        cards = ""
        for l in listings:
            features_html = "".join(f"<li>{f}</li>" for f in l.get("features", []))
            cards += f"""
            <div class="wf-item">
              <h3>{l['title']}</h3>
              <dl>
                <dt>Adresse</dt><dd>{l['address']}</dd>
                <dt>Zimmeranzahl</dt><dd>{str(l['rooms']).replace('.', ',')}</dd>
                <dt>Wohnfläche</dt><dd>{l['size_m2']} m²</dd>
                <dt>Kaltmiete</dt><dd>{str(l['cold_rent']).replace('.', ',')} €</dd>
                <dt>Gesamtmiete</dt><dd>{str(l['total_rent']).replace('.', ',')} €</dd>
                <dt>WBS</dt><dd>{l['wbs']}</dd>
                <dt>Bezugsfertig ab</dt><dd>{l.get('available', '')}</dd>
                <dt>Eingestellt am</dt><dd>{l.get('posted', '')}</dd>
                <dt>Etage</dt><dd>{l.get('floor', '')}</dd>
                <dt>Baujahr</dt><dd>{l.get('year_built', '')}</dd>
              </dl>
              <ul>{features_html}</ul>
              <a href="{l['url']}">Alle Details</a>
            </div>
            """
        return BeautifulSoup(f"<html><body>{cards}</body></html>", "lxml")

    def test_parses_single_listing(self):
        from tests.fixtures import GOOD_LISTING
        soup = self._make_html([GOOD_LISTING])
        results = parse_listings(soup)
        self.assertEqual(len(results), 1)

    def test_parses_multiple_listings(self):
        from tests.fixtures import GOOD_LISTING, WBS_LISTING, EXPENSIVE_LISTING
        soup = self._make_html([GOOD_LISTING, WBS_LISTING, EXPENSIVE_LISTING])
        results = parse_listings(soup)
        self.assertEqual(len(results), 3)

    def test_url_extracted(self):
        from tests.fixtures import GOOD_LISTING
        soup = self._make_html([GOOD_LISTING])
        result = parse_listings(soup)[0]
        self.assertEqual(result["url"], GOOD_LISTING["url"])

    def test_rooms_parsed_as_float(self):
        from tests.fixtures import GOOD_LISTING
        soup = self._make_html([GOOD_LISTING])
        result = parse_listings(soup)[0]
        self.assertEqual(result["rooms"], 2.0)

    def test_rent_parsed_as_float(self):
        from tests.fixtures import GOOD_LISTING
        soup = self._make_html([GOOD_LISTING])
        result = parse_listings(soup)[0]
        self.assertIsNotNone(result["cold_rent"])
        self.assertIsInstance(result["cold_rent"], float)

    def test_district_resolved_for_postcode_only_address(self):
        from tests.fixtures import POSTCODE_ONLY_LISTING
        soup = self._make_html([POSTCODE_ONLY_LISTING])
        result = parse_listings(soup)[0]
        # Parser should resolve 10437 → Pankow
        self.assertEqual(result["district"], "Pankow")

    def test_features_extracted(self):
        from tests.fixtures import GOOD_LISTING
        soup = self._make_html([GOOD_LISTING])
        result = parse_listings(soup)[0]
        self.assertIn("Balkon", result["features"])

    def test_empty_page_returns_empty_list(self):
        soup = BeautifulSoup("<html><body><p>No listings today</p></body></html>", "lxml")
        results = parse_listings(soup)
        self.assertEqual(results, [])

    def test_no_duplicate_urls(self):
        """Cards with the same URL should only appear once."""
        from tests.fixtures import GOOD_LISTING
        soup = self._make_html([GOOD_LISTING, GOOD_LISTING])
        results = parse_listings(soup)
        urls = [r["url"] for r in results]
        self.assertEqual(len(urls), len(set(urls)))

    def test_year_built_parsed(self):
        from tests.fixtures import GOOD_LISTING
        soup = self._make_html([GOOD_LISTING])
        result = parse_listings(soup)[0]
        self.assertEqual(result["year_built"], 1930)


if __name__ == "__main__":
    unittest.main()
