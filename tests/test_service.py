from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from helpers import tiers_for

from krillion_bot.formatting import DISPLAY_EMOJI, final_table, live_table, ratings_table
from krillion_bot.puzzle import PuzzleCalendar
from krillion_bot.rating import compute_round
from krillion_bot.service import KrillionService, SubmitStatus
from krillion_bot.storage import RATING_ENGINE, Storage

AEST = ZoneInfo("Australia/Brisbane")
GUILD = 1
CHANNEL = 10

# Krillion #58 is live from 11 Sept 2026 14:00 AEST until 12 Sept 14:00 AEST
# (midnight to midnight, New York).
DURING_58 = datetime(2026, 9, 12, 9, 30, tzinfo=AEST)
RESET_59 = datetime(2026, 9, 12, 14, 0, tzinfo=AEST)


def share(n: int, score: int) -> str:
    return f"Krillion #{n} 🦐\n{score}\n\n{tiers_for(score)}"


# Head-to-head between two 1200s: what the Queens-bot engine hands the winner/loser.
WIN, LOSE = compute_round({1: 1200.0, 2: 1200.0}, {1: 1, 2: 2}).values()


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


def test_accepts_todays_result(service):
    out = submit(service, 1, "alice", share(58, 340))
    assert out.status is SubmitStatus.ACCEPTED
    assert out.current_puzzle == 58
    stored = service.storage.get_result(GUILD, 58, 1)
    assert stored is not None and stored.score == 340 and stored.tiers == tiers_for(340)
    assert service.storage.get_player(GUILD, 1).rating == 1200


def test_ignores_chatter(service):
    assert submit(service, 1, "alice", "good morning").status is SubmitStatus.NOT_A_RESULT


def test_duplicate_keeps_first(service):
    submit(service, 1, "alice", share(58, 340))
    out = submit(service, 1, "alice", share(58, 600))
    assert out.status is SubmitStatus.DUPLICATE
    assert out.existing.score == 340
    assert service.storage.get_result(GUILD, 58, 1).score == 340


def test_rejects_wrong_day(service):
    assert submit(service, 1, "alice", share(57, 340)).status is SubmitStatus.TOO_LATE
    assert submit(service, 1, "alice", share(59, 340)).status is SubmitStatus.NOT_YET


def test_grace_period_after_reset(service):
    just_after = RESET_59 + timedelta(minutes=5)
    assert submit(service, 1, "alice", share(58, 340), now=just_after).status is (
        SubmitStatus.ACCEPTED
    )
    assert submit(service, 2, "bob", share(59, 200), now=just_after).status is (
        SubmitStatus.ACCEPTED
    )
    too_late = RESET_59 + timedelta(minutes=10)
    assert submit(service, 3, "carol", share(58, 340), now=too_late).status is (
        SubmitStatus.TOO_LATE
    )


def test_nothing_due_while_day_open(service):
    submit(service, 1, "alice", share(58, 340))
    assert service.finalize_due(RESET_59 + timedelta(minutes=9)) == []
    assert service.next_finalize_at(DURING_58) == RESET_59 + timedelta(minutes=10)


def test_finalize_applies_rating_and_posts_once(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 120))
    submit(service, 3, "carol", share(58, 120))

    close = RESET_59 + timedelta(minutes=10)
    days = service.finalize_due(close)
    assert len(days) == 1
    day = days[0]
    assert (day.guild_id, day.puzzle_number, day.channel_id) == (GUILD, 58, CHANNEL)
    by_user = {e.user_id: e for e in day.entries}
    assert by_user[1].placement == 1
    assert by_user[2].placement == 2 and by_user[3].placement == 2
    expected = compute_round({1: 1200.0, 2: 1200.0, 3: 1200.0}, {1: 1, 2: 2, 3: 2})
    assert {u: e.delta for u, e in by_user.items()} == pytest.approx(expected)
    assert by_user[2].performance == by_user[3].performance
    assert by_user[1].performance > by_user[2].performance
    assert service.storage.get_player(GUILD, 1).rating == pytest.approx(1200 + expected[1])
    assert service.storage.history_for(GUILD, 58)[0].performance == pytest.approx(
        by_user[1].performance
    )
    assert day.decay == {}

    # Idempotent: a second pass does nothing, and late results are refused.
    assert service.finalize_due(close + timedelta(hours=1)) == []
    assert submit(service, 4, "dave", share(58, 700), now=close).status is SubmitStatus.TOO_LATE


