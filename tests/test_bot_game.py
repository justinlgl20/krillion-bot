import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from test_bot import FakeMessage
from test_commands import ADMIN, post, share

AEST = ZoneInfo("Australia/Brisbane")
# Krillion #59 is Sat 12 Sept 2026 (NY); #60 is Sunday and closes Monday 14:00 AEST.
DURING_60 = datetime(2026, 9, 14, 9, 30, tzinfo=AEST)
AFTER_60 = datetime(2026, 9, 14, 14, 30, tzinfo=AEST)


class FakeChannel:
    def __init__(self, cid: int, messages=()):
        self.id = cid
        self.mention = f"<#{cid}>"
        self.sent: list = []
        self.messages = list(messages)

    async def send(self, content=None, **kwargs):
        self.sent.append((content, kwargs))

    async def history(self, *, limit: int, oldest_first: bool):
        for m in self.messages[:limit]:
            yield m

    async def fetch_message(self, message_id: int):
        return next(m for m in self.messages if m.id == message_id)


def wire(bot, monkeypatch, channel: FakeChannel):
    async def messageable(channel_id: int):
        return channel if channel_id == channel.id else None

    monkeypatch.setattr(bot, "_messageable", messageable)


def test_banned_message_gets_reaction(bot):
    bot.service.storage.ban(1, 1, banned_by=ADMIN, reason=None, at=FakeMessage("x").created_at)
    msg = FakeMessage(share(58, 340))
    asyncio.run(bot.on_message(msg))
    assert msg.reactions == ["🚫"] and msg.replies == []
    assert bot.service.storage.get_result(1, 58, 1) is None


def test_sunday_close_posts_weekly_recap(bot, monkeypatch):
    monkeypatch.setattr("krillion_bot.bot._now", lambda: AFTER_60)
    channel = FakeChannel(10)
    wire(bot, monkeypatch, channel)
    post(bot, 1, "alice", share(60, 700), DURING_60)
    post(bot, 2, "bob", share(60, 200), DURING_60)

    async def close_day():
        for day in bot.service.finalize_due(AFTER_60):
            await bot._announce(day)

    asyncio.run(close_day())
    assert len(channel.sent) == 1  # daily board only: no weekly channel configured
