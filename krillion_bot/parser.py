"""Parse the share text Krillion.io puts on the clipboard.

Example::

    Krillion #58 🦐
    340

    🦑🦑🦑🦑🦑🐟🫧
"""

from __future__ import annotations

import re
from dataclasses import dataclass

ROUNDS_PER_DAY = 7
MAX_DAY_SCORE = 700

TIER_SCORES = {"🌟": 100, "🏮": 85, "🦑": 60, "🐟": 30, "🤡": 15, "🫧": 10, "⬛": 0}
TIER_EMOJI = frozenset(TIER_SCORES)

_HEADER_RE = re.compile(r"krillion\s*#\s*(\d{1,5})\b", re.IGNORECASE)
_SCORE_RE = re.compile(r"(?<![\d#])(\d{1,4})(?!\d)")


@dataclass(frozen=True)
class ParsedResult:
    puzzle_number: int
    score: int
    tiers: str  # the emoji row, "" if absent


def _strip_markdown(line: str) -> str:
    return line.replace("*", "").replace("_", "").replace("`", "").replace(">", "").strip()


def _emoji_row(line: str) -> str:
    chars = [c for c in line if c in TIER_EMOJI]
    return "".join(chars) if chars else ""


def parse_result(text: str) -> ParsedResult | None:
    """Return the parsed result or ``None`` if ``text`` is not a Krillion share."""
    lines = [_strip_markdown(line) for line in text.splitlines()]
    for idx, line in enumerate(lines):
        m = _HEADER_RE.search(line)
        if not m:
            continue
        puzzle_number = int(m.group(1))
        score: int | None = None
        tiers = ""
        for follow in lines[idx + 1 : idx + 6]:
            if not follow:
                continue
            if score is None:
                sm = _SCORE_RE.search(follow)
                if sm:
                    score = int(sm.group(1))
                    continue
                return None
            row = _emoji_row(follow)
            if row:
                tiers = row
                break
        if (
            score is None
            or score < 0
            or score > MAX_DAY_SCORE
            or len(tiers) != ROUNDS_PER_DAY
            or sum(TIER_SCORES[c] for c in tiers) != score
        ):
            return None
        return ParsedResult(puzzle_number=puzzle_number, score=score, tiers=tiers)
    return None
