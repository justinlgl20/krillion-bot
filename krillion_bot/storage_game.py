"""Storage queries behind the game commands: results, bans and admins."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone

from .models import RatingEntry, Result


def _iso(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


class GameStorageMixin:
    """Mixed into :class:`Storage`; relies on its ``_conn`` and ``_result``."""

    _conn: sqlite3.Connection

    @staticmethod
    def _result(row: sqlite3.Row) -> Result:
        raise NotImplementedError

    # -- results ---------------------------------------------------------

    def results_for_user(
        self,
        guild_id: int,
        user_id: int,
        low: int | None = None,
        high: int | None = None,
    ) -> list[Result]:
        """A player's results, oldest puzzle first, optionally limited to ``[low, high]``."""
        where, params = self._range("puzzle_number", low, high)
        rows = self._conn.execute(
            f"SELECT * FROM results WHERE guild_id = ? AND user_id = ?{where} "
            "ORDER BY puzzle_number",
            (guild_id, user_id, *params),
        ).fetchall()
        return [self._result(r) for r in rows]

    def results_between(
        self, guild_id: int, low: int | None = None, high: int | None = None
    ) -> list[Result]:
        """Every result in the guild with puzzle number in ``[low, high]``, oldest first."""
        where, params = self._range("puzzle_number", low, high)
        rows = self._conn.execute(
            f"SELECT * FROM results WHERE guild_id = ?{where} "
            "ORDER BY puzzle_number, score DESC, submitted_at",
            (guild_id, *params),
        ).fetchall()
        return [self._result(r) for r in rows]

    def update_result(
        self, guild_id: int, puzzle_number: int, user_id: int, score: int, tiers: str
    ) -> bool:
        cur = self._conn.execute(
            "UPDATE results SET score = ?, tiers = ? "
            "WHERE guild_id = ? AND puzzle_number = ? AND user_id = ?",
            (score, tiers, guild_id, puzzle_number, user_id),
        )
        return cur.rowcount == 1

    def delete_results(self, guild_id: int, low: int, high: int) -> int:
        """Delete every result with puzzle number in ``[low, high]``; returns the count."""
        cur = self._conn.execute(
            "DELETE FROM results WHERE guild_id = ? AND puzzle_number BETWEEN ? AND ?",
            (guild_id, low, high),
        )
        return cur.rowcount

    def last_played(self, guild_id: int) -> dict[int, int]:
        """Most recent puzzle number each player has a result for."""
        rows = self._conn.execute(
            "SELECT user_id, MAX(puzzle_number) AS n FROM results WHERE guild_id = ? "
            "GROUP BY user_id",
            (guild_id,),
        ).fetchall()
        return {r["user_id"]: r["n"] for r in rows}

    # -- rating history --------------------------------------------------

    def history_for_user(self, guild_id: int, user_id: int) -> list[RatingEntry]:
        rows = self._conn.execute(
            """
            SELECT puzzle_number, user_id, score, placement, rating_before, rating_after,
                   performance
            FROM rating_history WHERE guild_id = ? AND user_id = ?
            ORDER BY puzzle_number
            """,
            (guild_id, user_id),
        ).fetchall()
        return [RatingEntry(**r) for r in rows]

    def history_between(self, guild_id: int, low: int, high: int) -> list[RatingEntry]:
        rows = self._conn.execute(
            """
            SELECT puzzle_number, user_id, score, placement, rating_before, rating_after,
                   performance
            FROM rating_history WHERE guild_id = ? AND puzzle_number BETWEEN ? AND ?
            ORDER BY puzzle_number, placement
            """,
            (guild_id, low, high),
        ).fetchall()
        return [RatingEntry(**r) for r in rows]

    # -- bans ------------------------------------------------------------

    def ban(
        self, guild_id: int, user_id: int, banned_by: int, reason: str | None, at: datetime
    ) -> bool:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO bans (guild_id, user_id, banned_by, reason, banned_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (guild_id, user_id, banned_by, reason, _iso(at)),
        )
        return cur.rowcount == 1

    def is_banned(self, guild_id: int, user_id: int) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM bans WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        ).fetchone()
        return row is not None

    # -- delegated admins ------------------------------------------------

    def add_admin(self, guild_id: int, user_id: int) -> bool:
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO guild_admins (guild_id, user_id) VALUES (?, ?)",
            (guild_id, user_id),
        )
        return cur.rowcount == 1

    def remove_admin(self, guild_id: int, user_id: int) -> bool:
        cur = self._conn.execute(
            "DELETE FROM guild_admins WHERE guild_id = ? AND user_id = ?", (guild_id, user_id)
        )
        return cur.rowcount == 1

    def admins(self, guild_id: int) -> set[int]:
        rows = self._conn.execute(
            "SELECT user_id FROM guild_admins WHERE guild_id = ?", (guild_id,)
        ).fetchall()
        return {r["user_id"] for r in rows}

    # -- helpers ---------------------------------------------------------

    @staticmethod
    def _range(column: str, low: int | None, high: int | None) -> tuple[str, tuple[int, ...]]:
        where = ""
        params: tuple[int, ...] = ()
        if low is not None:
            where += f" AND {column} >= ?"
            params += (low,)
        if high is not None:
            where += f" AND {column} <= ?"
            params += (high,)
        return where, params

    def user_ids(self, guild_id: int, user_ids: Iterable[int]) -> list[int]:
        """Filter ``user_ids`` to those with at least one result in the guild."""
        ids = list(user_ids)
        if not ids:
            return []
        marks = ",".join("?" * len(ids))
        rows = self._conn.execute(
            f"SELECT DISTINCT user_id FROM results WHERE guild_id = ? AND user_id IN ({marks})",
            (guild_id, *ids),
        ).fetchall()
        return [r["user_id"] for r in rows]
