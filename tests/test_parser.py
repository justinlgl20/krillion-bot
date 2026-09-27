import pytest

from krillion_bot.parser import parse_result

SHARE = "Krillion #58 🦐\n340\n\n🦑🦑🦑🦑🦑🐟🫧"


def test_parses_share_text():
    r = parse_result(SHARE)
    assert r is not None
    assert r.puzzle_number == 58
    assert r.score == 340
    assert r.tiers == "🦑🦑🦑🦑🦑🐟🫧"


def test_parses_with_share_link_and_surrounding_chatter():
    text = "gg everyone\n\n" + SHARE + "\nkrillion.io\n\nthat last one was brutal"
    r = parse_result(text)
    assert r is not None
    assert (r.puzzle_number, r.score) == (58, 340)


def test_parses_windows_line_endings_and_markdown():
    text = "**Krillion #7** 🦐\r\n85\r\n\r\n🫧🫧🐟🫧🫧🤡⬛"
    r = parse_result(text)
    assert r is not None
    assert (r.puzzle_number, r.score, r.tiers) == (7, 85, "🫧🫧🐟🫧🫧🤡⬛")


def test_rejects_without_emoji_row():
    r = parse_result("Krillion #12\n0")
    assert r is None


def test_parses_zero_with_blank_tiers():
    r = parse_result("Krillion #12\n0\n\n⬛⬛⬛⬛⬛⬛⬛")
    assert r is not None
    assert (r.puzzle_number, r.score, r.tiers) == (12, 0, "⬛⬛⬛⬛⬛⬛⬛")


def test_parses_max_score():
    r = parse_result("Krillion #100 🦐\n700\n\n🌟🌟🌟🌟🌟🌟🌟")
    assert r is not None
    assert r.score == 700


@pytest.mark.parametrize(
    "text",
    [
        "",
        "I love Krillion",
        "Krillion #58 was hard",  # no score line
        "Krillion #58\n\n🦑🦑🦑🦑🦑🐟🫧",  # emoji row where the score should be
        "Krillion #58\n9999",  # above the maximum possible score
        "Krillion #58\n350\n\n🦑🦑🦑🦑🦑🐟🫧",  # tier total does not match
        "Krillion #58\n340\n\n🦑🦑🦑🦑🦑🐟",  # too few tiers
        "Krillion #58\n340\n\n🦑🦑🦑🦑🦑🐟🫧⬛",  # too many tiers
        "Krillion #58\n700\n\n🏮🏮🏮🏮🏮🏮🏮",  # score/tier mismatch
        "Wordle 1,234 4/6\n\n⬛🟩⬛⬛⬛",
    ],
)
def test_rejects_non_results(text):
    assert parse_result(text) is None
