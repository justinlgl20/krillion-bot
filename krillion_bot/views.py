"""Embed views for the stats-style commands, in the tle-gf Akari layout."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import discord

from .analytics import Streaks, Summary, TopEntry, VsOutcome
from .discord_util import alert, cf_color, info, ok, pages, rank_color
from .formatting import signed
from .models import RatingEntry
from .puzzle import PuzzleCalendar
from .rating import rank_for_rating

Names = Mapping[int, str]

TIMEFRAME_LABEL = {
    "all": "all time",
    "week": "this week",
    "month": "this month",
    "year": "this year",
    "7d": "last 7 days",
    "30d": "last 30 days",
}

PER_PAGE = 10
HISTORY_PAGE = 15
DOT = " \N{MIDDLE DOT} "


def name_of(names: Names, user_id: int) -> str:
    return names.get(user_id, f"<@{user_id}>")


def _plural(n: int, word: str) -> str:
    return f"{n} {word}{'s' if n != 1 else ''}"


def _rated(value: float) -> str:
    return f"{round(value)} ({rank_for_rating(round(value)).abbr})"


def streak_embed(name: str, play: Streaks, perfect: Streaks, score: int) -> discord.Embed:
    lines = [
        f"`{name}`: **{perfect.current}** consecutive perfect day(s)",
        f"Longest streak: **{perfect.longest}** day(s)",
        f"Latest result: **{score} pts**" + (" (perfect)" if score == 700 else ""),
        f"Played: **{play.current}** consecutive day(s) (longest **{play.longest}**)",
    ]
    return info("\n".join(lines), title="Krillion Streak", color=cf_color())


def skips_pages(
    name: str, first: int | None, skipped: Sequence[int], calendar: PuzzleCalendar
) -> list[discord.Embed]:
    if first is None:
        return [alert(f"No Krillion results found for `{name}`.")]
    if not skipped:
        return [
            ok(
                f"`{name}` has no skipped Krillion days since first submitting "
                f"**#{first}** on **{calendar.date_for(first)}**."
            )
        ]
    lines = [
        f"**#{n}**{DOT}{calendar.date_for(n).isoformat()}{DOT}{calendar.date_for(n):%A}"
        for n in skipped
    ]
    title = f"Krillion skipped days — {name} ({_plural(len(skipped), 'day')})"
    lead = f"Since first submission: **#{first}**{DOT}**{calendar.date_for(first).isoformat()}**"
    return pages(title, lines, HISTORY_PAGE, lead=lead)


def top_pages(
    entries: Sequence[TopEntry], names: Names, label: str, count_ties: bool
) -> list[discord.Embed]:
    lines = []
    place = 0
    previous: tuple[int, int] | None = None
    for idx, e in enumerate(entries, start=1):
        key = (e.total, e.solo) if count_ties else (e.solo, e.tied)
        if key != previous:
            place = idx
            previous = key
        name = name_of(names, e.user_id)
        if count_ties:
            lines.append(
                f"**#{place}** `{name}` — **{e.total}** wins ({e.solo} solo, {e.tied} tied)"
            )
        else:
            lines.append(f"**#{place}** `{name}` — **{e.solo}** wins")
    title = "Krillion Winners" + (" (With Ties)" if count_ties else "")
    return pages(title, lines, PER_PAGE)


def vs_embed(outcome: VsOutcome, names: Names) -> discord.Embed:
    if len(outcome.players) == 2:
        a, b = outcome.players
        lines = [
            f"`{name_of(names, a.user_id)}`: **{a.points:g}** points, **{a.wins}** wins",
            f"`{name_of(names, b.user_id)}`: **{b.points:g}** points, **{b.wins}** wins",
            f"Ties: **{a.ties}**",
            f"Puzzles: **{outcome.puzzles}**",
        ]
        return info("\n".join(lines), title="Krillion Head to Head")

    lines = []
    place = 0
    previous: float | None = None
    for idx, player in enumerate(outcome.players, start=1):
        if player.points != previous:
            place = idx
            previous = player.points
        lines.append(
            f"**#{place}** `{name_of(names, player.user_id)}` — **{player.points:g}** points"
            f"{DOT}**{player.wins}** wins{DOT}**{player.losses}** losses"
            f"{DOT}**{player.ties}** ties"
        )
    lines.extend(["", f"Puzzles: **{outcome.puzzles}**", f"Comparisons: **{outcome.comparisons}**"])
    return info("\n".join(lines), title="Krillion Head to Head")


def history_pages(
    name: str, entries: Sequence[RatingEntry], calendar: PuzzleCalendar
) -> list[discord.Embed]:
    """Contested days, newest first."""
    entries = [e for e in entries if e.performance is not None]
    if not entries:
        return [alert(f"`{name}` has no contested Krillion days yet.")]
    lines = []
    for e in reversed(entries):
        lines.append(
            f"**#{e.puzzle_number}**{DOT}{calendar.date_for(e.puzzle_number).isoformat()}"
            f"{DOT}{e.score} pts{DOT}{round(e.rating_before)} \N{HORIZONTAL BAR} "
            f"**{round(e.delta):+}** \N{LONG RIGHTWARDS ARROW} {round(e.rating_after)} "
            f"({rank_for_rating(round(e.rating_after)).abbr})"
            f"{DOT}perf {round(e.performance)}"
        )
    title = f"Krillion rating history — {name} ({len(entries)} contests)"
    return pages(title, lines, HISTORY_PAGE)


def rating_embed(name: str, s: Summary, games: int, *, performance: bool) -> discord.Embed:
    """``/krillion rating`` and ``/krillion performance`` header; the plot hangs below it."""
    assert s.rating is not None
    if performance and s.last_performance is not None and s.best_performance is not None:
        e = discord.Embed(
            title=f"Krillion performance — {name}", color=rank_color(s.last_performance)
        )
        e.add_field(name="Last performance", value=_rated(s.last_performance))
        e.add_field(name="Best performance", value=_rated(s.best_performance))
        e.add_field(name="Contests", value=str(games))
        return e
    e = discord.Embed(title=f"Krillion rating — {name}", color=rank_color(s.rating))
    e.add_field(name="Rating", value=_rated(s.rating))
    e.add_field(name="Peak", value=_rated(s.peak if s.peak is not None else s.rating))
    e.add_field(name="Games", value=str(games))
    e.add_field(name="Last change", value=signed(s.last_delta) if s.last_delta is not None else "—")
    e.add_field(
        name="Last performance",
        value=_rated(s.last_performance) if s.last_performance is not None else "—",
    )
    return e
