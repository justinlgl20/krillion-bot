"""Pure calculations behind the stats-style commands.

Everything here works on stored :class:`Result` / :class:`RatingEntry` rows
and a :class:`PuzzleCalendar`; nothing knows about Discord. Adapted from the
Daily Akari minigame in mklol/tle-gf, with Krillion's single daily score
standing in for Akari's accuracy/time pair: a higher score wins the day and
``MAX_DAY_SCORE`` (700) is a perfect day.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta

from .models import RatingEntry, Result
from .parser import MAX_DAY_SCORE, TIER_EMOJI
from .puzzle import PuzzleCalendar

WEEKDAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")


# -- streaks and skips -------------------------------------------------------


@dataclass(frozen=True)
class Streaks:
    current: int
    longest: int


def streaks(puzzles: Iterable[int], current_puzzle: int) -> Streaks:
    """Consecutive-day runs over ``puzzles``.

    The current run is counted back from today's puzzle, or from yesterday's if
    today has not been played yet — a streak isn't broken until the day closes.
    """
    played = {n for n in puzzles if 0 < n <= current_puzzle}
    if not played:
        return Streaks(0, 0)
    start = current_puzzle if current_puzzle in played else current_puzzle - 1
    current = 0
    while start - current in played:
        current += 1
    longest = run = 0
    previous: int | None = None
    for n in sorted(played):
        run = run + 1 if previous == n - 1 else 1
        longest = max(longest, run)
        previous = n
    return Streaks(current, longest)


def perfect_puzzles(results: Iterable[Result]) -> set[int]:
    return {r.puzzle_number for r in results if r.score >= MAX_DAY_SCORE}


def skipped_puzzles(puzzles: Iterable[int], current_puzzle: int) -> tuple[int | None, list[int]]:
    """``(first played, closed puzzles missed since then)``, most recent first.

    Today's puzzle is never listed while it is still open.
    """
    played = {n for n in puzzles if 0 < n <= current_puzzle}
    if not played:
        return None, []
    first = min(played)
    skipped = [n for n in range(current_puzzle - 1, first, -1) if n not in played]
    return first, skipped


# -- winners -----------------------------------------------------------------


@dataclass(frozen=True)
class DayWinners:
    puzzle_number: int
    winners: tuple[int, ...]
    score: int
    participants: int

    @property
    def tied(self) -> bool:
        return len(self.winners) > 1


def by_puzzle(results: Iterable[Result]) -> dict[int, list[Result]]:
    out: dict[int, list[Result]] = {}
    for r in results:
        out.setdefault(r.puzzle_number, []).append(r)
    return out


def day_winners(results: Iterable[Result], min_participants: int = 2) -> dict[int, DayWinners]:
    """Who posted the top score each day; days with too few divers are skipped."""
    out: dict[int, DayWinners] = {}
    for n, rows in by_puzzle(results).items():
        if len(rows) < min_participants:
            continue
        best = max(r.score for r in rows)
        winners = tuple(sorted(r.user_id for r in rows if r.score == best))
        out[n] = DayWinners(n, winners, best, len(rows))
    return out


@dataclass(frozen=True)
class TopEntry:
    user_id: int
    solo: int
    tied: int

    @property
    def total(self) -> int:
        return self.solo + self.tied


def top(results: Iterable[Result], *, count_ties: bool = False) -> list[TopEntry]:
    """Winners board: outright wins first, shared wins listed alongside.

    With ``count_ties`` a shared top score counts as much as an outright one.
    """
    solo: Counter[int] = Counter()
    tied: Counter[int] = Counter()
    for day in day_winners(results).values():
        bucket = tied if day.tied else solo
        for uid in day.winners:
            bucket[uid] += 1
    entries = [TopEntry(uid, solo[uid], tied[uid]) for uid in solo.keys() | tied.keys()]
    if count_ties:
        entries.sort(key=lambda e: (-e.total, -e.solo, e.user_id))
    else:
        entries.sort(key=lambda e: (-e.solo, -e.tied, e.user_id))
    return entries


# -- head to head ------------------------------------------------------------


@dataclass
class VsPlayer:
    user_id: int
    points: float = 0.0
    wins: int = 0
    losses: int = 0
    ties: int = 0


@dataclass(frozen=True)
class VsOutcome:
    players: list[VsPlayer]
    """Best record first."""
    puzzles: int
    comparisons: int


def head_to_head(
    results: Mapping[int, Sequence[Result]], *, missing_is_loss: bool = False
) -> VsOutcome:
    """Pairwise record over the puzzles the players have in common.

    A win is a point, a tie half a point. With ``missing_is_loss`` a puzzle
    counts as soon as anyone played it and a missing result loses to any score.
    """
    scores: dict[int, dict[int, int]] = {}
    for uid, rows in results.items():
        for r in rows:
            scores.setdefault(r.puzzle_number, {})[uid] = r.score
    players = {uid: VsPlayer(uid) for uid in results}
    puzzles = comparisons = 0
    ordered = list(results)
    for n in sorted(scores):
        day = scores[n]
        if not missing_is_loss and len(day) < len(players):
            continue
        puzzles += 1
        for i, a in enumerate(ordered):
            for b in ordered[i + 1 :]:
                sa, sb = day.get(a, -1), day.get(b, -1)
                if sa < 0 and sb < 0:
                    continue
                comparisons += 1
                if sa == sb:
                    players[a].ties += 1
                    players[b].ties += 1
                    players[a].points += 0.5
                    players[b].points += 0.5
                else:
                    win, lose = (a, b) if sa > sb else (b, a)
                    players[win].wins += 1
                    players[win].points += 1
                    players[lose].losses += 1
    standings = sorted(
        players.values(), key=lambda p: (-p.points, -p.wins, p.losses, ordered.index(p.user_id))
    )
    return VsOutcome(standings, puzzles, comparisons)


# -- timeframes --------------------------------------------------------------

TIMEFRAMES = ("all", "week", "month", "year", "7d", "30d")


def puzzle_range(
    calendar: PuzzleCalendar, timeframe: str, today: date
) -> tuple[int | None, int | None]:
    """Inclusive puzzle-number bounds for a named timeframe ending today."""
    if timeframe == "all":
        return None, None
    if timeframe == "week":
        start = today - timedelta(days=today.weekday())
    elif timeframe == "month":
        start = today.replace(day=1)
    elif timeframe == "year":
        start = today.replace(month=1, day=1)
    elif timeframe.endswith("d") and timeframe[:-1].isdigit():
        start = today - timedelta(days=int(timeframe[:-1]) - 1)
    else:
        raise ValueError(f"Unknown timeframe {timeframe!r}")
    return calendar.number_for_date(start), calendar.number_for_date(today)


# -- personal summary --------------------------------------------------------


@dataclass(frozen=True)
class Summary:
    games: int
    rated_games: int
    wins: int
    tied_wins: int
    best: int | None
    average: float | None
    median: float | None
    perfect_days: int
    streak: Streaks
    perfect_streak: Streaks
    tier_counts: Counter[str]
    weekday_average: dict[int, float]
    """Mean score per ``date.weekday()`` for weekdays played."""
    rating: float | None
    peak: float | None
    last_delta: float | None
    last_performance: float | None
    best_performance: float | None


def summarize(
    user_id: int,
    guild_results: Sequence[Result],
    history: Sequence[RatingEntry],
    calendar: PuzzleCalendar,
    current_puzzle: int,
) -> Summary:
    """Everything ``/krillion stats`` shows for ``user_id``.

    ``guild_results`` is every diver's rows (needed to know who won each day);
    ``history`` is this player's rating history, oldest first.
    """
    results = [r for r in guild_results if r.user_id == user_id]
    scores = [r.score for r in results]
    played = {r.puzzle_number for r in results}
    wins = tied = 0
    for day in day_winners(guild_results).values():
        if user_id in day.winners:
            if day.tied:
                tied += 1
            else:
                wins += 1
    weekday: dict[int, list[int]] = {}
    for r in results:
        weekday.setdefault(calendar.date_for(r.puzzle_number).weekday(), []).append(r.score)
    tiers: Counter[str] = Counter()
    for r in results:
        tiers.update(ch for ch in r.tiers if ch in TIER_EMOJI)
    perfs = [e.performance for e in history if e.performance is not None]
    return Summary(
        games=len(results),
        rated_games=len(history),
        wins=wins,
        tied_wins=tied,
        best=max(scores) if scores else None,
        average=statistics.fmean(scores) if scores else None,
        median=statistics.median(scores) if scores else None,
        perfect_days=len(perfect_puzzles(results)),
        streak=streaks(played, current_puzzle),
        perfect_streak=streaks(perfect_puzzles(results), current_puzzle),
        tier_counts=tiers,
        weekday_average={d: statistics.fmean(v) for d, v in sorted(weekday.items())},
        rating=history[-1].rating_after if history else None,
        peak=max(e.rating_after for e in history) if history else None,
        last_delta=history[-1].delta if history else None,
        last_performance=perfs[-1] if perfs else None,
        best_performance=max(perfs) if perfs else None,
    )


# -- weekly recap ------------------------------------------------------------


def week_bounds(day: date) -> tuple[date, date]:
    """Monday..Sunday span containing ``day``."""
    start = day - timedelta(days=day.weekday())
    return start, start + timedelta(days=6)


@dataclass(frozen=True)
class WeekDay:
    day: date
    puzzle_number: int
    winners: DayWinners | None
    participants: int = 0


@dataclass(frozen=True)
class WeekStanding:
    user_id: int
    days: int
    total: int
    best: int
    solo_wins: int
    tied_wins: int
    perfects: int = 0

    @property
    def average(self) -> float:
        return self.total / self.days

    @property
    def total_wins(self) -> int:
        return self.solo_wins + self.tied_wins


@dataclass(frozen=True)
class RatingMove:
    user_id: int
    before: float
    after: float

    @property
    def delta(self) -> float:
        return self.after - self.before


@dataclass(frozen=True)
class WeekRecap:
    start: date
    end: date
    in_progress: bool
    days: list[WeekDay]
    standings: list[WeekStanding]
    """Ordered by total score, then average."""
    highest: tuple[int, int, date] | None
    """``(user, score, day)`` for the week's top single result."""
    most_improved: tuple[int, float] | None
    """``(user, average gain vs last week)``."""
    moves: list[RatingMove]
    """Rating changes over the week, biggest gain first."""
    players: int
    results: int


