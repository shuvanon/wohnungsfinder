"""
main.py — Entry point.

Orchestrates the scrape → filter → score → notify loop.
Run this directly:  python main.py
"""

import logging
import random
import signal
import sys
import time
from pathlib import Path

from config.loader         import load_config
from scraper.fetcher       import fetch_page
from scraper.parser        import parse_listings
from scraper.detail_fetcher import fetch_detail_text
from scraper.store         import ListingStore
from filters.hard_filter   import HardFilter
from filters.priority      import PriorityScorer
from enrich.llm            import LLMExtractor
from notifier.telegram     import TelegramNotifier
from notifier.formatter    import format_notification

BASE_DIR = Path(__file__).parent


def setup_logging(log_file: str, level: str) -> None:
    log_path = BASE_DIR / log_file
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
        handlers=[
            logging.FileHandler(log_path),
            logging.StreamHandler(sys.stdout),
        ],
    )


# ── Single scrape cycle ────────────────────────────────────────────────────────

def _apply_enrichment(listing: dict, extracted: dict) -> None:
    """
    Merge LLM-extracted fields into the listing and reconcile derived fields.

    The hard filter reads the textual `wbs` field, so when the LLM finds a WBS
    requirement the list view missed (the key case: table says "nicht
    erforderlich" but the headline/detail page says otherwise), escalate `wbs`
    to "erforderlich" so the existing rule actually blocks it. We only escalate,
    never downgrade — a list-view WBS flag is not cleared on the LLM's say-so.
    """
    listing.update(extracted)
    if extracted.get("wbs_required") is True:
        listing["wbs"] = "erforderlich"


def run_cycle(
    cfg:       dict,
    store:     ListingStore,
    hfilter:   HardFilter,
    scorer:    PriorityScorer,
    extractor: LLMExtractor,
    notifier:  TelegramNotifier | None,
) -> None:
    logger = logging.getLogger(__name__)
    scraper_cfg = cfg["scraper"]

    # 1. Fetch
    try:
        soup, session, csrf_token = fetch_page(scraper_cfg["url"], timeout=scraper_cfg.get("request_timeout", 30))
    except Exception as e:
        logger.error(f"Fetch failed: {e}")
        return

    # 2. Parse (passes session + csrf for Livewire pagination)
    listings = parse_listings(soup, session=session, csrf_token=csrf_token)
    if not listings:
        logger.warning("Parser returned 0 listings — page structure may have changed")
        return

    # 3. Find new listings
    new_listings = store.find_new(listings)
    logger.info(f"Found {len(new_listings)} new out of {len(listings)} total listings")

    # Mark all as seen immediately so a crash mid-loop doesn't re-notify
    store.mark_seen(new_listings)
    store.save()

    # 4. Filter, enrich, score, notify
    notified = blocked = 0
    for listing in new_listings:

        # Cheap hard filter on list-view data — drop obvious nos before
        # spending any network / LLM budget on the detail page.
        filter_result = hfilter.check(listing)
        if not filter_result.passed:
            logger.info(f"  ⛔ BLOCKED ({filter_result.reason}): {listing.get('address', listing['url'])}")
            store.log_filter_result(listing, filter_result)
            blocked += 1
            continue

        # Enrich survivors: fetch the detail page, normalize unstructured
        # fields (e.g. true WBS requirement) via the LLM, then re-run the hard
        # filter now that those fields may have changed.
        if extractor.enabled:
            detail_text = fetch_detail_text(
                listing["url"], max_chars=extractor.max_detail_chars
            )
            extracted = extractor.extract(listing, detail_text)
            listing["detail_text"] = detail_text
            _apply_enrichment(listing, extracted)
            store.save_enrichment(listing)

            filter_result = hfilter.check(listing)
            if not filter_result.passed:
                logger.info(
                    f"  ⛔ BLOCKED after enrichment ({filter_result.reason}): "
                    f"{listing.get('address', listing['url'])}"
                )
                store.log_filter_result(listing, filter_result)
                blocked += 1
                continue

        # Priority score
        priority = scorer.score(listing)
        logger.info(
            f"  ✅ NEW {priority.label} (score {priority.score}): "
            f"{listing.get('address', listing['url'])}"
        )
        store.log_filter_result(listing, filter_result, priority)

        # Format & send
        message = format_notification(listing, priority)

        if notifier:
            notifier.send(message)
        else:
            # No Telegram configured — print to stdout (useful for local testing)
            print("\n" + "═" * 60)
            print(message)

        notified += 1

    logger.info(f"Cycle complete — {notified} notified, {blocked} blocked")


# ── Main loop ──────────────────────────────────────────────────────────────────

def main() -> None:
    cfg = load_config()
    scraper_cfg = cfg["scraper"]

    setup_logging(scraper_cfg["log_file"], scraper_cfg.get("log_level", "INFO"))
    logger = logging.getLogger(__name__)
    logger.info("Wohnungsfinder scraper starting up")

    store     = ListingStore(BASE_DIR / scraper_cfg["store_file"])
    hfilter   = HardFilter(cfg["hard_filters"])
    scorer    = PriorityScorer(cfg["priority_scoring"])
    extractor = LLMExtractor(cfg.get("llm"))
    if extractor.enabled:
        logger.info(f"LLM enrichment ready ({extractor.model} @ {extractor.base_url})")
    else:
        logger.info("LLM enrichment disabled — running on list-view data only")

    # Set up Telegram (optional — falls back to stdout if not configured)
    notifier: TelegramNotifier | None = None
    tg_cfg = cfg.get("telegram", {})
    try:
        notifier = TelegramNotifier(
            bot_token=tg_cfg["bot_token"],
            chat_ids=tg_cfg["chat_ids"],
        )
        logger.info("Telegram notifier ready")
    except ValueError as e:
        logger.warning(f"Telegram not configured: {e}. Notifications will print to stdout.")

    base_interval = scraper_cfg["interval_minutes"] * 60
    jitter        = scraper_cfg.get("jitter_minutes", 3) * 60

    # Graceful shutdown on SIGTERM (sent by Docker / systemd on stop)
    shutdown = False

    def _handle_sigterm(signum, frame):
        nonlocal shutdown
        logger.info("SIGTERM received — finishing current cycle then shutting down")
        shutdown = True

    signal.signal(signal.SIGTERM, _handle_sigterm)

    while not shutdown:
        run_cycle(cfg, store, hfilter, scorer, extractor, notifier)
        if shutdown:
            break
        sleep_secs = base_interval + random.randint(-jitter, jitter)
        logger.info(f"Sleeping {sleep_secs // 60}m {sleep_secs % 60}s until next check")
        # Interruptible sleep — wakes immediately on SIGTERM
        for _ in range(sleep_secs):
            if shutdown:
                break
            time.sleep(1)

    logger.info("Shutting down cleanly")
    store.close()


if __name__ == "__main__":
    main()
