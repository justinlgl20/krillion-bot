"""Matplotlib base for the tle-gf style dashboards, plus the rating graph.

Everything here draws on an explicit :class:`Figure` with the Agg canvas, so
rendering is safe to run off the event loop and never touches pyplot state.
Player names are drawn in their rank colour; :func:`safe_name` strips what the
Agg text renderer cannot shape (control characters, colour emoji).
"""

from __future__ import annotations

import io
import unicodedata
from collections.abc import Sequence

import matplotlib
from matplotlib.axes import Axes
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from .models import RatingEntry
from .puzzle import PuzzleCalendar
from .rating import RANKS, rank_for_rating

matplotlib.use("Agg")

BG = "#F4F6FA"
PANEL = "#FFFFFF"
TEXT = "#172033"
MUTED = "#667085"
GRID = "#DCE6E1"
RED = "#C63C55"
GREEN = "#16845B"
DARK = "#0C6444"
BLUE = "#356B9E"
AMBER = "#A46100"
LINE_COLORS = ("#5d4dff", "#009ccc", "#00ba6a", "#b99d27", "#cb2aff")
WEEKDAYS = ("MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN")
DPI = 100


def hex_color(rgb: tuple[int, int, int]) -> str:
    return "#{:02x}{:02x}{:02x}".format(*rgb)


def band_color(rgb: tuple[int, int, int]) -> str:
    """Lighten a rank colour into a pastel band."""
    r, g, b = (int(c + (255 - c) * 0.72) for c in rgb)
    return hex_color((r, g, b))


def name_color(rating: float | None) -> str:
    return hex_color(rank_for_rating(round(rating)).color) if rating is not None else TEXT


def safe_name(value: str) -> str:
    """Single line, no control/format characters or symbols Agg draws as boxes."""
    chars = []
    for ch in str(value):
        category = unicodedata.category(ch)
        if ch.isspace():
            if chars and chars[-1] != " ":
                chars.append(" ")
        elif category[0] != "C" and category != "So" and ord(ch) < 0x10000:
            chars.append(ch)
    return "".join(chars).strip() or "Player"


def clip(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def figure(width: float, height: float) -> Figure:
    fig = Figure(figsize=(width, height), dpi=DPI, facecolor=BG)
    FigureCanvasAgg(fig)
    return fig


def png(fig: Figure) -> bytes:
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=fig.get_facecolor())
    return buf.getvalue()


def style(ax: Axes) -> None:
    ax.set_facecolor(PANEL)
    ax.grid(False)
    ax.set_xticks([])
    ax.set_yticks([])
    for spine in ax.spines.values():
        spine.set_visible(False)


def panel(fig: Figure, rect: tuple[float, float, float, float], title: str, accent: str) -> Axes:
    ax = fig.add_axes(rect)
    style(ax)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.text(0.03, 1.045, title, transform=ax.transAxes, color=TEXT, fontsize=10, weight="bold")
    ax.axvline(0, color=accent, linewidth=5)
    return ax


def kpi_strip(fig: Figure, entries: Sequence[tuple[str, str, str]], accent: str) -> None:
    """One banded row of ``(value, label, colour)`` triples."""
    ax = fig.add_axes((0.04, 0.875, 0.92, 0.05))
    style(ax)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axvline(0, color=accent, linewidth=5)
    width = 1 / max(1, len(entries))
    for i, (value, label, color) in enumerate(entries):
        x = width * i + 0.022
        ax.text(x, 0.5, value, va="center", color=color, fontsize=15, weight="bold")
        ax.text(
            x + 0.022 + 0.011 * len(value),
            0.46,
            label,
            va="center",
            color=MUTED,
            fontsize=8,
            weight="bold",
        )


def empty_note(ax: Axes, text: str) -> None:
    ax.text(0.04, 0.5, text, va="center", color=MUTED, fontsize=9, style="italic")


def draw_names(
    ax: Axes,
    x: float,
    y: float,
    parts: Sequence[tuple[str, str]],
    *,
    fontsize: float = 10,
    weight: str = "normal",
    sep: str = " + ",
) -> None:
    """``parts`` are ``(name, colour)``; each name is drawn in its own colour."""
    renderer = ax.figure.canvas.get_renderer()
    ax_width = ax.get_window_extent(renderer).width
    pieces = []
    for i, (name, color) in enumerate(parts):
        if i:
            pieces.append((sep, MUTED))
        pieces.append((name, color))
    for text, color in pieces:
        t = ax.text(x, y, text, va="center", color=color, fontsize=fontsize, weight=weight)
        x += t.get_window_extent(renderer).width / ax_width


# -- rating graph --------------------------------------------------------------


BAND_COLORS = (
    "#CCCCCC",
    "#77FF77",
    "#77DDBB",
    "#AAAAFF",
    "#FF88FF",
    "#FFCC88",
    "#FFBB55",
    "#FF7777",
    "#FF3333",
    "#AA0000",
)
"""tle-gf's ``color_graph`` per rank, in :data:`RANKS` order."""


def rating_chart(
    name: str, entries: Sequence[RatingEntry], calendar: PuzzleCalendar, *, performances: bool
) -> bytes | None:
    """tle-gf's Akari rating / performance graph (``_plot_akari_multi``) for one diver.

    Default 7x3.5 in figure, rank bands under the line, legend ``name (rating)``
    above the axes. ``None`` when ``performances`` is asked for but every rated
    day was solo.
    """
    if performances:
        points = [
            (calendar.date_for(e.puzzle_number), e.performance)
            for e in entries
            if e.performance is not None
        ]
    else:
        points = [(calendar.date_for(e.puzzle_number), e.rating_after) for e in entries]
    if not points:
        return None
    days = [d for d, _ in points]
    values = [v for _, v in points]
    fig = Figure(figsize=(7.0, 3.5), dpi=DPI)
    FigureCanvasAgg(fig)
    ax = fig.add_subplot()
    ax.plot(
        days,
        values,
        color=LINE_COLORS[0],
        linestyle="-",
        marker="o",
        markersize=3,
        markerfacecolor="white",
        markeredgewidth=0.5,
    )
    ax.set_ylim(min(min(values) - 50, 1100), max(max(values) + 50, 1500))
    ymin, ymax = ax.get_ylim()
    bgcolor = ax.get_facecolor()
    for rank, color in zip(RANKS, BAND_COLORS, strict=True):
        ax.axhspan(
            rank.low, rank.high, facecolor=color, alpha=0.8, edgecolor=bgcolor, linewidth=0.5
        )
    for loc in ax.get_xticks():
        ax.axvline(loc, color=bgcolor, linewidth=0.5)
    ax.set_ylim(ymin, ymax)
    fig.autofmt_xdate()
    ax.legend(
        [f"{safe_name(name)} ({round(entries[-1].rating_after)})"],
        bbox_to_anchor=(0, 1, 1, 0),
        loc="lower left",
        mode="expand",
        ncol=1,
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=bgcolor, bbox_inches="tight", pad_inches=0.25)
    return buf.getvalue()
