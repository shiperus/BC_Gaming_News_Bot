from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrendingItem:
    title: str
    url: str
    source: str  # "reddit"
    engagement: float
    origin: str  # e.g. "r/Games" or channel title
    sources: set[str] = field(default_factory=set)
    confidence: int = 1
    article_url: str | None = None

    def __post_init__(self) -> None:
        if not self.sources:
            self.sources = {self.source}

    @property
    def link(self) -> str:
        return self.article_url or self.url


@dataclass
class Article:
    title: str
    link: str
    source: str
    published: str | None = None
