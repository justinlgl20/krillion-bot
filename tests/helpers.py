from krillion_bot.parser import TIER_SCORES


def tiers_for(score: int) -> str:
    values = tuple(TIER_SCORES.items())

    def choose(remaining: int, slots: int) -> str | None:
        if slots == 0:
            return "" if remaining == 0 else None
        for emoji, points in values:
            if points > remaining:
                continue
            suffix = choose(remaining - points, slots - 1)
            if suffix is not None:
                return emoji + suffix
        return None

    result = choose(score, 7)
    if result is None:
        raise ValueError(f"{score} cannot be represented by seven Krillion tiers")
    assert len(result) == 7
    assert sum(TIER_SCORES[emoji] for emoji in result) == score
    return result
