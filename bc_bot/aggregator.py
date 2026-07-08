from __future__ import annotations

import re

from rapidfuzz import fuzz, utils

from bc_bot.models import Article, TrendingItem
from bc_bot.sources import rss

CONSOLIDATION_THRESHOLD = 80

# Phrases that show up in titles announcing, revealing, or confirming a new game --
# as opposed to discounts, patch notes, esports results, memes, etc.
_ANNOUNCEMENT_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\bannounc(e|ed|ement|es|ing)\b",
        r"\brevealed?\b",
        r"\bunveil(ed|s|ing)?\b",
        r"\bteaser\b",
        r"\btrailer\b",
        r"\bcoming to\b",
        r"\brelease date\b",
        r"\bconfirmed for\b",
        r"\bnew (game|expansion|dlc)\b",
    ]
]

# Phrases indicating hands-on editorial coverage of a game -- reviews, previews,
# impressions -- which should also be prioritized over routine chatter, esports
# results, sales, and discussion threads, same as announcements.
_COVERAGE_PATTERNS = [
    re.compile(pattern, re.IGNORECASE)
    for pattern in [
        r"\breview(s|ed)?\b",
        r"\bimpressions?\b",
        r"\bhands[- ]on\b",
        r"\bpreview(s|ed)?\b",
        r"\bfirst look\b",
        r"\bearly access\b",
    ]
]


def consolidate(items: list[TrendingItem]) -> list[TrendingItem]:
    """Merge items across sources that describe the same story."""
    clusters: list[TrendingItem] = []

    for item in sorted(items, key=lambda i: i.engagement, reverse=True):
        cluster = next(
            (
                c
                for c in clusters
                if fuzz.token_sort_ratio(
                    item.title, c.title, processor=utils.default_process
                )
                >= CONSOLIDATION_THRESHOLD
            ),
            None,
        )
        if cluster is None:
            clusters.append(item)
            continue

        cluster.engagement += item.engagement
        cluster.sources.add(item.source)
        cluster.confidence = len(cluster.sources)

    return clusters


def enrich_with_articles(items: list[TrendingItem], articles: list[Article]) -> None:
    """Attach a matching RSS article to each item, falling back to its original link."""
    for item in items:
        match = rss.find_best_match(item.title, articles)
        if match:
            item.article_url = match.link
            item.article_title = match.title
            item.confidence += 1


def boost_announcements(items: list[TrendingItem]) -> None:
    """Bump confidence for items that look like a new-game announcement, or hands-on
    coverage (review/preview/impressions) -- the content this bot should lead with,
    ahead of routine discussion, esports results, or sales posts. A title can match
    both categories (e.g. a review of a just-announced game) and stack the boost."""
    for item in items:
        if any(pattern.search(item.title) for pattern in _ANNOUNCEMENT_PATTERNS):
            item.confidence += 1
        if any(pattern.search(item.title) for pattern in _COVERAGE_PATTERNS):
            item.confidence += 1


def rank(items: list[TrendingItem]) -> list[TrendingItem]:
    return sorted(items, key=lambda i: (i.confidence, i.engagement), reverse=True)
