import asyncio
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from krillion_bot.bot import KrillionBot, build
from krillion_bot.config import Config
from krillion_bot.puzzle import PuzzleCalendar
from krillion_bot.service import KrillionService
from krillion_bot.storage import Storage

AEST = ZoneInfo("Australia/Brisbane")
NOW = datetime(2026, 9, 12, 9, 30, tzinfo=AEST)


@dataclass
class FakeMessage:
    content: str
    author_id: int = 1
    channel_id: int = 10
    bot: bool = False
    reactions: list = field(default_factory=list)
    replies: list = field(default_factory=list)
    id: int = 555
    created_at: datetime = NOW

    def __post_init__(self):
        self.author = SimpleNamespace(id=self.author_id, bot=self.bot, display_name="alice")
        self.channel = SimpleNamespace(id=self.channel_id)
        self.guild = SimpleNamespace(id=1)

    async def add_reaction(self, emoji):
        self.reactions.append(emoji)

    async def reply(self, text, **_):
        self.replies.append(text)


ADMIN = 750888871696269402


@dataclass
class FakeInteraction:
    user_id: int
    guild_id: int | None = 1
    sent: list = field(default_factory=list)

    def __post_init__(self):
        self.user = SimpleNamespace(id=self.user_id, mention=f"<@{self.user_id}>")
        self.response = SimpleNamespace(send_message=self._send, defer=self._defer)
        self.followup = SimpleNamespace(send=self._send)

    async def _send(self, content=None, **kwargs):
        self.sent.append((content, kwargs.get("embed"), kwargs.get("ephemeral", False)))
        if "file" in kwargs:
            self.file = kwargs["file"]

    async def _defer(self, **_):
        self.deferred = True

    @property
    def embed(self):
        return self.sent[-1][1]


def run_command(bot: KrillionBot, path: str, interaction, *args, **kwargs):
    command = bot.tree
    for part in path.split():
        command = command.get_command(part)
    assert command is not None, path
    return asyncio.run(command.callback(interaction, *args, **kwargs))


def make_config(tmp_path: Path, **overrides) -> Config:
    base = dict(
        token="x",
        database_path=tmp_path / "db.sqlite3",
        leaderboard_channel_id=None,
        results_channel_id=None,
        late_grace_minutes=10,
        rating_damping=0.25,
        decay_base=0.04,
        decay_max=0.08,
        decay_grace=0,
        puzzle_tz=ZoneInfo("America/New_York"),
        epoch_date=PuzzleCalendar().epoch,
        log_level="INFO",
    )
    base.update(overrides)
    return Config(**base)


def test_build_registers_commands_and_creates_db(tmp_path):
    b = build(make_config(tmp_path))
    assert [c.name for c in b.tree.get_commands()] == ["krillion"]
    assert b.config.admin_user_ids == {ADMIN}
    assert (tmp_path / "db.sqlite3").exists()
    assert b.intents.message_content


def test_on_message_records_result(bot):
    msg = FakeMessage("Krillion #58 🦐\n340\n\n🦑🦑🦑🦑🦑🐟🫧")
    asyncio.run(bot.on_message(msg))
    assert msg.reactions == ["🦐"]
    assert msg.replies == ["Received Krillion #58 score from **alice**: 340 🦐"]
    assert bot.service.storage.get_result(1, 58, 1).score == 340


def test_on_message_ignores_bots_and_chatter(bot):
    for msg in (FakeMessage("Krillion #58\n340", bot=True), FakeMessage("hello")):
        asyncio.run(bot.on_message(msg))
        assert msg.reactions == [] and msg.replies == []


def test_on_message_rejects_old_puzzle(bot):
    msg = FakeMessage("Krillion #57 🦐\n340")
    asyncio.run(bot.on_message(msg))
    assert msg.reactions == ["⏰"]
    assert "today's puzzle is #58" in msg.replies[0]


def test_on_message_duplicate(bot):
    asyncio.run(bot.on_message(FakeMessage("Krillion #58\n340")))
    msg = FakeMessage("Krillion #58\n500")
    asyncio.run(bot.on_message(msg))
    assert msg.reactions == ["⚠️"]
    assert "340" in msg.replies[0]


def test_results_channel_filter(tmp_path):
    cfg = make_config(tmp_path, results_channel_id=10)
    service = KrillionService(Storage(":memory:"), PuzzleCalendar())
    b = KrillionBot(cfg, service)
    asyncio.run(b.on_message(FakeMessage("Krillion #58\n340", channel_id=11)))
    assert service.storage.get_result(1, 58, 1) is None
    asyncio.run(b.on_message(FakeMessage("Krillion #58\n340", channel_id=10)))
    assert service.storage.get_result(1, 58, 1).score == 340
