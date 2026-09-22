from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import discord
import pytest
from test_bot import run_command as run

from krillion_bot.bot import KrillionBot

AEST = ZoneInfo("Australia/Brisbane")
NOW = datetime(2026, 9, 12, 9, 30, tzinfo=AEST)  # during #58
ADMIN = 750888871696269402


@dataclass
class Fake:
    user_id: int
    guild_id: int = 1
    name: str = "alice"
    sent: list = field(default_factory=list)
    files: list = field(default_factory=list)
    deferred: bool = False
    channel_id: int = 10

    def __post_init__(self):
        self.user = SimpleNamespace(
            id=self.user_id, mention=f"<@{self.user_id}>", display_name=self.name
        )
        self.response = SimpleNamespace(send_message=self._send, defer=self._defer)
        self.followup = SimpleNamespace(send=self._send)

    async def _send(self, content=None, **kwargs):
        self.sent.append((content, kwargs.get("embed"), kwargs.get("ephemeral", False)))
        if "file" in kwargs:
            self.files.append(kwargs["file"])

    async def _defer(self, **_):
        self.deferred = True

    @property
    def text(self) -> str:
        content, embed, _ = self.sent[-1]
        return content or (embed.description if embed else "") or (embed.title if embed else "")

    @property
    def embed(self):
        return self.sent[-1][1]

    def board(self, filename: str, heading: str) -> None:
        """A table went out as a PNG, or as text where no font is installed."""
        if self.files:
            assert self.files[-1].filename == filename
        else:
            assert heading in self.text or heading in (self.embed.title or "")


def member(uid: int, name: str):
    return SimpleNamespace(id=uid, display_name=name, mention=f"<@{uid}>")


def share(n: int, score: int, tiers: str = "🦑🦑🦑🦑🦑🐟🫧") -> str:
    return f"Krillion #{n} 🦐\n{score}\n\n{tiers}"


def post(bot, uid, name, text, when=NOW):
    return bot.service.submit(
        guild_id=1,
        user_id=uid,
        display_name=name,
        text=text,
        channel_id=10,
        message_id=None,
        now=when,
    )


@pytest.fixture
def kb(bot, monkeypatch) -> KrillionBot:
    monkeypatch.setattr("krillion_bot.bot._now", lambda: NOW)
    return bot


@pytest.fixture
def seeded(kb) -> KrillionBot:
    day_ago = NOW - timedelta(days=1)
    post(kb, 1, "alice", share(57, 700, "🦑🦑🦑🦑🦑🦑🦑"), day_ago)
    post(kb, 2, "bob", share(57, 300), day_ago)
    kb.service.finalize_due(NOW)
    post(kb, 1, "alice", share(58, 340))
    post(kb, 2, "bob", share(58, 500))
    return kb


def test_all_subcommands_registered(kb):
    group = kb.tree.get_command("krillion")
    names = {c.name for c in group.commands}
    assert names >= {
        "leaderboard", "ratings", "top", "stats", "rating", "performance", "history",
        "streak", "skips", "vs", "week", "puzzle", "admin",
    }  # fmt: skip
    admin = {c.name for c in group.get_command("admin").commands}
    assert admin == {"ban"}


def test_stats_and_streak(seeded):
    i = Fake(1)
    run(seeded, "krillion stats", i)
    assert i.deferred and i.files[0].filename == "krillion-stats.png"
    i = Fake(1)
    run(seeded, "krillion stats", i, member(2, "bob"))
    assert i.deferred and i.files[0].filename == "krillion-stats.png"
    i = Fake(1)
    run(seeded, "krillion stats", i, member(9, "nobody"))
    assert i.sent[-1][2] is True
    assert "hasn't shared" in i.embed.description
    i = Fake(1)
    run(seeded, "krillion streak", i)
    assert i.embed.title == "Krillion Streak"
    assert "`alice`: **1** consecutive perfect day(s)" in i.embed.description
    assert "Latest result: **340 pts**" in i.embed.description