def test_finalizes_missed_days_after_downtime(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 100))
    later = RESET_59 + timedelta(days=1, hours=1)
    submit(service, 1, "alice", share(59, 200), now=RESET_59 + timedelta(hours=2))
    submit(service, 2, "bob", share(59, 250), now=RESET_59 + timedelta(hours=2))
    days = service.finalize_due(later)
    assert [d.puzzle_number for d in days] == [58, 59]
    # alice won #58 then lost #59 to a now slightly lower-rated bob.
    alice = service.storage.get_player(GUILD, 1).rating
    bob = service.storage.get_player(GUILD, 2).rating
    assert alice < 1200 + WIN and bob > 1200 + LOSE
    assert bob > alice


def test_live_projection_matches_finalization(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 120))
    submit(service, 3, "carol", share(58, 250))
    results = service.storage.results_for(GUILD, 58)
    projected = service.rate_day(GUILD, 58, results)
    assert projected.deltas == pytest.approx(service.projected_deltas(GUILD, 58, results))
    day = service.finalize_due(RESET_59 + timedelta(minutes=10))[0]
    assert {e.user_id: e.delta for e in day.entries} == pytest.approx(projected.deltas)
    assert {e.user_id: e.performance for e in day.entries} == pytest.approx(projected.performances)


def test_solo_day_changes_nothing(service):
    submit(service, 1, "alice", share(58, 340))
    day = service.finalize_due(RESET_59 + timedelta(minutes=10))[0]
    assert day.entries[0].delta == 0 and day.entries[0].performance is None
    assert service.storage.get_player(GUILD, 1).rating == 1200


def test_absent_players_decay_towards_1200_and_pay_the_active(service):
    cal = service.calendar
    # #58: alice beats bob, so alice > 1200 > bob. #59: only bob and carol play.
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 120))
    service.finalize_due(cal.end(58) + timedelta(minutes=10))
    alice_before = service.storage.get_player(GUILD, 1).rating
    now59 = cal.start(59) + timedelta(hours=1)
    submit(service, 2, "bob", share(59, 100), now=now59)
    submit(service, 3, "carol", share(59, 200), now=now59)
    assert service.storage.absentees(GUILD, 59, [2, 3]) == {1: (alice_before, 1)}
    day = service.finalize_due(cal.end(59) + timedelta(minutes=10))[0]
    lost = 0.04 * (alice_before - 1200)
    assert day.decay == {1: pytest.approx(-lost)}
    assert service.storage.get_player(GUILD, 1).rating == pytest.approx(alice_before - lost)
    contest = compute_round({2: 1200 + LOSE, 3: 1200.0}, {2: 2, 3: 1})
    deltas = {e.user_id: e.delta for e in day.entries}
    assert deltas[2] == pytest.approx(contest[2] + lost / 2)
    assert deltas[3] == pytest.approx(contest[3] + lost / 2)
    # Bob sat out #60 while below 1200: no upward drift, streak counted from his last game.
    now60 = cal.start(60) + timedelta(hours=1)
    submit(service, 3, "carol", share(60, 100), now=now60)
    submit(service, 4, "dave", share(60, 200), now=now60)
    absent = service.storage.absentees(GUILD, 60, [3, 4])
    assert absent[1][1] == 2 and absent[2][1] == 1
    day60 = service.finalize_due(cal.end(60) + timedelta(minutes=10))[0]
    assert day60.decay[2] == 0.0 and day60.decay[1] < 0


