"""
fetcher.py — HTTP layer.

Two public functions:
  fetch_page()         — initial page fetch, returns (BeautifulSoup, session, csrf_token)
  fetch_livewire_page() — call the Livewire /update endpoint to get a specific page
"""

import logging
import time

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_BASE_URL = "https://www.inberlinwohnen.de"
_WOHNUNGSFINDER_URL = f"{_BASE_URL}/wohnungsfinder"
_LIVEWIRE_URL = f"{_BASE_URL}/livewire/update"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (X11; Linux x86_64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def fetch_page(url: str = _WOHNUNGSFINDER_URL, timeout: int = 30):
    """
    Fetch the Wohnungsfinder page.

    Returns:
        (BeautifulSoup, requests.Session, csrf_token: str)

    The session and CSRF token are needed for subsequent Livewire pagination
    calls. The session carries the cookies set by the initial response.
    """
    logger.debug(f"GET {url}")
    session = requests.Session()
    session.headers.update(_HEADERS)
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    logger.debug(f"Response {response.status_code}, {len(response.content)} bytes")

    soup = BeautifulSoup(response.text, "lxml")

    # CSRF token is in a <meta name="csrf-token"> tag
    csrf_meta = soup.find("meta", {"name": "csrf-token"})
    csrf_token = csrf_meta["content"] if csrf_meta else ""
    if not csrf_token:
        logger.warning("CSRF token not found in page — Livewire pagination may fail")

    return soup, session, csrf_token


def fetch_livewire_page(
    session: requests.Session,
    csrf_token: str,
    component_id: str,
    snapshot: str,
    checksum: str,
    page: int,
    timeout: int = 30,
) -> dict:
    """
    Call the Livewire /update endpoint to navigate to a specific page.

    Livewire v3 protocol:
      POST /livewire/update
      Headers: X-CSRF-TOKEN, X-Livewire: true
      Body: { components: [{ snapshot, updates: {}, calls: [setPage call] }] }

    Returns the parsed JSON response or {} on failure.
    """
    headers = {
        "X-CSRF-TOKEN": csrf_token,
        "X-Livewire": "true",
        "Content-Type": "application/json",
        "Accept": "text/html, application/xhtml+xml",
        "Referer": "https://www.inberlinwohnen.de/wohnungsfinder",
    }

    payload = {
        "components": [
            {
                "snapshot": snapshot,
                "updates": {},
                "calls": [
                    {
                        "path": "",
                        "method": "setPage",
                        "params": [page, "page"],
                    }
                ],
            }
        ]
    }

    for attempt in range(1, 4):
        try:
            resp = session.post(
                _LIVEWIRE_URL,
                json=payload,
                headers=headers,
                timeout=timeout,
            )
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            logger.warning(f"Livewire page {page} fetch failed (attempt {attempt}/3): {e}")
            if attempt < 3:
                time.sleep(2 ** attempt)
    logger.error(f"Livewire page {page} fetch failed after 3 attempts — giving up")
    return {}
