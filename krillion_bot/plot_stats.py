"""Seven-day player dashboard for ``/krillion stats``."""

from __future__ import annotations

import statistics
from collections.abc import Sequence
from datetime import date, timedelta

from matplotlib import dates as mdates

from .analytics import Summary
from .charts import figure, name_color, png, safe_name
from .models import Result
from .parser import MAX_DAY_SCORE
from .puzzle import PuzzleCalendar

_BG = "#F3F7F5"
_TEXT = "#18251F"
_MUTED = "#66756D"
_GREEN = "#16845B"
_GREEN_DARK = "#0C6444"
_BLUE = "#356B9E"
_AMBER = "#A46100"
_RED = "#C63C55"
_GRID = "#DCE6E1"
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")


def _panel(fig, rect: tuple[float, float, float, float]):
    ax = fig.add_axes(rect, facecolor="white")
    for spine in ax.spines.values():
        spine.set_visible(False)
    return ax


def _kpi(fig, x: float, label: str, value: str, detail: str, color: str) -> None:
    ax = _panel(fig, (x, 0.745, 0.215, 0.115))
    ax.axvline(0, color=color, linewidth=5)
    ax.axis("off")
    ax.text(0.06, 0.77, label, color=_MUTED, fontsize=8, weight="bold")
    ax.text(0.06, 0.42, value, color=color, fontsize=20, weight="bold")
    ax.text(0.06, 0.12, detail, color=_TEXT, fontsize=8)


def _status(score: int | None, day: date, today: date) -> tuple[str, str]:
    if score is not None:
        return ("PERFECT", _GREEN) if score == MAX_DAY_SCORE else (f"{score} PTS", _AMBER)
    if day > today:
        return "UP NEXT", _MUTED
    if day == today:
        return "OPEN", _BLUE
    return "MISSED", _RED


def _strip(fig, scores: dict[date, int], week: Sequence[date], today: date) -> None:
    for i, day in enumerate(week):
        ax = _panel(fig, (0.04 + i * 0.132, 0.535, 0.118, 0.145))
        ax.axis("off")
        score = scores.get(day)
        status, color = _status(score, day, today)
        ax.axhline(1, color=color, linewidth=5)
        ax.text(0.08, 0.78, WEEKDAYS[i], color=_TEXT, fontsize=9, weight="bold")
        ax.text(0.92, 0.78, f"{day:%d}", color=_MUTED, fontsize=8, ha="right")
        ax.text(
            0.08,
            0.43,
            "—" if score is None else str(score),
            color=color,
            fontsize=14,
            weight="bold",
        )
        ax.text(0.08, 0.12, status, color=color, fontsize=7, weight="bold")