def test_migrate_ratings_replays_once(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 120))
    service.finalize_due(RESET_59 + timedelta(minutes=10))
    # Simulate history written by the old pairwise engine.
    service.storage._conn.execute("UPDATE players SET rating = 1216 WHERE user_id = 1")
    assert service.migrate_ratings() == 1
    assert service.storage.get_player(GUILD, 1).rating == pytest.approx(1200 + WIN)
    assert service.storage.get_meta("rating_engine") == RATING_ENGINE
    assert service.migrate_ratings() == 0


def test_invalidate_open_day_allows_resubmit(service):
    submit(service, 1, "alice", share(58, 700))
    assert service.invalidate(GUILD, 58, 2) is None
    out = service.invalidate(GUILD, 58, 1)
    assert out is not None and out.removed.score == 700 and out.replayed_days == 0
    assert service.storage.get_result(GUILD, 58, 1) is None
    assert submit(service, 1, "alice", share(58, 340)).status is SubmitStatus.ACCEPTED


def test_invalidate_closed_day_replays_ratings(service):
    cal = service.calendar
    # #58: alice 340, bob 120, mallory 700 (bogus). #59: alice 200 vs bob 250.
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 120))
    submit(service, 3, "mallory", share(58, 700))
    service.finalize_due(cal.end(58) + timedelta(minutes=10))
    now59 = cal.start(59) + timedelta(hours=1)
    submit(service, 1, "alice", share(59, 200), now=now59)
    submit(service, 2, "bob", share(59, 250), now=now59)
    service.finalize_due(cal.end(59) + timedelta(minutes=10))
    assert service.storage.get_player(GUILD, 3).rating > 1200

    out = service.invalidate(GUILD, 58, 3)
    assert out is not None and out.replayed_days == 2

    # Same ratings as if mallory had never played #58.
    clean = KrillionService(Storage(":memory:"), PuzzleCalendar())
    submit(clean, 1, "alice", share(58, 340))
    submit(clean, 2, "bob", share(58, 120))
    clean.finalize_due(cal.end(58) + timedelta(minutes=10))
    submit(clean, 1, "alice", share(59, 200), now=now59)
    submit(clean, 2, "bob", share(59, 250), now=now59)
    clean.finalize_due(cal.end(59) + timedelta(minutes=10))
    for uid in (1, 2):
        assert service.storage.get_player(GUILD, uid).rating == pytest.approx(
            clean.storage.get_player(GUILD, uid).rating
        )
    assert service.storage.get_player(GUILD, 3).rating == 1200
    assert service.storage.games_played(GUILD) == {1: 2, 2: 2}
    assert [e.user_id for e in service.storage.history_for(GUILD, 58)] == [1, 2]
    assert service.storage.is_finalized(GUILD, 58) and service.storage.is_finalized(GUILD, 59)
    # Nothing is left dangling for the scheduler to re-close.
    assert service.finalize_due(cal.end(59) + timedelta(days=1)) == []


def test_invalidate_only_result_leaves_day_empty(service):
    submit(service, 1, "alice", share(58, 700))
    service.finalize_due(RESET_59 + timedelta(minutes=10))
    out = service.invalidate(GUILD, 58, 1)
    assert out is not None and out.replayed_days == 0
    assert not service.storage.is_finalized(GUILD, 58)
    assert service.storage.history_for(GUILD, 58) == []
    assert submit(
        service, 1, "alice", share(58, 340), now=RESET_59 + timedelta(hours=1)
    ).status is (SubmitStatus.TOO_LATE)


def test_stats_and_games(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 100))
    service.finalize_due(RESET_59 + timedelta(minutes=10))
    s = service.storage.stats_for(GUILD, 1)
    assert (s.games, s.wins, s.best_score, s.average_score) == (1, 1, 340, 340)
    assert service.storage.games_played(GUILD) == {1: 1, 2: 1}


def test_guilds_are_isolated(service):
    submit(service, 1, "alice", share(58, 340))
    other = service.submit(
        guild_id=2,
        user_id=1,
        display_name="alice",
        text=share(58, 340),
        channel_id=99,
        message_id=None,
        now=DURING_58,
    )
    assert other.status is SubmitStatus.ACCEPTED
    assert service.storage.results_for(2, 58)[0].channel_id == 99


