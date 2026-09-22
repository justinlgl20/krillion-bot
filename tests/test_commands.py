from dataclasses import dataclass, field
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

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
        self.sent.append((content, kwargs.get("ephemeral", False)))
        if "file" in kwargs:
            self.files.append(kwargs["file"])

    async def _defer(self, **_):
        self.deferred = True

    @property
    def text(self) -> str:
        return self.sent[-1][0]

    def board(self, filename: str, heading: str) -> None:
        """A table went out as a PNG, or as text where no font is installed."""
        if self.files:
            assert self.files[-1].filename == filename
        else:
            assert heading in self.text


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
        "streak", "skips", "vs", "week", "puzzle", "giveup", "register", "unregister",
        "show", "admin", "config",
    }  # fmt: skip
    admin = {c.name for c in group.get_command("admin").commands}
    assert admin == {
        "remove", "add", "delete", "recompute", "reparse", "import", "export",
        "ban", "unban", "bans", "admins",
    }  # fmt: skip
    assert {c.name for c in group.get_command("config").commands} == {"channel"}


def test_stats_and_streak(seeded):
    i = Fake(1)
    run(seeded, "krillion stats", i)
    text = i.text
    assert "**alice**" in text and "2 played" in text and "Best 700" in text
    assert "1 win" in text and "streak" in text.lower() and "Rating **" in text
    i = Fake(1)
    run(seeded, "krillion stats", i, member(2, "bob"))
    assert "bob" in i.text
    i = Fake(1)
    run(seeded, "krillion stats", i, member(9, "nobody"))
    assert i.sent[-1][1] is True and "hasn't shared" in i.text
    i = Fake(1)
    run(seeded, "krillion streak", i)
    assert "2" in i.text and "alice" in i.text


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
    assert "#56" in i.text and "#57" in i.text and "#58" not in i.text
    i = Fake(1)
    run(seeded, "krillion history", i)
    assert "#57" in i.text and "700" in i.text
    i = Fake(9, name="nobody")
    run(seeded, "krillion history", i)
    assert "no rated" in i.text.lower()


def test_rating_and_performance(seeded):
    i = Fake(1)
    run(seeded, "krillion rating", i)
    assert "alice" in i.text and "Chart appears" in i.text  # one rated day: no chart yet
    i = Fake(9, name="nobody")
    run(seeded, "krillion performance", i)
    assert "no rated" in i.text
    post(seeded, 1, "alice", share(56, 100), NOW - timedelta(days=2))
    post(seeded, 2, "bob", share(56, 600), NOW - timedelta(days=2))
    seeded.service.replay(1, NOW)
    i = Fake(1)
    run(seeded, "krillion performance", i)
    assert i.files and i.files[0].filename == "krillion-rating.png"


def test_top_and_vs(seeded):
    i = Fake(1)
    run(seeded, "krillion top", i)
    i.board("krillion-top.png", "Krillion Winners — all time")
    i = Fake(1)
    run(seeded, "krillion top", i, "week", True)
    i.board("krillion-top.png", "this week")
    i = Fake(1)
    run(seeded, "krillion top", i, "year", True)
    i.board("krillion-top.png", "this year")
    i = Fake(1)
    run(seeded, "krillion vs", i, member(1, "alice"), member(2, "bob"))
    assert "alice" in i.text and "bob" in i.text and "1" in i.text
    i = Fake(1)
    run(seeded, "krillion vs", i, member(1, "alice"), member(1, "alice"))
    assert "different" in i.text
    i = Fake(1)
    run(seeded, "krillion vs", i, member(1, "alice"), member(9, "nobody"))
    assert "No puzzles in common" in i.text


def test_week(seeded):
    i = Fake(1)
    run(seeded, "krillion week", i)
    assert "alice" in i.text and "bob" in i.text
    i = Fake(1)
    run(seeded, "krillion week", i, "last")
    assert "No Krillion results" in i.text
    i = Fake(1)
    run(seeded, "krillion week", i, "not-a-date")
    assert i.sent[-1][1] is True