def _trend(fig, rows: Sequence[Result], calendar: PuzzleCalendar) -> None:
    ax = _panel(fig, (0.04, 0.09, 0.575, 0.375))
    ax.tick_params(colors=_MUTED, labelsize=8, length=0)
    recent = rows[-35:]
    dates = [calendar.date_for(r.puzzle_number) for r in recent]
    perfect = [(d, r.score) for d, r in zip(dates, recent, strict=True) if r.score == MAX_DAY_SCORE]
    imperfect = [
        (d, r.score) for d, r in zip(dates, recent, strict=True) if r.score != MAX_DAY_SCORE
    ]
    if perfect:
        ax.scatter(*zip(*perfect, strict=True), color=_GREEN, s=34, label="Perfect")
    if imperfect:
        ax.scatter(*zip(*imperfect, strict=True), color=_AMBER, marker="x", s=34, label="Imperfect")
    if len(recent) >= 3:
        window = min(7, max(3, len(recent) // 3))
        values = [r.score for r in recent]
        average = [
            statistics.fmean(values[i - window + 1 : i + 1]) for i in range(window - 1, len(values))
        ]
        ax.plot(
            dates[window - 1 :],
            average,
            color=_GREEN_DARK,
            linewidth=2.2,
            label=f"{window}-run average",
        )
    else:
        ax.text(
            0.5,
            0.88,
            "A few more results unlock the average line",
            transform=ax.transAxes,
            color=_MUTED,
            fontsize=8,
            ha="center",
        )
    ax.set_ylim(0, 750)
    ax.set_ylabel("SCORE  ·  HIGHER ↑", color=_MUTED, fontsize=8, weight="bold")
    ax.grid(axis="y", color=_GRID, linewidth=0.7)
    ax.xaxis.set_major_locator(mdates.AutoDateLocator(minticks=3, maxticks=6))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d"))
    ax.set_title(
        "SCORE LAB  ·  LAST 35 RESULTS", color=_TEXT, fontsize=10, weight="bold", loc="left"
    )
    legend = ax.legend(loc="lower right", frameon=False, fontsize=8)
    for text in legend.get_texts():
        text.set_color(_MUTED)


def _weekday_dna(fig, rows: Sequence[Result], calendar: PuzzleCalendar) -> None:
    ax = _panel(fig, (0.66, 0.09, 0.30, 0.375))
    counts = [0] * 7
    perfects = [0] * 7
    scores: list[list[int]] = [[] for _ in range(7)]
    for row in rows:
        weekday = calendar.date_for(row.puzzle_number).weekday()
        counts[weekday] += 1
        perfects[weekday] += row.score == MAX_DAY_SCORE
        scores[weekday].append(row.score)
    rates = [100 * p / n if n else 0 for p, n in zip(perfects, counts, strict=True)]
    strengths = [
        max(0.025, rate / 100) if count else 0 for rate, count in zip(rates, counts, strict=True)
    ]
    colors = [_GREEN if rate >= 80 else _BLUE if rate >= 50 else _AMBER for rate in rates]
    bars = ax.barh(range(7), strengths, color=colors, height=0.57)
    ax.set_yticks(range(7), WEEKDAYS)
    ax.invert_yaxis()
    ax.set_xlim(0, 1.43)
    ax.set_xticks([])
    ax.tick_params(length=0, colors=_TEXT, labelsize=8)
    for bar, count, perfect, values in zip(bars, counts, perfects, scores, strict=True):
        y = bar.get_y() + bar.get_height() / 2
        label = f"{perfect}/{count} PERFECT" if count else "NO DATA"
        avg = f"AVG {statistics.fmean(values):.0f}" if values else "NO SCORE"
        ax.text(0.04, y, label, va="center", color=_TEXT, fontsize=7, weight="bold")
        ax.text(1.40, y, avg, va="center", ha="right", color=_TEXT, fontsize=7)
    ax.set_title(
        "DAY DNA  ·  PERFECT RATE + SCORE", color=_TEXT, fontsize=10, weight="bold", loc="left"
    )


def stats_plot(
    name: str, summary: Summary, rows: Sequence[Result], calendar: PuzzleCalendar, today: date
) -> bytes:
    fig = figure(16, 10)
    fig.set_facecolor(_BG)
    header = fig.add_axes((0.04, 0.89, 0.92, 0.075), facecolor=_BG)
    header.axis("off")
    header.text(
        0, 0.72, "KRILLION  /  7-DAY PLAYER DASHBOARD", color=_GREEN, fontsize=10, weight="bold"
    )
    header.text(
        0, 0.08, safe_name(name), color=name_color(summary.rating), fontsize=24, weight="bold"
    )
    week_start = today - timedelta(days=today.weekday())
    header.text(
        1,
        0.18,
        f"LATEST WEEK  ·  {week_start:%b %d, %Y}",
        color=_MUTED,
        fontsize=9,
        weight="bold",
        ha="right",
    )
    first = calendar.date_for(rows[0].puzzle_number)
    _kpi(fig, 0.04, "RUNS LOGGED", str(summary.games), f"since {first:%b %d, %Y}", _BLUE)
    rate = 100 * summary.perfect_days / summary.games
    _kpi(
        fig,
        0.275,
        "PERFECT RATE",
        f"{rate:.0f}%",
        f"{summary.perfect_days}/{summary.games} perfect results",
        _GREEN,
    )
    _kpi(fig, 0.51, "PERSONAL BEST", str(summary.best), f"median {summary.median:.0f}", _AMBER)
    _kpi(
        fig,
        0.745,
        "PERFECT STREAK",
        str(summary.perfect_streak.current),
        f"longest {summary.perfect_streak.longest} days",
        _RED,
    )
    week = [week_start + timedelta(days=i) for i in range(7)]
    scores = {calendar.date_for(r.puzzle_number): r.score for r in rows}
    played = [day for day in week if day in scores]
    perfects = sum(scores[day] == MAX_DAY_SCORE for day in played)
    summary_text = (
        f"{len(played)}/{sum(day <= today for day in week)} PLAYED  ·  {perfects} PERFECT"
    )
    if played:
        summary_text += f"  ·  {max(scores[day] for day in played)} BEST"
    fig.text(0.04, 0.695, summary_text, color=_TEXT, fontsize=9, weight="bold")
    _strip(fig, scores, week, today)
    _trend(fig, rows, calendar)
    _weekday_dna(fig, rows, calendar)
    footer = fig.add_axes((0.04, 0.02, 0.92, 0.035), facecolor=_BG)
    footer.axis("off")
    footer.text(
        0,
        0.5,
        "PERFECT DAYS SCORE 700  ·  WEEK RUNS MONDAY → SUNDAY",
        color=_MUTED,
        fontsize=7,
        weight="bold",
        va="center",
    )
    return png(fig)