def _averages(results: Iterable[Result]) -> dict[int, tuple[float, int]]:
    per_user: dict[int, list[int]] = {}
    for r in results:
        per_user.setdefault(r.user_id, []).append(r.score)
    return {u: (statistics.fmean(s), len(s)) for u, s in per_user.items()}


def build_week_recap(
    results: Sequence[Result],
    history: Sequence[RatingEntry],
    calendar: PuzzleCalendar,
    anchor: date,
    today: date,
) -> WeekRecap:
    """Recap of the Monday–Sunday week holding ``anchor``.

    ``results`` should span at least the previous week too so "most improved"
    has something to compare against; ``history`` only needs the week itself.
    """
    start, end = week_bounds(anchor)
    lo, hi = calendar.number_for_date(start), calendar.number_for_date(end)
    week = [r for r in results if lo <= r.puzzle_number <= hi]
    previous = [r for r in results if lo - 7 <= r.puzzle_number < lo]
    winners = day_winners(week)
    counts = {number: len(rows) for number, rows in by_puzzle(week).items()}
    days = [
        WeekDay(start + timedelta(days=i), lo + i, winners.get(lo + i), counts.get(lo + i, 0))
        for i in range(7)
        if start + timedelta(days=i) <= today
    ]

    per_user: dict[int, list[Result]] = {}
    for r in week:
        per_user.setdefault(r.user_id, []).append(r)
    standings = []
    for uid, rows in per_user.items():
        solo = sum(1 for d in winners.values() if d.winners == (uid,))
        tied = sum(1 for d in winners.values() if d.tied and uid in d.winners)
        scores = [r.score for r in rows]
        standings.append(
            WeekStanding(uid, len(rows), sum(scores), max(scores), solo, tied, scores.count(700))
        )
    standings.sort(key=lambda s: (-s.total, -s.average, -s.solo_wins, s.user_id))

    highest = None
    if week:
        best = max(week, key=lambda r: (r.score, -r.submitted_at.timestamp()))
        highest = (best.user_id, best.score, calendar.date_for(best.puzzle_number))

    active_days = sum(1 for d in days if d.puzzle_number in by_puzzle(week))
    threshold = max(1, (active_days + 1) // 2)
    now_avg, prev_avg = _averages(week), _averages(previous)
    gains = {
        u: avg - prev_avg[u][0]
        for u, (avg, n) in now_avg.items()
        if n >= threshold and u in prev_avg and prev_avg[u][1] >= threshold
    }
    improved = {u: g for u, g in gains.items() if g > 0}
    most_improved = max(improved.items(), key=lambda kv: (kv[1], -kv[0])) if improved else None

    first: dict[int, float] = {}
    last: dict[int, float] = {}
    for e in sorted(history, key=lambda e: e.puzzle_number):
        if lo <= e.puzzle_number <= hi:
            first.setdefault(e.user_id, e.rating_before)
            last[e.user_id] = e.rating_after
    moves = sorted(
        (RatingMove(u, first[u], last[u]) for u in first),
        key=lambda m: (-m.delta, m.user_id),
    )
    return WeekRecap(
        start=start,
        end=end,
        in_progress=start <= today <= end,
        days=days,
        standings=standings,
        highest=highest,
        most_improved=most_improved,
        moves=moves,
        players=len(per_user),
        results=len(week),
    )
