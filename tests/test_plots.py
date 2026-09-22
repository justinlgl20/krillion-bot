import io
from datetime import date, datetime, timezone

from PIL import Image

from krillion_bot.analytics import build_week_recap, summarize
from krillion_bot.models import RatingEntry, Result
from krillion_bot.plot_stats import stats_plot
from krillion_bot.plot_week import week_plot
from krillion_bot.puzzle import PuzzleCalendar

CALENDAR = PuzzleCalendar()
NOW = datetime(2026, 7, 18, tzinfo=timezone.utc)


def result(puzzle: int, user: int, score: int) -> Result:
    return Result(1, puzzle, user, score, "", 10, None, NOW)


def history(puzzle: int, user: int, before: float, after: float, perf: float | None) -> RatingEntry:
    return RatingEntry(puzzle, user, 500, 1, before, after, perf)


def png_image(data: bytes) -> Image.Image:
    image = Image.open(io.BytesIO(data))
    assert image.format == "PNG"
    assert image.width > 300 and image.height > 150
    return image


def test_stats_plot_renders_seeded_dashboard_and_single_result():
    rows = [result(4, 1, 700), result(5, 1, 500), result(6, 1, 600)]
    all_rows = rows + [result(4, 2, 300), result(5, 2, 400), result(6, 2, 200)]
    entries = [
        history(4, 1, 1200, 1210, 1300),
        history(5, 1, 1210, 1220, 1320),
        history(6, 1, 1220, 1230, 1340),
    ]
    summary = summarize(1, all_rows, entries, CALENDAR, current_puzzle=6)
    assert png_image(stats_plot("alice", summary, rows, CALENDAR, date(2026, 7, 18)))

    one = [result(4, 1, 700)]
    single_summary = summarize(1, one, [], CALENDAR, current_puzzle=6)
    assert png_image(stats_plot("alice", single_summary, one, CALENDAR, date(2026, 7, 18)))


def test_week_plot_renders_with_viewer_and_unknown_user_label():
    rows = [
        result(4, 1, 700),
        result(4, 2, 400),
        result(5, 1, 500),
        result(5, 2, 600),
    ]
    entries = [
        history(4, 1, 1200, 1210, 1300),
        history(5, 1, 1210, 1220, 1320),
        history(4, 2, 1200, 1190, 1100),
        history(5, 2, 1190, 1200, 1150),
    ]
    recap = build_week_recap(
        rows, entries, CALENDAR, anchor=date(2026, 7, 15), today=date(2026, 7, 18)
    )
    assert png_image(week_plot(recap, {1: "alice", 2: "bob"}, {1: 1210, 2: 1190}, viewer=1))
    assert png_image(week_plot(recap, {}, {}, viewer=99))
