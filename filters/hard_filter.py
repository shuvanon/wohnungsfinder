"""
hard_filter.py — Hard filters.

A listing that fails any hard filter is dropped entirely — no notification
is sent, no scoring is done.  These rules represent absolute disqualifiers
based on your personal situation (no WBS, not a student, not a senior, etc.).

All rules are driven by config/settings.json so you never need to edit code.
"""

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _searchable_text(listing: dict) -> str:
    """
    Concatenate the listing's text fields for keyword / WBS-category matching.

    Includes the detail-page fields (detail_text, description_summary, wbs_tier)
    when present — i.e. after enrichment, so markers buried in the listing body
    are caught. At the cheap pre-filter stage only title/address are available,
    which is fine; the post-enrichment re-filter sees the full text.
    """
    parts = (
        listing.get("title"),
        listing.get("address"),
        listing.get("wbs_tier"),
        listing.get("description_summary"),
        listing.get("detail_text"),
        listing.get("raw_text"),  # legacy; currently always empty
    )
    return " ".join(part for part in parts if part).lower()


@dataclass
class FilterResult:
    passed: bool
    reason: str = ""  # Human-readable explanation when passed=False


class HardFilter:
    """
    Applies all configured hard-filter rules to a single listing.

    Instantiate once with the hard_filters section of settings.json,
    then call .check(listing) for each new listing.
    """

    def __init__(self, config: dict):
        self._cfg = config

    def check(self, listing: dict) -> FilterResult:
        """
        Run every rule in order.  Returns on the first failure so logs are
        clear about exactly which rule eliminated the listing.
        """
        result = (
            self._check_keywords(listing)
            or self._check_wbs_required(listing)
            or self._check_wbs_categories(listing)
            or self._check_rent(listing)
            or self._check_rooms(listing)
        )
        if result:
            logger.debug(f"Hard filter blocked: {result.reason} — {listing.get('address', listing['url'])}")
            return result

        return FilterResult(passed=True)

    # ── Individual rules ───────────────────────────────────────────────────

    def _check_keywords(self, listing: dict) -> FilterResult | None:
        """Block listings whose text contains a disallowed keyword."""
        keywords: list[str] = self._cfg.get("block_keywords", [])
        searchable = _searchable_text(listing)

        for kw in keywords:
            if kw.lower() in searchable:
                return FilterResult(passed=False, reason=f"Blocked keyword: '{kw}'")
        return None

    def _check_wbs_required(self, listing: dict) -> FilterResult | None:
        """Block all WBS-required listings when the user has no WBS."""
        if not self._cfg.get("block_if_wbs_required", False):
            return None

        wbs = (listing.get("wbs") or "").lower()
        if "erforderlich" in wbs and "nicht" not in wbs:
            return FilterResult(passed=False, reason="WBS required — user has no WBS")
        return None

    def _check_wbs_categories(self, listing: dict) -> FilterResult | None:
        """Block specific WBS income tiers (e.g. WBS 100, WBS 140)."""
        blocked: list[str] = self._cfg.get("block_wbs_categories", [])
        searchable = _searchable_text(listing)

        for category in blocked:
            if category.lower() in searchable:
                return FilterResult(passed=False, reason=f"Blocked WBS category: '{category}'")
        return None

    def _check_rent(self, listing: dict) -> FilterResult | None:
        """Block listings above the maximum rent."""
        max_rent = self._cfg.get("max_total_rent")
        if max_rent is None:
            return None

        total_rent = listing.get("total_rent")
        if total_rent is not None and total_rent > max_rent:
            return FilterResult(
                passed=False,
                reason=f"Total rent €{total_rent:.2f} exceeds max €{max_rent}"
            )
        return None

    def _check_rooms(self, listing: dict) -> FilterResult | None:
        """Block listings outside the desired room count range."""
        rooms = listing.get("rooms")
        if rooms is None:
            return None  # Can't check — let it through

        min_rooms = self._cfg.get("min_rooms", 0)
        max_rooms = self._cfg.get("max_rooms")  # None = no upper limit

        if rooms < min_rooms:
            return FilterResult(passed=False, reason=f"Rooms {rooms} < minimum {min_rooms}")
        if max_rooms is not None and rooms > max_rooms:
            return FilterResult(passed=False, reason=f"Rooms {rooms} > maximum {max_rooms}")
        return None
