"""
tests/test_detail_fetcher.py — Tests for scraper/detail_fetcher.py

Uses unittest.mock to simulate HTTP responses so no real requests are made.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent))

from scraper.detail_fetcher import fetch_detail_text

_HTML = """
<html><head><title>T</title><style>.x{color:red}</style></head>
<body>
  <script>var noise = 1;</script>
  <h1>Schöne Wohnung</h1>
  <p>Kaltmiete 469,27 €   WBS erforderlich</p>
</body></html>
"""


def _resp(text="", raises=None) -> MagicMock:
    resp = MagicMock()
    resp.text = text
    if raises is not None:
        resp.raise_for_status.side_effect = raises
    return resp


class TestFetchDetailText(unittest.TestCase):

    @patch("scraper.detail_fetcher.requests.get")
    def test_extracts_visible_text(self, mock_get):
        mock_get.return_value = _resp(_HTML)
        text = fetch_detail_text("https://example.de/x")
        self.assertIn("Schöne Wohnung", text)
        self.assertIn("WBS erforderlich", text)

    @patch("scraper.detail_fetcher.requests.get")
    def test_strips_script_and_style(self, mock_get):
        mock_get.return_value = _resp(_HTML)
        text = fetch_detail_text("https://example.de/x")
        self.assertNotIn("noise", text)
        self.assertNotIn("color:red", text)

    @patch("scraper.detail_fetcher.requests.get")
    def test_collapses_whitespace(self, mock_get):
        mock_get.return_value = _resp(_HTML)
        text = fetch_detail_text("https://example.de/x")
        self.assertNotIn("  ", text)  # no double spaces

    @patch("scraper.detail_fetcher.requests.get")
    def test_truncates_to_max_chars(self, mock_get):
        big = "<html><body>" + ("ab " * 5000) + "</body></html>"
        mock_get.return_value = _resp(big)
        text = fetch_detail_text("https://example.de/x", max_chars=100)
        self.assertLessEqual(len(text), 100)

    def test_empty_url_returns_empty(self):
        self.assertEqual(fetch_detail_text(""), "")

    @patch("scraper.detail_fetcher.requests.get")
    def test_http_error_returns_empty(self, mock_get):
        mock_get.return_value = _resp(_HTML, raises=Exception("503"))
        self.assertEqual(fetch_detail_text("https://example.de/x"), "")

    @patch("scraper.detail_fetcher.requests.get")
    def test_connection_error_returns_empty(self, mock_get):
        mock_get.side_effect = Exception("connection refused")
        self.assertEqual(fetch_detail_text("https://example.de/x"), "")


if __name__ == "__main__":
    unittest.main()
