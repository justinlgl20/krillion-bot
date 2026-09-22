"""Small Discord-facing helpers shared by the bot and its command modules.

Responses follow the tle-gf look: green embeds for things that worked, amber
for things that didn't, Codeforces-coloured embeds for everything informational,
and long lists as pages with ``Page i / n`` footers and ◀ ▶ buttons.
"""

from __future__ import annotations

import asyncio
import io
import logging
import random
from collections.abc import Callable, Sequence
from datetime import date, datetime, timezone
from typing import Any, ParamSpec

import discord

from .formatting import Table
from .puzzle import PuzzleCalendar
from .rating import rank_for_rating
from .render import render_table

log = logging.getLogger(__name__)
P = ParamSpec("P")

CF_COLORS = (0xFFCA1F, 0x198BCC, 0xFF2020)
SUCCESS_GREEN = 0x28A745
ALERT_AMBER = 0xFFBF00
PAGE_TIMEOUT = 300


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def guild_of(interaction: discord.Interaction) -> int:
    """The server id; every ``/krillion`` command is ``guild_only``."""
    assert interaction.guild_id is not None
    return interaction.guild_id


def png_file(png: bytes, filename: str) -> discord.File:
    return discord.File(io.BytesIO(png), filename=filename)


def board_message(table: Table, filename: str) -> dict[str, Any]:
    """kwargs for ``send``: the table as a PNG attachment, or as text if that fails.

    Notes carrying a Discord timestamp can't go in the image, so they stay as text.
    """
    try:
        png = render_table(table)
    except Exception:
        log.exception("Rendering leaderboard image failed; sending text")
        png = None
    if png is None:
        return {"content": table.text()}
    timed = [n for n in table.notes if "<t:" in n]
    return {"content": "\n".join(timed) or None, "file": png_file(png, filename)}


def resolve_puzzle(
    calendar: PuzzleCalendar, now: datetime, puzzle: int | None, day: str | None
) -> tuple[int | None, str | None]:
    """Turn a ``puzzle`` number or ``YYYY-MM-DD`` ``day`` into a puzzle number.

    Returns ``(number, error)``; with neither given, today's puzzle.
    """
    if puzzle is not None and day is not None:
        return None, "Give either a puzzle number or a date, not both."
    if day is not None:
        try:
            puzzle = calendar.number_for_date(date.fromisoformat(day))
        except ValueError:
            return None, f"`{day}` is not a date (`YYYY-MM-DD`)."
    if puzzle is None:
        return calendar.current(now), None
    if puzzle < 1:
        return None, "Puzzle numbers start at 1."
    return puzzle, None


# -- embeds ------------------------------------------------------------------


def cf_color() -> int:
    return random.choice(CF_COLORS)


def rank_color(rating: float) -> int:
    r, g, b = rank_for_rating(round(rating)).color
    return (r << 16) | (g << 8) | b


def info(description: str, *, title: str | None = None, color: int | None = None) -> discord.Embed:
    color = cf_color() if color is None else color
    return discord.Embed(title=title, description=description, color=color)


def ok(description: str) -> discord.Embed:
    return discord.Embed(description=description, color=SUCCESS_GREEN)


def alert(description: str) -> discord.Embed:
    return discord.Embed(description=description, color=ALERT_AMBER)


async def reply(
    interaction: discord.Interaction, embed: discord.Embed, *, ephemeral: bool = False
) -> None:
    await interaction.response.send_message(embed=embed, ephemeral=ephemeral)


async def send_plot(
    interaction: discord.Interaction,
    filename: str,
    render: Callable[P, bytes],
    *args: P.args,
    **kwargs: P.kwargs,
) -> None:
    """Defer, draw the matplotlib figure off the event loop, then attach it."""
    await interaction.response.defer()
    png = await asyncio.to_thread(render, *args, **kwargs)
    await interaction.followup.send(file=png_file(png, filename))


# -- pagination --------------------------------------------------------------


class Pages(discord.ui.View):
    """◀ ▶ over a list of embeds; only the requester may turn pages."""

    def __init__(self, embeds: Sequence[discord.Embed], author_id: int, index: int) -> None:
        super().__init__(timeout=PAGE_TIMEOUT)
        self.embeds = embeds
        self.author_id = author_id
        self.index = index

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        return interaction.user.id == self.author_id

    async def _turn(self, interaction: discord.Interaction, step: int) -> None:
        self.index = (self.index + step) % len(self.embeds)
        await interaction.response.edit_message(embed=self.embeds[self.index], view=self)

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary)
    async def previous(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._turn(interaction, -1)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary)
    async def next(self, interaction: discord.Interaction, _: discord.ui.Button) -> None:
        await self._turn(interaction, 1)


def chunk(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)] or [[]]


def pages(
    title: str, lines: Sequence[str], per_page: int, *, lead: str = "", color: int | None = None
) -> list[discord.Embed]:
    """Same-coloured embeds sharing ``title``; ``lead`` opens every page."""
    color = cf_color() if color is None else color
    out = []
    for part in chunk(lines, per_page):
        body = "\n".join(part)
        out.append(info(f"{lead}\n\n{body}" if lead and body else lead or body, title=title))
    return number_pages(out, color)


def number_pages(embeds: list[discord.Embed], color: int | None = None) -> list[discord.Embed]:
    """Give ``embeds`` one colour and ``Page i / n`` footers (none for a single page)."""
    color = cf_color() if color is None else color
    for i, e in enumerate(embeds, start=1):
        e.color = color
        if len(embeds) > 1:
            e.set_footer(text=f"Page {i} / {len(embeds)}")
    return embeds


async def send_pages(
    interaction: discord.Interaction,
    embeds: Sequence[discord.Embed],
    *,
    page: int = 1,
    ephemeral: bool = False,
) -> None:
    index = min(max(1, page), len(embeds)) - 1
    if len(embeds) == 1:
        await interaction.response.send_message(embed=embeds[0], ephemeral=ephemeral)
        return
    view = Pages(embeds, interaction.user.id, index)
    await interaction.response.send_message(embed=embeds[index], view=view, ephemeral=ephemeral)
