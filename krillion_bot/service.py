"""Discord-agnostic game logic: accept submissions, close days, run the rating."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum

from .parser import ParsedResult, parse_result
from .puzzle import PuzzleCalendar
from .rating import (
    DAMPING,
    DECAY_BASE,
    DECAY_GRACE,
    DECAY_MAX,
    DayOutcome,
    close_day,
    placements,
)
from .storage import RATING_ENGINE, Player, RatingEntry, Result, Storage


class SubmitStatus(Enum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"
    TOO_LATE = "too_late"
    NOT_YET = "not_yet"
    NOT_A_RESULT = "not_a_result"
    BANNED = "banned"


@dataclass(frozen=True)
class SubmitOutcome:
    status: SubmitStatus
    parsed: ParsedResult | None
    current_puzzle: int
    existing: Result | None = None


@dataclass(frozen=True)
class FinalizedDay:
    guild_id: int
    puzzle_number: int
    channel_id: int
    entries: list[RatingEntry]
    players: dict[int, Player]
    decay: dict[int, float]
    """Rating lost by each absent player (shared out to the day's submitters)."""


@dataclass(frozen=True)
class Invalidation:
    removed: Result
    replayed_days: int
    """Closed days whose Elo was recomputed (0 if the puzzle was still open)."""


@dataclass(frozen=True)
class Deletion:
    removed: int
    recomputed: bool
    """Whether a closed day was touched, so every rating was rebuilt from scratch."""
    replayed_days: int


MAX_INACTIVE_DAYS = 30
"""Divers who haven't played this many puzzles drop off the ratings board."""


class KrillionService:
    def __init__(
        self,
        storage: Storage,
        calendar: PuzzleCalendar | None = None,
        *,
        grace: timedelta = timedelta(minutes=10),
        damping: float = DAMPING,
        decay_base: float = DECAY_BASE,
        decay_max: float = DECAY_MAX,
        decay_grace: int = DECAY_GRACE,
    ) -> None:
        self.storage = storage
        self.calendar = calendar or PuzzleCalendar()
        self.grace = grace
        self.damping = damping
        self.decay_base = decay_base
        self.decay_max = decay_max
        self.decay_grace = decay_grace

    def migrate_ratings(self) -> int:
        """Replay every guild if the stored history came from an older rating engine.

        Returns the number of guilds replayed.
        """
        if self.storage.get_meta("rating_engine") == RATING_ENGINE:
            return 0
        guilds = self.storage.guild_ids()
        for guild_id in guilds:
            self.replay(guild_id)
        self.storage.set_meta("rating_engine", RATING_ENGINE)
        return len(guilds)

    # -- submissions -----------------------------------------------------

    def is_open(self, puzzle_number: int, now: datetime) -> bool:
        """A puzzle accepts results from its start until reset + grace."""
        if now < self.calendar.start(puzzle_number):
            return False
        return now < self.calendar.end(puzzle_number) + self.grace

    def submit(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        text: str,
        channel_id: int,
        message_id: int | None,
        now: datetime,
    ) -> SubmitOutcome:
        current = self.calendar.current(now)
        parsed = parse_result(text)
        if parsed is None:
            return SubmitOutcome(SubmitStatus.NOT_A_RESULT, None, current)
        return self._record(
            guild_id, user_id, display_name, parsed, channel_id, message_id, now, current
        )

    def _record(
        self,
        guild_id: int,
        user_id: int,
        display_name: str,
        parsed: ParsedResult,
        channel_id: int,
        message_id: int | None,
        now: datetime,
        current: int,
    ) -> SubmitOutcome:
        n = parsed.puzzle_number
        if self.storage.is_banned(guild_id, user_id):
            return SubmitOutcome(SubmitStatus.BANNED, parsed, current)
        if n > current:
            return SubmitOutcome(SubmitStatus.NOT_YET, parsed, current)
        if not self.is_open(n, now) or self.storage.is_finalized(guild_id, n):
            return SubmitOutcome(SubmitStatus.TOO_LATE, parsed, current)
        self.storage.upsert_player(guild_id, user_id, display_name)
        result = Result(
            guild_id=guild_id,
            puzzle_number=n,
            user_id=user_id,
            score=parsed.score,
            tiers=parsed.tiers,
            channel_id=channel_id,
            message_id=message_id,
            submitted_at=now,
        )
        if not self.storage.add_result(result):
            existing = self.storage.get_result(guild_id, n, user_id)
            return SubmitOutcome(SubmitStatus.DUPLICATE, parsed, current, existing)
        return SubmitOutcome(SubmitStatus.ACCEPTED, parsed, current)

    def ranked_players(self, guild_id: int, now: datetime, include_inactive: bool) -> list[Player]:
        """Public ratings board: by default nobody
        who has sat out the last :data:`MAX_INACTIVE_DAYS` puzzles."""
        cutoff = self.calendar.current(now) - MAX_INACTIVE_DAYS
        last = self.storage.last_played(guild_id)
        return [
            p
            for p in self.storage.players(guild_id)
            if not self.storage.is_banned(guild_id, p.user_id)
            and (include_inactive or last.get(p.user_id, cutoff) >= cutoff)
        ]

    # -- finalization ----------------------------------------------------

    def rate_day(self, guild_id: int, puzzle_number: int, results: list[Result]) -> DayOutcome:
        """What closing ``puzzle_number`` with ``results`` does to everyone's rating."""
        players = {
            p.user_id: p for p in self.storage.players(guild_id, [r.user_id for r in results])
        }
        scores = {r.user_id: r.score for r in results}
        ratings = {uid: players[uid].rating for uid in scores}
        absent = self.storage.absentees(guild_id, puzzle_number, scores)
        return close_day(
            scores,
            ratings,
            absent,
            damping=self.damping,
            decay_base=self.decay_base,
            decay_max=self.decay_max,
            decay_grace=self.decay_grace,
        )

    def projected_deltas(
        self, guild_id: int, puzzle_number: int, results: list[Result]
    ) -> dict[int, float]:
        """Rating change each submitter would get if ``results`` closed the day now."""
        return self.rate_day(guild_id, puzzle_number, results).deltas

    def next_finalize_at(self, now: datetime) -> datetime:
        return self.calendar.next_reset(now) + self.grace

    def due_puzzles(self, now: datetime) -> list[tuple[int, int]]:
        return [
            (guild_id, n)
            for guild_id, n in self.storage.unfinalized_puzzles()
            if not self.is_open(n, now)
        ]

    def finalize(self, guild_id: int, puzzle_number: int, now: datetime) -> FinalizedDay | None:
        results = self.storage.results_for(guild_id, puzzle_number)
        if not results or self.storage.is_finalized(guild_id, puzzle_number):
            return None
        players = {
            p.user_id: p for p in self.storage.players(guild_id, [r.user_id for r in results])
        }
        scores = {r.user_id: r.score for r in results}
        ratings = {uid: players[uid].rating for uid in scores}
        outcome = self.rate_day(guild_id, puzzle_number, results)
        places = placements(scores)
        entries = [
            RatingEntry(
                puzzle_number=puzzle_number,
                user_id=r.user_id,
                score=r.score,
                placement=places[r.user_id],
                rating_before=ratings[r.user_id],
                rating_after=ratings[r.user_id] + outcome.deltas[r.user_id],
                performance=outcome.performances[r.user_id],
            )
            for r in results
        ]
        self.storage.finalize(guild_id, puzzle_number, entries, now, outcome.decay)
        # Post to the channel the day's results were mostly shared in.
        channel_counts: dict[int, int] = {}
        for r in results:
            channel_counts[r.channel_id] = channel_counts.get(r.channel_id, 0) + 1
        channel_id = max(channel_counts, key=lambda c: channel_counts[c])
        updated = {
            p.user_id: p for p in self.storage.players(guild_id, [r.user_id for r in results])
        }
        return FinalizedDay(guild_id, puzzle_number, channel_id, entries, updated, outcome.decay)

    # -- admin -----------------------------------------------------------

    def invalidate(self, guild_id: int, puzzle_number: int, user_id: int) -> Invalidation | None:
        """Drop a user's result. If that day was already closed, replay ratings from scratch."""
        removed = self.storage.remove_result(guild_id, puzzle_number, user_id)
        if removed is None:
            return None
        if not self.storage.is_finalized(guild_id, puzzle_number):
            return Invalidation(removed, 0)
        return Invalidation(removed, self.replay(guild_id))

    def add_manual(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        puzzle_number: int,
        score: int,
        tiers: str,
        channel_id: int,
        now: datetime,
    ) -> Invalidation | None:
        """Admin insert of a result for any past or current puzzle.

        Returns ``None`` if the user already has a result for that puzzle. A closed
        day is (re)rated by replaying the guild.
        """
        self.storage.upsert_player(guild_id, user_id, display_name)
        result = Result(
            guild_id=guild_id,
            puzzle_number=puzzle_number,
            user_id=user_id,
            score=score,
            tiers=tiers,
            channel_id=channel_id,
            message_id=None,
            submitted_at=now,
        )
        if not self.storage.add_result(result):
            return None
        if self.is_open(puzzle_number, now):
            return Invalidation(result, 0)
        return Invalidation(result, self.replay(guild_id, now))

    def import_result(
        self,
        *,
        guild_id: int,
        user_id: int,
        display_name: str,
        text: str,
        channel_id: int,
        message_id: int,
        created_at: datetime,
    ) -> bool:
        """Backfill a share from channel history, judged by when it was posted.

        Returns whether a new result was stored. Closed days are not rated here;
        the caller replays once the whole channel has been read.
        """
        parsed = parse_result(text)
        if parsed is None or self.storage.is_banned(guild_id, user_id):
            return False
        n = parsed.puzzle_number
        if not self.is_open(n, created_at):
            return False
        self.storage.upsert_player(guild_id, user_id, display_name)
        return self.storage.add_result(
            Result(
                guild_id=guild_id,
                puzzle_number=n,
                user_id=user_id,
                score=parsed.score,
                tiers=parsed.tiers,
                channel_id=channel_id,
                message_id=message_id,
                submitted_at=created_at,
            )
        )

    def correct(
        self, guild_id: int, puzzle_number: int, user_id: int, score: int, tiers: str
    ) -> bool:
        """Overwrite a stored score; the caller replays once all corrections are in."""
        existing = self.storage.get_result(guild_id, puzzle_number, user_id)
        if existing is None or (existing.score, existing.tiers) == (score, tiers):
            return False
        return self.storage.update_result(guild_id, puzzle_number, user_id, score, tiers)

    def delete_puzzles(self, guild_id: int, low: int, high: int) -> Deletion:
        """Drop every result for puzzles ``low..high``, replaying ratings if any was closed."""
        closed = any(low <= n <= high for n, _ in self.storage.finalized_puzzles(guild_id))
        removed = self.storage.delete_results(guild_id, low, high)
        recomputed = bool(removed) and closed
        replayed = self.replay(guild_id) if recomputed else 0
        return Deletion(removed, recomputed, replayed)

    def replay(self, guild_id: int, now: datetime | None = None) -> int:
        """Recompute every closed day's rating from the stored results, in order.

        Returns how many days were re-finalized. A day left with no results stays open
        (it no longer appears in history), but is still too old to accept submissions.
        With ``now``, closed days that were never rated (results added after the fact)
        are rated too, in puzzle order.
        """
        days = dict(self.storage.finalized_puzzles(guild_id))
        if now is not None:
            for g, n in self.storage.unfinalized_puzzles():
                if g == guild_id and n not in days and not self.is_open(n, now):
                    days[n] = now
        self.storage.reset_ratings(guild_id)
        return sum(self.finalize(guild_id, n, days[n]) is not None for n in sorted(days))

    def finalize_due(self, now: datetime) -> list[FinalizedDay]:
        done: list[FinalizedDay] = []
        for guild_id, n in self.due_puzzles(now):
            day = self.finalize(guild_id, n, now)
            if day is not None:
                done.append(day)
        return done