def test_formatting(service):
    submit(service, 1, "alice", share(58, 340))
    submit(service, 2, "bob", share(58, 120))
    results = service.storage.results_for(GUILD, 58)
    players = {p.user_id: p for p in service.storage.players(GUILD)}
    outcome = service.rate_day(GUILD, 58, results)
    live = live_table(
        58,
        results,
        players,
        deltas=outcome.deltas,
        performances=outcome.performances,
        reset_unix=1_800_000_000,
    )
    assert live.header == ("#", "Name", "Result", "Score", "Perf", "Δ")
    assert [c.text for c in live.rows[0]] == [
        "1",
        "alice (1200 E)",
        tiers_for(340).translate(DISPLAY_EMOJI),
        "340",
        "1391",
        "+24",
    ]
    assert [c.text for c in live.rows[1]] == [
        "2",
        "bob (1200 E)",
        tiers_for(120).translate(DISPLAY_EMOJI),
        "120",
        "1009",
        "-25",
    ]
    assert live.rows[0][1].color == live.rows[1][1].color == (0, 0, 255)
    assert live.rows[0][4].color == (170, 0, 170) and live.rows[1][4].color == (0, 128, 0)
    assert live.rows[0][5].color == (0, 128, 0) and live.rows[1][5].color == (128, 128, 128)
    text = live.text()
    assert text.startswith("**Krillion #58 — live** 🦐\n")
    assert (
        f"` 1.`  **alice (1200 E)**  {tiers_for(340).translate(DISPLAY_EMOJI)}  340  1391  +24"
        in text
    )
    assert "<t:1800000000:R>" in text

    day = service.finalize_due(RESET_59 + timedelta(minutes=10))[0]
    tiers = {r.user_id: r.tiers for r in results}
    final = final_table(58, service.calendar.date_for(58), day.entries, day.players, tiers)
    assert final.title == "Krillion #58 2026-09-11 Results"
    assert [c.text for c in final.rows[0]] == [c.text for c in live.rows[0]]
    assert final.notes == []

    table = ratings_table(service.storage.players(GUILD), service.storage.games_played(GUILD))
    assert table is not None and table.header == ("#", "Name", "Rating", "Games")
    assert [c.text for c in table.rows[0]] == ["1", "alice", "1224 · E", "1"]
    assert [c.text for c in table.rows[1]] == ["2", "bob", "1175 · S", "1"]
    assert ratings_table([], {}) is None


def test_black_square_shown_as_snail(service):
    submit(service, 1, "alice", "Krillion #58 🦐\n85\n\n🫧🫧🐟🫧🫧🤡⬛")
    results = service.storage.results_for(GUILD, 58)
    assert results[0].tiers == "🫧🫧🐟🫧🫧🤡⬛"
    players = {p.user_id: p for p in service.storage.players(GUILD)}
    live = live_table(58, results, players, deltas={1: 0.0}, performances={1: None})
    assert live.rows[0][2].text == "🫧🫧🐟🫧🫧🤡🐌"
    assert "🫧🫧🐟🫧🫧🤡🐌" in live.text()


def test_formatting_notes(service):
    submit(service, 1, "alice", share(58, 340))
    results = service.storage.results_for(GUILD, 58)
    players = {p.user_id: p for p in service.storage.players(GUILD)}
    live = live_table(58, results, players, deltas={1: 0.0}, performances={1: None})
    assert [c.text for c in live.rows[0]] == [
        "1",
        "alice (1200 E)",
        tiers_for(340).translate(DISPLAY_EMOJI),
        "340",
        "",
        "+0",
    ]
    assert live.notes == ["_Only one diver so far, so no rating change yet._"]
    day = service.finalize_due(RESET_59 + timedelta(minutes=10))[0]
    final = final_table(58, service.calendar.date_for(58), day.entries, day.players, {}, day.decay)
    assert final.notes == ["_Only one diver today, so no rating change._"]
    decayed = final_table(
        58, service.calendar.date_for(58), day.entries, day.players, {}, {7: -8.0, 8: 0.0}
    )
    assert decayed.notes[-1] == "_Δ includes +8 each from 1 inactive diver's rating decay._"
