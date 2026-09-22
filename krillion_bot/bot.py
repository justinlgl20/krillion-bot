from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta
from typing import Any

import discord
from discord import app_commands

from . import commands, commands_admin
from .analytics import WeekRecap, build_week_recap
from .config import Config
from .discord_util import board_message, utcnow
from .formatting import final_table
from .models import Result
from .parser import ParsedResult, parse_result
from .puzzle import PuzzleCalendar
from .service import FinalizedDay, KrillionService, SubmitStatus
from .storage import Storage
from .views import week_table, week_text

log = logging.getLogger(__name__)

_POLL_CAP = timedelta(minutes=15)


def _now() -> datetime:
    return utcnow()


class KrillionBot(discord.Client):
    def __init__(self, config: Config, service: KrillionService) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = False
        super().__init__(intents=intents)
        self.config = config
        self.service = service
        self.tree = app_commands.CommandTree(self)
        group = commands.register(self)
        commands_admin.register(self, group)
        self._scheduler: asyncio.Task[None] | None = None

    @staticmethod
    def now() -> datetime:
        return _now()

    # -- lifecycle -------------------------------------------------------

    async def setup_hook(self) -> None:
        replayed = self.service.migrate_ratings()
        if replayed:
            log.info("Replayed ratings for %d guild(s) with the current engine", replayed)
        await self.tree.sync()
        self._scheduler = asyncio.create_task(self._finalize_loop(), name="finalize-loop")

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info(
            "Logged in as %s (%s); current puzzle #%d",
            self.user,
            self.user.id,
            self.service.calendar.current(_now()),
        )

    async def close(self) -> None:
        if self._scheduler is not None:
            self._scheduler.cancel()
        await super().close()

    def admin_ids(self, guild_id: int) -> set[int]:
        return set(self.config.admin_user_ids) | self.service.storage.admins(guild_id)

    def is_admin(self, user: discord.abc.User, guild_id: int) -> bool:
        return user.id in self.admin_ids(guild_id)

    def channel_setting(self, guild_id: int, key: str) -> int | None:
        """Per-server channel override, else the env default (``None`` = unset)."""
        stored = self.service.storage.get_setting(guild_id, key)
        if stored is not None:
            return int(stored)
        if key == "results_channel":
            return self.config.results_channel_id
        if key == "leaderboard_channel":
            return self.config.leaderboard_channel_id
        return None

    async def _messageable(self, channel_id: int) -> discord.abc.Messageable | None:
        channel = self.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.fetch_channel(channel_id)
            except discord.HTTPException:
                log.error("Cannot find channel %s", channel_id)
                return None
        if not isinstance(channel, discord.abc.Messageable):
            log.error("Channel %s is not messageable", channel_id)
            return None
        return channel

    # -- results ingestion ----------------------------------------------

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        wanted = self.channel_setting(message.guild.id, "results_channel")
        if wanted is not None and message.channel.id != wanted:
            return
        outcome = self.service.submit(
            guild_id=message.guild.id,
            user_id=message.author.id,
            display_name=message.author.display_name,
            text=message.content,
            channel_id=message.channel.id,
            message_id=message.id,
            now=message.created_at,
        )
        if outcome.status is SubmitStatus.NOT_A_RESULT:
            if "krillion" in message.content.lower():
                log.info(
                    "Message %s in %s mentions Krillion but did not parse as a result",
                    message.id,
                    message.channel.id,
                )
            return
        assert outcome.parsed is not None
        n = outcome.parsed.puzzle_number
        log.info(
            "Krillion #%d from %s in guild %s: %s (%s)",
            n,
            message.author.id,
            message.guild.id,
            outcome.status.value,
            outcome.parsed.score,
        )
        try:
            if outcome.status is SubmitStatus.ACCEPTED:
                await message.add_reaction("🦐")
                await message.reply(
                    f"Received Krillion #{n} score from **{message.author.display_name}**: "
                    f"{outcome.parsed.score} 🦐",
                    mention_author=False,
                )
            elif outcome.status is SubmitStatus.DUPLICATE:
                assert outcome.existing is not None
                await message.add_reaction("⚠️")
                await message.reply(
                    f"Already have your Krillion #{n} result ({outcome.existing.score}) — "
                    "keeping the first one.",
                    mention_author=False,
                )
            elif outcome.status is SubmitStatus.TOO_LATE:
                await message.add_reaction("⏰")
                await message.reply(
                    f"Krillion #{n} has already closed — today's puzzle is "
                    f"#{outcome.current_puzzle}.",
                    mention_author=False,
                )
            elif outcome.status is SubmitStatus.NOT_YET:
                await message.add_reaction("❓")
                await message.reply(
                    f"Krillion #{n} isn't out yet — today's puzzle is #{outcome.current_puzzle}.",
                    mention_author=False,
                )
            elif outcome.status is SubmitStatus.BANNED:
                await message.add_reaction("🚫")
        except discord.HTTPException:
            log.exception("Failed to respond to submission in %s", message.channel.id)

    # -- daily close -----------------------------------------------------

    async def _finalize_loop(self) -> None:
        await self.wait_until_ready()
        while not self.is_closed():
            try:
                for day in self.service.finalize_due(_now()):
                    await self._announce(day)
            except Exception:
                log.exception("Finalization failed")
            now = _now()
            wake = min(self.service.next_finalize_at(now), now + _POLL_CAP)
            await asyncio.sleep(max(1.0, (wake - now).total_seconds() + 1))

    async def _announce(self, day: FinalizedDay) -> None:
        channel_id = self.channel_setting(day.guild_id, "leaderboard_channel") or day.channel_id
        channel = await self._messageable(channel_id)
        if channel is None:
            return
        tiers = {
            r.user_id: r.tiers
            for r in self.service.storage.results_for(day.guild_id, day.puzzle_number)
        }
        board = final_table(
            day.puzzle_number,
            self.service.calendar.date_for(day.puzzle_number),
            day.entries,
            day.players,
            tiers,
            day.decay,
        )
        await channel.send(**board_message(board, f"krillion-{day.puzzle_number}.png"))
        log.info("Posted Krillion #%d results for guild %s", day.puzzle_number, day.guild_id)
        closed = self.service.calendar.date_for(day.puzzle_number)
        if closed.weekday() == 6:
            await self._announce_week(day.guild_id, closed)

    # -- weekly recap ----------------------------------------------------

    def week_recap(self, guild_id: int, anchor: date, today: date) -> WeekRecap:
        storage = self.service.storage
        calendar = self.service.calendar
        low = calendar.number_for_date(anchor - timedelta(days=anchor.weekday() + 7))
        high = calendar.number_for_date(anchor + timedelta(days=6 - anchor.weekday()))
        return build_week_recap(
            storage.results_between(guild_id, low, high),
            storage.history_between(guild_id, low, high),
            calendar,
            anchor,
            today,
        )

    def week_board(self, recap: WeekRecap, names: dict[int, str]) -> dict[str, Any]:
        """Attachment kwargs for the standings table (empty if there's nothing to show)."""
        if not recap.standings:
            return {}
        message = board_message(week_table(recap, names), f"krillion-week-{recap.start}.png")
        return {"file": message["file"]} if "file" in message else {}

    async def _announce_week(self, guild_id: int, sunday: date) -> None:
        channel_id = self.channel_setting(guild_id, "weekly_channel")
        if channel_id is None:
            return
        channel = await self._messageable(channel_id)
        if channel is None:
            return
        recap = self.week_recap(guild_id, sunday, sunday)
        if recap.results == 0:
            return
        names = {p.user_id: p.display_name for p in self.service.storage.players(guild_id)}
        await channel.send(week_text(recap, names), **self.week_board(recap, names))
        log.info("Posted weekly recap for guild %s (week of %s)", guild_id, recap.start)

    # -- message re-reading ----------------------------------------------

    async def refetch_results(
        self, guild_id: int, puzzle_number: int
    ) -> list[tuple[ParsedResult | None, Result]]:
        """Re-parse the original share message behind each stored result."""
        out: list[tuple[ParsedResult | None, Result]] = []
        for r in self.service.storage.results_for(guild_id, puzzle_number):
            if r.message_id is None:
                continue
            channel = await self._messageable(r.channel_id)
            if channel is None:
                continue
            try:
                message = await channel.fetch_message(r.message_id)
            except discord.HTTPException:
                log.warning("Cannot fetch message %s for reparse", r.message_id)
                continue
            out.append((parse_result(message.content), r))
        return out

    async def import_channel(self, guild_id: int, channel: discord.TextChannel, limit: int) -> int:
        added = 0
        async for message in channel.history(limit=limit, oldest_first=False):
            if message.author.bot:
                continue
            added += self.service.import_result(
                guild_id=guild_id,
                user_id=message.author.id,
                display_name=message.author.display_name,
                text=message.content,
                channel_id=channel.id,
                message_id=message.id,
                created_at=message.created_at,
            )
        return added


def build(config: Config) -> KrillionBot:
    storage = Storage(config.database_path)
    calendar = PuzzleCalendar(tz=config.puzzle_tz, epoch=config.epoch_date)
    service = KrillionService(
        storage,
        calendar,
        grace=timedelta(minutes=config.late_grace_minutes),
        damping=config.rating_damping,
        decay_base=config.decay_base,
        decay_max=config.decay_max,
        decay_grace=config.decay_grace,
    )
    return KrillionBot(config, service)
