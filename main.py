"""
main.py — Entry point.

Orchestrates the scrape → filter → score → notify loop.
Run this directly:  python main.py
"""

import logging
import random
import sys
import time
from pathlib import Path

from config.loader       import load_config
from scraper.fetcher     import fetch_page
from scraper.parser      import parse_listings
from scraper.store       import ListingStore
from filters.hard_filter import HardFilter
from filters.priority    import PriorityScorer
from notifier.telegram   import TelegramNotifier
from notifier.formatter  import format_notification

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

def run_cycle(
    cfg:      dict,
    store:    ListingStore,
    hfilter:  HardFilter,
    scorer:   PriorityScorer,
    notifier: TelegramNotifier | None,
) -> None:
    logger = logging.getLogger(__name__)
    scraper_cfg = cfg["scraper"]

    # 1. Fetch
    try:
        soup = fetch_page(scraper_cfg["url"], timeout=scraper_cfg.get("request_timeout", 30))
    except Exception as e:
        logger.error(f"Fetch failed: {e}")
        return

    # 2. Parse
    listings = parse_listings(soup)
    if not listings:
        logger.warning("Parser returned 0 listings — page structure may have changed")
        return

    # 3. Find new listings
    new_listings = store.find_new(listings)
    logger.info(f"Found {len(new_listings)} new out of {len(listings)} total listings")

    # Mark all as seen immediately so a crash mid-loop doesn't re-notify
    store.mark_seen(new_listings)
    store.save()

    # 4. Filter, score, notify
    notified = blocked = 0
    for listing in new_listings:

        # Hard filter
        filter_result = hfilter.check(listing)
        if not filter_result.passed:
            logger.info(f"  ⛔ BLOCKED ({filter_result.reason}): {listing.get('address', listing['url'])}")
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

    store   = ListingStore(BASE_DIR / scraper_cfg["store_file"])
    hfilter = HardFilter(cfg["hard_filters"])
    scorer  = PriorityScorer(cfg["priority_scoring"])

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

    while True:
        run_cycle(cfg, store, hfilter, scorer, notifier)

        sleep_secs = base_interval + random.randint(-jitter, jitter)
        logger.info(f"Sleeping {sleep_secs // 60}m {sleep_secs % 60}s until next check")
        time.sleep(sleep_secs)


if __name__ == "__main__":
    main()
