from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from krillion_bot.puzzle import PuzzleCalendar
from krillion_bot.service import KrillionService, SubmitStatus
from krillion_bot.storage import Storage

AEST = ZoneInfo("Australia/Brisbane")
GUILD = 1
CHANNEL = 10
DURING_58 = datetime(2026, 9, 12, 9, 30, tzinfo=AEST)
RESET_59 = datetime(2026, 9, 12, 14, 0, tzinfo=AEST)
AFTER_58 = RESET_59 + timedelta(hours=1)


def share(n: int, score: int) -> str:
    return f"Krillion #{n} 🦐\n{score}\n\n🦑🦑🦑🦑🦑🐟🫧"


@pytest.fixture
def service() -> KrillionService:
    return KrillionService(Storage(":memory:"), PuzzleCalendar(), grace=timedelta(minutes=10))


def submit(service, user, name, text, now=DURING_58):
    return service.submit(
        guild_id=GUILD,
        user_id=user,
        display_name=name,
        text=text,
        channel_id=CHANNEL,
        message_id=None,
        now=now,
    )


def add(service, user, n, score, now=DURING_58):
    return service.add_manual(
        guild_id=GUILD,
        user_id=user,
        display_name=f"u{user}",
        puzzle_number=n,
        score=score,
        tiers="",
        channel_id=CHANNEL,
        now=now,
    )


def test_bans_reject_results(service):
    s = service.storage
    assert s.ban(GUILD, 2, banned_by=99, reason="cheating", at=DURING_58)
    assert not s.ban(GUILD, 2, banned_by=99, reason=None, at=DURING_58)
    assert s.is_banned(GUILD, 2) and not s.is_banned(GUILD, 1)


def test_delegated_admins(service):
    s = service.storage
    assert s.add_admin(GUILD, 5) and not s.add_admin(GUILD, 5)
    assert s.admins(GUILD) == {5} and s.admins(2) == set()
    assert s.remove_admin(GUILD, 5) and not s.remove_admin(GUILD, 5)


def test_result_queries(service):
    s = service.storage
    for n, score in ((55, 100), (56, 200), (58, 300)):
        add(service, 1, n, score, now=DURING_58)
    add(service, 2, 58, 500)
    assert [r.puzzle_number for r in s.results_for_user(GUILD, 1)] == [55, 56, 58]
    assert [r.score for r in s.results_for_user(GUILD, 1, low=56)] == [200, 300]
    assert [r.score for r in s.results_for_user(GUILD, 1, high=56)] == [100, 200]
    assert len(s.results_between(GUILD, 58, 58)) == 2
    assert s.last_played(GUILD) == {1: 58, 2: 58}
    assert s.user_ids(GUILD, [1, 2, 3]) == [1, 2]
    assert s.user_ids(GUILD, []) == []


# -- service: bans and ranked board -------------------------------------------


def test_banned_user_is_rejected(service):
    service.storage.ban(GUILD, 1, banned_by=99, reason=None, at=DURING_58)
    out = submit(service, 1, "alice", share(58, 340))
    assert out.status is SubmitStatus.BANNED
    assert service.storage.get_result(GUILD, 58, 1) is None


def test_ranked_players_prunes_banned_and_inactive(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 200))
    submit(service, 3, "carol", share(58, 100))
    service.storage.ban(GUILD, 3, banned_by=99, reason=None, at=DURING_58)
    board = service.ranked_players(GUILD, DURING_58, include_inactive=False)
    assert [p.user_id for p in board] == [1, 2]
    much_later = DURING_58 + timedelta(days=40)
    assert service.ranked_players(GUILD, much_later, include_inactive=False) == []
    assert [
        p.user_id for p in service.ranked_players(GUILD, much_later, include_inactive=True)
    ] == [1, 2]


# -- service: admin result management -----------------------------------------


def test_add_manual_open_day_does_not_rate(service):
    out = add(service, 1, 58, 640)
    assert out is not None and out.replayed_days == 0
    assert out.removed.score == 640
    assert add(service, 1, 58, 100) is None  # duplicate


def test_add_manual_closed_day_replays(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 200))
    assert len(service.finalize_due(AFTER_58)) == 1
    assert service.storage.get_player(GUILD, 1).rating > 1200
    out = add(service, 3, 58, 700, now=AFTER_58)
    assert out is not None and out.replayed_days == 1
    assert service.storage.get_player(GUILD, 3).rating > 1200
    assert service.storage.get_player(GUILD, 1).rating < service.storage.get_player(GUILD, 3).rating
    assert {e.user_id for e in service.storage.history_for(GUILD, 58)} == {1, 2, 3}


def test_add_manual_rates_previously_unrated_closed_day(service):
    # #57 closed with no results, so it was never finalized; a manual add rates it.
    out = add(service, 1, 57, 500, now=DURING_58)
    assert out is not None and out.replayed_days == 1
    assert service.storage.is_finalized(GUILD, 57)


def test_correct_and_delete(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 200))
    assert service.correct(GUILD, 58, 1, 100, "🐟")
    assert not service.correct(GUILD, 58, 1, 100, "🐟")
    assert not service.correct(GUILD, 58, 9, 100, "")
    assert service.storage.get_result(GUILD, 58, 1).score == 100
    service.finalize_due(AFTER_58)
    assert service.storage.get_player(GUILD, 2).rating > 1200
    deletion = service.delete_puzzles(GUILD, 58, 58)
    assert (deletion.removed, deletion.recomputed, deletion.replayed_days) == (2, True, 0)
    assert service.storage.results_for(GUILD, 58) == []
    assert service.storage.get_player(GUILD, 2).rating == 1200
    assert service.delete_puzzles(GUILD, 58, 58).removed == 0


def test_delete_range_replays_remaining_days(service):
    add(service, 1, 56, 300)
    add(service, 2, 56, 200)
    add(service, 1, 57, 300)
    add(service, 2, 57, 500)
    assert service.replay(GUILD, DURING_58) == 2
    deletion = service.delete_puzzles(GUILD, 57, 57)
    assert (deletion.removed, deletion.recomputed, deletion.replayed_days) == (2, True, 1)
    assert not service.storage.is_finalized(GUILD, 57)
    assert service.storage.get_player(GUILD, 1).rating > service.storage.get_player(GUILD, 2).rating


def test_import_result_uses_post_time(service):
    kwargs = dict(guild_id=GUILD, user_id=1, display_name="alice", channel_id=CHANNEL)
    assert (
        service.import_result(**kwargs, text=share(56, 300), message_id=1, created_at=AFTER_58)
        is False
    )
    on_time = DURING_58 - timedelta(days=2)
    assert service.import_result(**kwargs, text=share(56, 300), message_id=2, created_at=on_time)
    assert not service.import_result(
        **kwargs, text=share(56, 300), message_id=3, created_at=on_time
    )
    assert not service.import_result(**kwargs, text="hello", message_id=4, created_at=on_time)
    service.storage.ban(GUILD, 2, banned_by=99, reason=None, at=DURING_58)
    assert not service.import_result(
        **{**kwargs, "user_id": 2}, text=share(56, 300), message_id=5, created_at=on_time
    )
    assert service.replay(GUILD, DURING_58) == 1
    assert service.storage.get_result(GUILD, 56, 1).message_id == 2
