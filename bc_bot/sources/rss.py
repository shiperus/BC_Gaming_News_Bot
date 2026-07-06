from __future__ import annotations

import logging

import feedparser
from rapidfuzz import fuzz, process, utils

from bc_bot.config import Config
from bc_bot.models import Article

logger = logging.getLogger(__name__)

ARTICLES_PER_FEED = 30
MATCH_THRESHOLD = 62


def fetch_articles(config: Config) -> list[Article]:
    articles: list[Article] = []
    for feed_url in config.rss_feeds:
        try:
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:ARTICLES_PER_FEED]:
                articles.append(
                    Article(
                        title=entry.get("title", ""),
                        link=entry.get("link", ""),
                        source=feed_url,
                        published=entry.get("published"),
                    )
                )
        except Exception:
            logger.exception("Failed to fetch RSS feed %s", feed_url)

    return [a for a in articles if a.title and a.link]


def find_best_match(topic_title: str, articles: list[Article]) -> Article | None:
    if not articles:
        return None

    titles = [a.title for a in articles]
    result = process.extractOne(
        topic_title, titles, scorer=fuzz.token_set_ratio, processor=utils.default_process
    )
    if result is None:
        return None

    _match_title, score, index = result
    if score < MATCH_THRESHOLD:
        return None

    return articles[index]
