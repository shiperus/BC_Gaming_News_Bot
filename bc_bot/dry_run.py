from __future__ import annotations

import logging
import time

from bc_bot import aggregator
from bc_bot.config import Config
from bc_bot.db import Store
from bc_bot.sources import reddit, rss

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = 10 * 60


def run_cycle(config: Config, store: Store) -> None:
    reddit_items = reddit.fetch_trending(config)
    articles = rss.fetch_articles(config)
    print(f"\nFetched {len(reddit_items)} Reddit posts, {len(articles)} RSS articles.\n")

    consolidated = aggregator.consolidate(reddit_items)
    aggregator.boost_announcements(consolidated)
    aggregator.enrich_with_articles(consolidated, articles)
    ranked = aggregator.rank(consolidated)

    fresh = [
        item for item in ranked if not store.is_duplicate(item.title, config.retention_days)
    ]
    to_post = fresh[: config.posts_per_cycle]

    print(f"=== DRY RUN: {len(to_post)} item(s) would be posted (of {len(ranked)} candidates) ===\n")
    for i, item in enumerate(to_post, 1):
        print(f"{i}. {item.title}")
        print(f"   Link: {item.link}")
        print(
            f"   Origin: {item.origin}  Sources: {', '.join(sorted(item.sources))}  "
            f"Confidence: x{item.confidence}"
        )
        print()
        store.record_posted(item.title, item.link, "+".join(sorted(item.sources)))

    removed = store.cleanup_old(config.retention_days)
    print(
        f"Recorded {len(to_post)} item(s) to the database (nothing was posted to Discord). "
        f"Cleaned up {removed} old record(s).\n"
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    config = Config()
    store = Store(config.db_path)

    cycle_num = 0
    try:
        while True:
            cycle_num += 1
            logger.info("Starting dry-run cycle %d", cycle_num)
            try:
                run_cycle(config, store)
            except Exception:
                logger.exception("Dry-run cycle failed; will retry at the next scheduled interval")
            logger.info("Sleeping %d seconds until next cycle", CHECK_INTERVAL_SECONDS)
            time.sleep(CHECK_INTERVAL_SECONDS)
    except KeyboardInterrupt:
        logger.info("Dry-run stopped after %d cycle(s)", cycle_num)


if __name__ == "__main__":
    main()
