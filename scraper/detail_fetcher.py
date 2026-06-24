"""
detail_fetcher.py — Fetch and clean an individual listing's detail page.

The Wohnungsfinder list view only carries shallow data. The real detail lives
on each housing company's own site (degewo, howoge, gewobag, wbm, gesobau,
stadtundland, …) — and every provider has a different page structure.

Rather than maintain a parser per provider, we fetch the page, strip it to
plain text, and hand that text to the LLM enrichment layer (enrich/llm.py),
which extracts the structured fields we care about.

Public function:
    fetch_detail_text(url) -> str   # clean visible text, or "" on failure
"""

import logging
import re

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


def fetch_detail_text(url: str, timeout: int = 30, max_chars: int = 8000) -> str:
    """
    Fetch a listing detail page and return its visible text.

    requests follows cross-host redirects automatically, so deep-links that
    bounce (e.g. http→https, or a path move) resolve transparently.

    Args:
        url:       The listing's deep-link (an external housing-company URL).
        timeout:   Per-request timeout in seconds.
        max_chars: Hard cap on returned text length, to bound LLM input cost.

    Returns:
        Cleaned, whitespace-collapsed page text, truncated to max_chars.
        Returns "" on any failure (logged) so the caller can degrade
        gracefully to list-view data only.
    """
    if not url:
        return ""

    try:
        resp = requests.get(url, headers=_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Detail fetch failed for {url}: {e}")
        return ""

    try:
        soup = BeautifulSoup(resp.text, "lxml")
    except Exception as e:
        logger.warning(f"Detail parse failed for {url}: {e}")
        return ""

    # Drop non-content elements that would only add noise to the LLM input.
    for tag in soup(["script", "style", "noscript", "svg", "head"]):
        tag.decompose()

    text = soup.get_text(separator=" ")
    text = re.sub(r"\s+", " ", text).strip()

    if len(text) > max_chars:
        text = text[:max_chars]

    logger.debug(f"Detail text for {url}: {len(text)} chars")
    return text
