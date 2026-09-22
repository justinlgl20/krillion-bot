"""Weekly server recap panel (``/krillion week`` and the Monday auto-post)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import timedelta

from matplotlib.figure import Figure

from .analytics import WeekRecap
from .charts import (
    AMBER,
    BG,
    BLUE,
    DARK,
    GREEN,
    MUTED,
    RED,
    TEXT,
    WEEKDAYS,
    clip,
    draw_names,
    empty_note,
    figure,
    kpi_strip,
    name_color,
    panel,
    png,
    safe_name,
)

Names = Mapping[int, str]
Ratings = Mapping[int, float]


def _label(names: Names, ratings: Ratings, user_id: int, limit: int = 18) -> tuple[str, str]:
    name = clip(safe_name(names.get(user_id, f"user {user_id}")), limit)
    return name, name_color(ratings.get(user_id))


def _labels(
    names: Names, ratings: Ratings, ids: Sequence[int], limit: int = 2
) -> list[tuple[str, str]]:
    shown = [_label(names, ratings, uid, 14) for uid in ids[:limit]]
    if len(ids) > limit:
        shown.append((f"+{len(ids) - limit}", MUTED))
    return shown


def _draw_days(fig: Figure, recap: WeekRecap, names: Names, ratings: Ratings) -> None:
    ax = panel(fig, (0.04, 0.375, 0.44, 0.44), "DAY BY DAY  ·  WINNERS", GREEN)
    step = 1 / 7
    for i, day in enumerate(recap.days):
        y = 1 - step * (i + 0.5)
        ax.text(0.04, y, WEEKDAYS[day.day.weekday()], va="center", color=MUTED, fontsize=8)
        ax.text(0.135, y, f"{day.day:%m-%d}", va="center", color=MUTED, fontsize=8)
        if day.winners is None:
            label = "no results" if day.participants == 0 else "no winner"
            ax.text(0.26, y, label, va="center", color=MUTED, fontsize=9, style="italic")
            continue
        draw_names(ax, 0.26, y, _labels(names, ratings, day.winners.winners), weight="bold")
        if day.winners.tied:
            ax.text(0.71, y, "TIED", va="center", color=AMBER, fontsize=7, weight="bold")
        ax.text(
            0.855,
            y,
            str(day.winners.score),
            va="center",
            ha="right",
            color=DARK,
            fontsize=9,
            weight="bold",
        )
        ax.text(
            0.97,
            y,
            f"{day.winners.participants}p",
            va="center",
            ha="right",
            color=MUTED,
            fontsize=8,
        )
    for i in range(len(recap.days), 7):
        y = 1 - step * (i + 0.5)
        ax.text(0.04, y, WEEKDAYS[i], va="center", color=MUTED, fontsize=8)
        future = recap.start + timedelta(days=i)
        ax.text(0.135, y, f"{future:%m-%d}", va="center", color=MUTED, fontsize=8)
        ax.text(0.26, y, "up next", va="center", color=MUTED, fontsize=9, style="italic")


def _draw_standings(fig: Figure, recap: WeekRecap, names: Names, ratings: Ratings) -> None:
    ax = panel(fig, (0.53, 0.55, 0.43, 0.265), "WEEK LEADERBOARD  ·  WINS", BLUE)
    top = sorted(recap.standings, key=lambda s: (-s.total_wins, -s.solo_wins, s.user_id))[:6]
    if not top:
        empty_note(ax, "Nobody has played this week.")
        return
    step = 1 / max(4, len(top))
    for i, s in enumerate(top):
        y = 1 - step * (i + 0.5)
        ax.text(0.04, y, f"#{i + 1}", va="center", color=BLUE, fontsize=9, weight="bold")
        draw_names(ax, 0.13, y, [_label(names, ratings, s.user_id)])
        ax.text(
            0.72,
            y,
            f"{s.total_wins} win{'s' if s.total_wins != 1 else ''}",
            va="center",
            ha="right",
            color=TEXT,
            fontsize=9,
            weight="bold",
        )
        detail = f"{s.solo_wins} solo · {s.tied_wins} tied"
        ax.text(0.98, y, detail, va="center", ha="right", color=MUTED, fontsize=8)


def _draw_standouts(fig: Figure, recap: WeekRecap, names: Names, ratings: Ratings) -> None:
    ax = panel(fig, (0.53, 0.375, 0.43, 0.115), "STANDOUTS", AMBER)
    rows: list[tuple[str, int, str, str]] = []
    if recap.highest is not None:
        uid, score, day = recap.highest
        rows.append(("HIGHEST SCORE", uid, str(score), f"{day:%a %d %b}"))
    if recap.most_improved is not None:
        uid, gain = recap.most_improved
        rows.append(("MOST IMPROVED", uid, f"+{gain:.0f}", "avg vs last week"))
    if not rows:
        empty_note(ax, "Not enough results for standouts.")
        return
    step = 1 / 2
    for i, (label, uid, value, detail) in enumerate(rows):
        y = 1 - step * (i + 0.5)
        ax.text(0.04, y, label, va="center", color=MUTED, fontsize=8, weight="bold")
        draw_names(ax, 0.35, y, [_label(names, ratings, uid)], fontsize=9)
        ax.text(0.76, y, value, va="center", ha="right", color=AMBER, fontsize=9, weight="bold")
        ax.text(0.98, y, detail, va="center", ha="right", color=MUTED, fontsize=7)


def _draw_moves(fig: Figure, recap: WeekRecap, names: Names, ratings: Ratings) -> None:
    ax = panel(fig, (0.04, 0.08, 0.2833, 0.225), "DAILY RATING  ·  THIS WEEK", DARK)
    if not recap.moves:
        empty_note(ax, "No daily rating movement this week.")
        return
    gains = [m for m in recap.moves if m.delta >= 0][:3]
    losses = [m for m in recap.moves if m.delta < 0][-3:]
    rows = [(m, True) for m in gains] + [(m, False) for m in losses]
    step = 1 / 6
    for i, (m, gaining) in enumerate(rows):
        y = 1 - step * (i + 0.5)
        color = GREEN if m.delta >= 0 else RED
        ax.text(0.03, y, "▲" if gaining else "▼", va="center", color=color, fontsize=7)
        draw_names(ax, 0.09, y, [_label(names, ratings, m.user_id)], fontsize=9)
        ax.text(
            0.76,
            y,
            f"{round(m.after)}",
            va="center",
            ha="right",
            color=TEXT,
            fontsize=9,
            weight="bold",
        )
        ax.text(
            0.98,
            y,
            f"{m.delta:+.0f}",
            va="center",
            ha="right",
            color=color,
            fontsize=9,
            weight="bold",
        )


def _draw_scores(fig: Figure, recap: WeekRecap, names: Names, ratings: Ratings) -> None:
    ax = panel(fig, (0.3583, 0.08, 0.2833, 0.225), "TOTAL SCORE  ·  THIS WEEK", BLUE)
    top = sorted(recap.standings, key=lambda s: (-s.total, -s.average, s.user_id))[:6]
    if not top:
        empty_note(ax, "No results this week.")
        return
    step = 1 / 6
    for i, s in enumerate(top):
        y = 1 - step * (i + 0.5)
        ax.text(0.03, y, f"#{i + 1}", va="center", color=BLUE, fontsize=8, weight="bold")
        draw_names(ax, 0.13, y, [_label(names, ratings, s.user_id, 14)], fontsize=8)
        ax.text(
            0.98,
            y,
            f"{s.total}  avg {s.average:.0f}",
            va="center",
            ha="right",
            color=TEXT,
            fontsize=8,
            weight="bold",
        )


def _draw_averages(fig: Figure, recap: WeekRecap, names: Names, ratings: Ratings) -> None:
    ax = panel(fig, (0.6767, 0.08, 0.2833, 0.225), "BEST AVERAGE  ·  FULL WEEK ONLY", AMBER)
    elapsed = sum(day.day <= recap.end for day in recap.days)
    top = [s for s in recap.standings if s.days == elapsed]
    top.sort(key=lambda s: (-s.average, s.user_id))
    if not top:
        empty_note(ax, "Nobody played every day this week.")
        return
    for i, s in enumerate(top[:6]):
        y = 1 - (i + 0.5) / 6
        ax.text(0.03, y, f"#{i + 1}", va="center", color=AMBER, fontsize=8, weight="bold")
        draw_names(ax, 0.13, y, [_label(names, ratings, s.user_id, 14)], fontsize=8)
        ax.text(
            0.98,
            y,
            f"{s.average:.0f}  {s.days} days",
            va="center",
            ha="right",
            color=TEXT,
            fontsize=8,
            weight="bold",
        )


def _personal(recap: WeekRecap, viewer: int | None) -> str:
    mine = next((s for s in recap.standings if s.user_id == viewer), None)
    if mine is None:
        return "YOU HAVE NO RESULTS THIS WEEK" if viewer is not None else ""
    wins_board = sorted(recap.standings, key=lambda s: (-s.total_wins, -s.solo_wins, s.user_id))
    rank = wins_board.index(mine) + 1
    parts = [f"{mine.days} PLAYED", f"{mine.perfects} PERFECT"]
    if mine.solo_wins or mine.tied_wins:
        parts.append(f"{mine.solo_wins} SOLO WIN(S) · {mine.tied_wins} TIED")
    parts.append(f"{mine.best} BEST")
    parts.append(f"#{rank} ON THE BOARD")
    return "YOUR WEEK  ·  " + "  ·  ".join(parts)


def week_plot(
    recap: WeekRecap, names: Names, ratings: Ratings, *, viewer: int | None = None
) -> bytes:
    """Render the recap; ``ratings`` colours each name by the diver's rank."""
    fig = figure(16, 9)
    header = fig.add_axes((0.04, 0.935, 0.92, 0.05))
    header.set_facecolor(BG)
    header.axis("off")
    header.text(0, 0.78, "KRILLION  /  WEEKLY SERVER RECAP", color=GREEN, fontsize=9, weight="bold")
    header.text(
        0,
        0.1,
        f"{recap.start:%b %d} – {recap.end:%b %d, %Y}",
        color=TEXT,
        fontsize=20,
        weight="bold",
    )
    status = "IN PROGRESS" if recap.in_progress else "FINAL"
    if recap.standings:
        leader = sorted(recap.standings, key=lambda s: (-s.total_wins, -s.solo_wins, s.user_id))[0]
        name, _ = _label(names, ratings, leader.user_id)
        wins = leader.total_wins
        status = f"{name} leads · {wins} win{'s' if wins != 1 else ''}  ·  {status}"
    header.text(
        1, 0.3, status, color=AMBER if recap.in_progress else MUTED, fontsize=9, weight="bold",
        ha="right",
    )  # fmt: skip

    played = [d for d in recap.days if d.participants > 0]
    kpi_strip(
        fig,
        [
            (str(recap.players), "PLAYERS", GREEN),
            (str(recap.results), "RESULTS", GREEN),
            (f"{len(played)}/7", "DAYS PLAYED", BLUE),
            (
                str(sum(1 for d in played if d.winners and not d.winners.tied)),
                "DECIDED OUTRIGHT",
                BLUE,
            ),
            (str(sum(1 for d in played if d.winners and d.winners.tied)), "TIED DAYS", AMBER),
        ],
        GREEN,
    )
    _draw_days(fig, recap, names, ratings)
    _draw_standings(fig, recap, names, ratings)
    _draw_standouts(fig, recap, names, ratings)
    _draw_moves(fig, recap, names, ratings)
    _draw_scores(fig, recap, names, ratings)
    _draw_averages(fig, recap, names, ratings)
    fig.text(0.04, 0.03, _personal(recap, viewer), color=TEXT, fontsize=9, weight="bold")
    fig.text(
        0.96, 0.03, "WEEK RUNS MONDAY → SUNDAY", color=MUTED, fontsize=7, weight="bold", ha="right"
    )
    return png(fig)
