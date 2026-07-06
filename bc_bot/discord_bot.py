from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import tasks

from bc_bot import aggregator
from bc_bot.config import Config
from bc_bot.db import Store
from bc_bot.models import TrendingItem
from bc_bot.sources import reddit, rss

logger = logging.getLogger(__name__)


class BcGamingBot(discord.Client):
    def __init__(self, config: Config, store: Store) -> None:
        super().__init__(intents=discord.Intents.default())
        self.config = config
        self.store = store
        self.cycle_task = tasks.loop(hours=config.check_interval_hours)(self._run_cycle_safe)

    async def setup_hook(self) -> None:
        self.cycle_task.start()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s", self.user)

    async def _run_cycle_safe(self) -> None:
        try:
            await self._run_cycle()
        except Exception:
            logger.exception("Cycle failed; will retry at the next scheduled interval")

    async def _run_cycle(self) -> None:
        logger.info("Starting trending-news cycle")

        reddit_items, articles = await asyncio.gather(
            asyncio.to_thread(reddit.fetch_trending, self.config),
            asyncio.to_thread(rss.fetch_articles, self.config),
        )

        consolidated = aggregator.consolidate(reddit_items)
        aggregator.boost_announcements(consolidated)
        aggregator.enrich_with_articles(consolidated, articles)
        ranked = aggregator.rank(consolidated)

        fresh = [
            item
            for item in ranked
            if not self.store.is_duplicate(item.title, self.config.retention_days)
        ]
        to_post = fresh[: self.config.posts_per_cycle]

        channel = self.get_channel(self.config.discord_channel_id)
        if channel is None:
            channel = await self.fetch_channel(self.config.discord_channel_id)

        for item in to_post:
            await self._post_item(channel, item)
            self.store.record_posted(item.title, item.link, "+".join(sorted(item.sources)))

        removed = self.store.cleanup_old(self.config.retention_days)
        logger.info(
            "Cycle complete: posted %d items, cleaned up %d old records", len(to_post), removed
        )

    async def _post_item(self, channel: discord.abc.Messageable, item: TrendingItem) -> None:
        embed = discord.Embed(title=item.title, url=item.link, color=discord.Color.blurple())
        embed.add_field(name="Origin", value=item.origin, inline=True)
        embed.add_field(name="Sources", value=", ".join(sorted(item.sources)), inline=True)
        embed.set_footer(text=f"Confidence x{item.confidence}")
        await channel.send(embed=embed)
