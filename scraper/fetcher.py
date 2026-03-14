"""
fetcher.py — HTTP layer.

Responsible solely for fetching the raw HTML from inberlinwohnen.de.
All retry logic and session configuration lives here.
"""

import logging
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_page(url: str, timeout: int = 30) -> BeautifulSoup:
    """
    Fetch `url` and return a BeautifulSoup tree.

    Raises:
        requests.HTTPError  — on 4xx / 5xx responses
        requests.Timeout    — if the server doesn't respond in time
        requests.ConnectionError — on network failures
    """
    logger.debug(f"GET {url}")
    response = requests.get(url, headers=_HEADERS, timeout=timeout)
    response.raise_for_status()
    logger.debug(f"Response {response.status_code}, {len(response.content)} bytes")
    return BeautifulSoup(response.text, "lxml")