def test_leaderboard_ratings_puzzle(seeded):
    i = Fake(1)
    run(seeded, "krillion leaderboard", i)
    i.board("krillion-58-live.png", "Krillion #58 — live")
    i = Fake(1)
    run(seeded, "krillion leaderboard", i, 57)
    i.board("krillion-57.png", "Krillion #57")
    i = Fake(1)
    run(seeded, "krillion leaderboard", i, 50)
    assert "no results yet" in i.text
    i = Fake(1)
    run(seeded, "krillion ratings", i)
    i.board("krillion-ratings.png", "Ratings")
    i = Fake(1)
    run(seeded, "krillion puzzle", i)
    assert "**#58**" in i.text


def test_giveup_register_show(kb):
    i = Fake(1)
    run(kb, "krillion giveup", i)
    assert "gave up" in i.text
    assert kb.service.storage.get_result(1, 58, 1).score == 0
    i = Fake(1)
    run(kb, "krillion giveup", i)
    assert i.sent[-1][1] is True and "already" in i.text
    i = Fake(1)
    run(kb, "krillion unregister", i)
    assert kb.service.storage.opted_out(1) == {1}
    i = Fake(1)
    run(kb, "krillion unregister", i)
    assert "already hidden" in i.text
    i = Fake(1)
    run(kb, "krillion register", i)
    assert kb.service.storage.opted_out(1) == set()
    i = Fake(1)
    run(kb, "krillion show", i)
    assert "#58" in i.text and i.sent[-1][1] is True


def test_admin_gate_accepts_delegates_and_manage_guild(kb):
    outsider = Fake(999, name="zed")
    run(kb, "krillion admin bans", outsider)
    assert outsider.text == "Only Krillion admins can do that."
    kb.service.storage.add_admin(1, 999)
    delegate = Fake(999, name="zed")
    run(kb, "krillion admin bans", delegate)
    assert "Nobody is banned" in delegate.text


def test_admin_add_remove_delete(kb):
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin add", a, member(1, "alice"), 640)
    assert "Added Krillion #58 score **640**" in a.text
    assert kb.service.storage.get_result(1, 58, 1).score == 640
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin add", a, member(1, "alice"), 100)
    assert "already has" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin add", a, member(1, "alice"), 100, 99)
    assert "isn't out yet" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin add", a, member(2, "bob"), 300, 57)
    assert "recalculated across 1 closed day" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin remove", a, member(1, "alice"), 58)
    assert "invalidated by" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin delete", a, 57)
    assert "Deleted 1 result(s) for Krillion #57" in a.text
    assert "recalculated across 0 closed day(s)" in a.text
    assert kb.service.storage.get_player(1, 2).rating == 1200
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin delete", a, 60, 50)
    assert "No results stored for Krillion #50–#60" in a.text


def test_admin_recompute_and_export(seeded):
    a = Fake(ADMIN, name="admin")
    run(seeded, "krillion admin recompute", a)
    assert a.deferred and "recomputed across 1 closed day" in a.text
    a = Fake(ADMIN, name="admin")
    run(seeded, "krillion admin export", a)
    csv_text = a.files[0].fp.read().decode()
    assert csv_text.startswith("puzzle,date,user_id,name,score,tiers,submitted_at")
    assert "57,2026-09-10,1,alice,700" in csv_text


def test_admin_bans_and_admins(kb):
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin ban", a, member(2, "bob"), "cheating")
    assert "bob** is banned" in a.text and "Reason: cheating" in a.text
    assert post(kb, 2, "bob", share(58, 700)).status.value == "banned"
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin ban", a, member(2, "bob"))
    assert "already banned" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin bans", a)
    assert "<@2>" in a.text and "cheating" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin unban", a, member(2, "bob"))
    assert "can share" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin unban", a, member(2, "bob"))
    assert "isn't banned" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin admins", a, "add", member(5, "eve"))
    assert "is now" in a.text and 5 in kb.admin_ids(1)
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin admins", a, "list")
    assert "<@5>" in a.text and f"<@{ADMIN}>" in a.text
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion admin admins", a, "remove", member(5, "eve"))
    assert "no longer" in a.text and 5 not in kb.admin_ids(1)


def test_config_channel(kb):
    a = Fake(ADMIN, name="admin")
    chan = SimpleNamespace(id=77, mention="<#77>")
    run(kb, "krillion config channel", a, "results", chan)
    assert "<#77>" in a.text
    assert kb.channel_setting(1, "results_channel") == 77
    a = Fake(ADMIN, name="admin")
    run(kb, "krillion config channel", a, "results")
    assert "_default_" in a.text and kb.channel_setting(1, "results_channel") is None