def test_skips_and_history(seeded):
    post(seeded, 3, "carol", share(58, 100))
    seeded.service.add_manual(
        guild_id=1,
        user_id=3,
        display_name="carol",
        puzzle_number=55,
        score=200,
        tiers="",
        channel_id=10,
        now=NOW,
    )
    i = Fake(3, name="carol")
    run(seeded, "krillion skips", i)
    assert "#56" in i.embed.description and "#57" in i.embed.description
    assert "#58" not in i.embed.description
    i = Fake(1)
    run(seeded, "krillion history", i)
    assert "#57" in i.embed.description and "700" in i.embed.description
    i = Fake(9, name="nobody")
    run(seeded, "krillion history", i)
    assert i.embed.description == "`nobody` has no contested Krillion days yet."


def test_rating_and_performance(seeded):
    i = Fake(1)
    run(seeded, "krillion rating", i)
    assert i.deferred and i.files[0].filename == "krillion-rating.png"
    assert i.embed.title == "Krillion rating — alice"
    i = Fake(9, name="nobody")
    run(seeded, "krillion performance", i)
    assert i.embed.description == "No Krillion rating for `nobody` yet."
    post(seeded, 1, "alice", share(56, 100), NOW - timedelta(days=2))
    post(seeded, 2, "bob", share(56, 600), NOW - timedelta(days=2))
    seeded.service.replay(1, NOW)
    i = Fake(1)
    run(seeded, "krillion performance", i)
    assert i.files and i.files[0].filename == "krillion-rating.png"
    assert i.embed.title == "Krillion performance — alice"


def test_top_and_vs(seeded):
    i = Fake(1)
    run(seeded, "krillion top", i)
    i.board("krillion-top.png", "Krillion Winners")
    i = Fake(1)
    run(seeded, "krillion top", i, "week", True)
    i.board("krillion-top.png", "Krillion Winners (With Ties)")
    i = Fake(1)
    run(seeded, "krillion top", i, "year", True)
    i.board("krillion-top.png", "Krillion Winners (With Ties)")
    i = Fake(1)
    run(seeded, "krillion vs", i, member(1, "alice"), member(2, "bob"))
    assert "alice" in i.embed.description and "bob" in i.embed.description
    assert "1" in i.embed.description
    i = Fake(1)
    run(seeded, "krillion vs", i, member(1, "alice"), member(1, "alice"))
    assert "different" in i.embed.description and i.sent[-1][2] is True
    i = Fake(1)
    run(seeded, "krillion vs", i, member(1, "alice"), member(9, "nobody"))
    assert i.embed.description == "These users have no Krillion puzzles to compare."


def test_week(seeded):
    i = Fake(1)
    run(seeded, "krillion week", i)
    assert i.deferred and i.files[0].filename.startswith("krillion-week-")
    i = Fake(1)
    run(seeded, "krillion week", i, "last")
    assert "No Krillion results" in i.embed.description
    i = Fake(1)
    run(seeded, "krillion week", i, "not-a-date")
    assert i.sent[-1][2] is True


def test_leaderboard_ratings_puzzle(seeded):
    i = Fake(1)
    run(seeded, "krillion leaderboard", i)
    i.board("krillion-58-live.png", "Krillion #58 — live")
    i = Fake(1)
    run(seeded, "krillion leaderboard", i, 57)
    i.board("krillion-57.png", "Krillion #57")
    i = Fake(1)
    run(seeded, "krillion leaderboard", i, 50)
    assert "No results for Krillion #50 yet." == i.embed.description
    i = Fake(1)
    run(seeded, "krillion ratings", i)
    i.board("krillion-ratings.png", "Ratings")
    i = Fake(1)
    run(seeded, "krillion puzzle", i)
    assert "**#58**" in i.embed.description


def test_admin_ban(kb):
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin ban", a, member(2, "bob"), "cheating")
    assert "bob` from Krillion tracking." in a.embed.description
    assert "Reason: cheating" in a.embed.description
    assert post(kb, 2, "bob", share(58, 700)).status.value == "banned"
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin ban", a, member(2, "bob"))
    assert "already banned" in a.embed.description


def test_manage_server_is_not_admin(kb):
    mod = Fake(5, name="mod")

    class Mod(discord.Member):
        def __init__(self):
            pass

        id = 5
        display_name = "mod"
        mention = "<@5>"
        guild_permissions = discord.Permissions(manage_guild=True, administrator=True)

    mod.user = Mod()
    run(kb, "krillion admin ban", mod, member(2, "bob"))
    assert mod.sent[-1][2] is True
    assert "admin" in mod.embed.description.lower()
    assert post(kb, 2, "bob", share(58, 700)).status.value != "banned"
