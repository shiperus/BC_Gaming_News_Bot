from __future__ import annotations

import logging
import re
import time
from html import unescape

import feedparser

from bc_bot.config import Config
from bc_bot.models import TrendingItem

logger = logging.getLogger(__name__)

POSTS_PER_SUBREDDIT = 10
DELAY_BETWEEN_REQUESTS_SECONDS = 60
MAX_RETRIES_ON_RATE_LIMIT = 3
RETRY_BACKOFF_BASE_SECONDS = 30

# For link posts, Reddit's RSS <link> always points to the comments page; the actual
# submitted URL (e.g. the news article) is embedded in the entry summary as a "[link]"
# anchor instead. Self-posts (discussion threads) have no such anchor.
_SUBMITTED_LINK_PATTERN = re.compile(r'<a href="([^"]+)">\[link\]</a>')

# Recurring community megathreads (not news) that rank high in "hot" every day/week
# and should never be treated as trending stories. Kept as an explicit list for the
# common cases feedparser sees most often; _is_meta_thread() also has a more general
# self-post + date heuristic below for subreddit-specific wordings not covered here.
_META_THREAD_PATTERNS = [
    re.compile(r"\bdaily\b.*\bdiscussion\b", re.IGNORECASE),
    re.compile(r"\bweekly\b.*\b(thread|discussion|megathread)\b", re.IGNORECASE),
    re.compile(r"\bmonthly\b.*\b(thread|discussion|megathread)\b", re.IGNORECASE),
    re.compile(r"free talk friday", re.IGNORECASE),
    re.compile(r"tech support and basic questions thread", re.IGNORECASE),
]

# Matches a date embedded in a title, e.g. "06/29/26", "6-29-2026", or "June 29".
_DATE_TOKEN_PATTERN = re.compile(
    r"\b\d{1,2}[/-]\d{1,2}([/-]\d{2,4})?\b"
    r"|\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\.?\s+\d{1,2}\b",
    re.IGNORECASE,
)
_THREAD_HINT_PATTERN = re.compile(r"\b(thread|discussion|megathread)\b", re.IGNORECASE)


def _extract_submitted_url(summary: str) -> str | None:
    match = _SUBMITTED_LINK_PATTERN.search(summary)
    return unescape(match.group(1)) if match else None


def _is_meta_thread(title: str, is_self_post: bool) -> bool:
    if any(pattern.search(title) for pattern in _META_THREAD_PATTERNS):
        return True

    # Recurring megathreads are almost always self-posts with a date baked into the
    # title (e.g. "Discussion Thread - Week Beginning 06/29/26"); this catches new
    # subreddits' own wordings without needing a hand-tuned pattern for each one.
    return bool(
        is_self_post
        and _THREAD_HINT_PATTERN.search(title)
        and _DATE_TOKEN_PATTERN.search(title)
    )


def fetch_trending(config: Config) -> list[TrendingItem]:
    """Fetch hot posts via Reddit's public Atom feed (reddit.com/r/<sub>/hot/.rss).

    Reddit's official API now gates app creation behind an approval process, and the
    plain .json endpoints are blocked by anti-bot filtering, but the .rss/.atom feeds
    remain reachable. Atom entries don't carry score/comment counts, so engagement is
    approximated by feed position (already hot-ranked by Reddit).
    """
    items: list[TrendingItem] = []

    for index, subreddit_name in enumerate(config.subreddits):
        if index > 0:
            time.sleep(DELAY_BETWEEN_REQUESTS_SECONDS)

        url = f"https://www.reddit.com/r/{subreddit_name}/hot/.rss"
        try:
            feed = _parse_with_retry(url, config.reddit_user_agent, subreddit_name)
            if feed is None:
                continue

            skipped_meta_threads = 0
            weight = config.subreddit_weights.get(subreddit_name, 1.0)
            for rank, entry in enumerate(feed.entries[:POSTS_PER_SUBREDDIT]):
                title = entry.get("title", "")
                submitted_url = _extract_submitted_url(entry.get("summary", ""))
                if _is_meta_thread(title, is_self_post=submitted_url is None):
                    skipped_meta_threads += 1
                    continue

                items.append(
                    TrendingItem(
                        title=title,
                        url=submitted_url or entry.get("link", ""),
                        source="reddit",
                        engagement=(POSTS_PER_SUBREDDIT - rank) * weight,
                        origin=f"r/{subreddit_name}",
                    )
                )

            if skipped_meta_threads:
                logger.info(
                    "r/%s: skipped %d recurring meta-thread(s)",
                    subreddit_name,
                    skipped_meta_threads,
                )
        except Exception:
            logger.exception("Failed to fetch trending posts from r/%s", subreddit_name)

    return [item for item in items if item.title and item.url]


def _parse_with_retry(url: str, user_agent: str, subreddit_name: str):
    """Parse a subreddit feed, retrying with backoff on HTTP 429."""
    for attempt in range(MAX_RETRIES_ON_RATE_LIMIT + 1):
        feed = feedparser.parse(url, agent=user_agent)
        status = feed.get("status")

        if status == 429 and attempt < MAX_RETRIES_ON_RATE_LIMIT:
            wait_seconds = RETRY_BACKOFF_BASE_SECONDS * (attempt + 1)
            logger.warning(
                "r/%s returned HTTP 429, retrying in %ds (attempt %d/%d)",
                subreddit_name,
                wait_seconds,
                attempt + 1,
                MAX_RETRIES_ON_RATE_LIMIT,
            )
            time.sleep(wait_seconds)
            continue

        if status and status != 200:
            logger.warning("r/%s returned HTTP %s, skipping", subreddit_name, status)
            return None
        if feed.bozo and not feed.entries:
            raise feed.bozo_exception

        if attempt == 0:
            logger.info("r/%s succeeded (%d entries)", subreddit_name, len(feed.entries))
        else:
            logger.info(
                "r/%s succeeded after %d retry(ies) (%d entries)",
                subreddit_name,
                attempt,
                len(feed.entries),
            )
        return feed

    return None
