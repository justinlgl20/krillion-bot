"""Render a :class:`Table` as a PNG in the Queens-bot style.

Dark Discord-grey frame with a white bold title and header, light alternating
row backgrounds, and per-cell text colours (rank colours for names, ratings and
performances; green/grey for Δ). Needs Pillow plus two fonts: DejaVu Sans (or
Pillow's bundled fallback) and Noto Color Emoji for result rows. Without the
emoji font :func:`render_table` returns ``None`` and callers fall back to text.
"""

from __future__ import annotations

import io
import logging
import re
from functools import cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .formatting import Cell, Table

log = logging.getLogger(__name__)

_FONT_DIR = Path(__file__).resolve().parent.parent / "fonts"
EMOJI_FONT_PATHS = (
    _FONT_DIR / "NotoColorEmoji.ttf",
    Path("/usr/share/fonts/google-noto-emoji/NotoColorEmoji.ttf"),
    Path("/usr/share/fonts/truetype/noto/NotoColorEmoji.ttf"),
)
TEXT_FONT_PATHS = {
    "regular": (
        _FONT_DIR / "DejaVuSans.ttf",
        Path("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ),
    "bold": (
        _FONT_DIR / "DejaVuSans-Bold.ttf",
        Path("/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ),
}
# Noto Color Emoji is a bitmap (CBDT) font shipped at exactly this pixel size.
_EMOJI_NATIVE = 109

FONT = 20
EMOJI = 24
MARGIN = 20
CELL_PAD = 10
GAP = 14
ROW_H = 36
HEADER_H = 45
TITLE_H = 36
MAX_ROWS = 40

FRAME = (54, 62, 63)
ROW_A = (242, 242, 242)
ROW_B = (230, 230, 230)
SMOKE = (250, 250, 250)
NOTE = (200, 205, 210)

_MARKDOWN = re.compile(r"[*_`]")


def _first_existing(paths: tuple[Path, ...]) -> Path | None:
    return next((p for p in paths if p.is_file()), None)


@cache
def _text_font(style: str, size: int) -> ImageFont.FreeTypeFont:
    path = _first_existing(TEXT_FONT_PATHS[style])
    if path is not None:
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default(size)


@cache
def emoji_font() -> ImageFont.FreeTypeFont | None:
    path = _first_existing(EMOJI_FONT_PATHS)
    if path is None:
        log.warning("No Noto Color Emoji font found; leaderboard images disabled")
        return None
    return ImageFont.truetype(str(path), _EMOJI_NATIVE)


def emoji_strip(text: str, font: ImageFont.FreeTypeFont) -> Image.Image:
    """Render ``text`` with the bitmap emoji font, scaled down to ``EMOJI`` px tall."""
    left, top, right, bottom = font.getbbox(text)
    canvas = Image.new("RGBA", (max(right, 1), max(bottom, 1)), (0, 0, 0, 0))
    ImageDraw.Draw(canvas).text((0, 0), text, font=font, embedded_color=True)
    scale = EMOJI / _EMOJI_NATIVE
    size = (max(1, round(right * scale)), max(1, round(bottom * scale)))
    return canvas.resize(size, Image.Resampling.LANCZOS)


def _plain(note: str) -> str:
    return _MARKDOWN.sub("", note)


def render_table(table: Table) -> bytes | None:
    """PNG bytes for ``table``, or ``None`` if the emoji font is unavailable."""
    emoji = emoji_font()
    if emoji is None:
        return None
    regular = _text_font("regular", FONT)
    bold = _text_font("bold", FONT)
    small = _text_font("regular", FONT - 4)

    rows = table.rows[:MAX_ROWS]
    notes = [_plain(n) for n in table.notes if "<t:" not in n]
    if len(table.rows) > len(rows):
        notes.append(f"Showing top {len(rows)} of {len(table.rows)} results")

    def width(font: ImageFont.FreeTypeFont, text: str) -> int:
        return int(font.getlength(text))

    strips: dict[tuple[int, int], Image.Image] = {}
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            if cell.emoji and cell.text:
                strips[(i, j)] = emoji_strip(cell.text, emoji)

    def cell_width(i: int, j: int, cell: Cell) -> int:
        strip = strips.get((i, j))
        return strip.width if strip is not None else width(regular, cell.text)

    columns = [width(bold, h) for h in table.header]
    for i, row in enumerate(rows):
        for j, cell in enumerate(row):
            columns[j] = max(columns[j], cell_width(i, j, cell))
    columns = [c + 2 * CELL_PAD for c in columns]

    table_w = sum(columns) + GAP * (len(columns) - 1)
    img_w = max(table_w, width(bold, table.title), *(width(small, n) for n in notes), 0)
    img_w += 2 * MARGIN
    notes_h = (FONT + 4) * len(notes) + (MARGIN // 2 if notes else 0)
    img_h = MARGIN + TITLE_H + HEADER_H + ROW_H * len(rows) + notes_h + MARGIN

    img = Image.new("RGB", (img_w, img_h), FRAME)
    draw = ImageDraw.Draw(img)

    y = MARGIN
    draw.text((MARGIN, y + (TITLE_H - FONT) // 2 - 2), table.title, font=bold, fill=SMOKE)
    y += TITLE_H

    xs = []
    x = MARGIN
    for c in columns:
        xs.append(x)
        x += c + GAP

    def place(j: int, text_w: int) -> int:
        if j in table.right:
            return xs[j] + columns[j] - CELL_PAD - text_w
        return xs[j] + CELL_PAD

    ty = y + (ROW_H - FONT) // 2 - 2
    for j, h in enumerate(table.header):
        draw.text((place(j, width(bold, h)), ty), h, font=bold, fill=SMOKE)
    y += HEADER_H

    for i, row in enumerate(rows):
        draw.rectangle((0, y, img_w, y + ROW_H), fill=ROW_A if i % 2 == 0 else ROW_B)
        ty = y + (ROW_H - FONT) // 2 - 2
        for j, cell in enumerate(row):
            strip = strips.get((i, j))
            if strip is not None:
                img.paste(strip, (place(j, strip.width), y + (ROW_H - strip.height) // 2), strip)
            elif cell.text:
                draw.text(
                    (place(j, width(regular, cell.text)), ty),
                    cell.text,
                    font=regular,
                    fill=cell.color,
                )
        y += ROW_H

    y += MARGIN // 2
    for note in notes:
        draw.text((MARGIN, y), note, font=small, fill=NOTE)
        y += FONT + 4

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()
