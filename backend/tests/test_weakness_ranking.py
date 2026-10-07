"""Train Your Weakness picks a real weakness, not a category seen once."""

import pytest

from app.progress import Player, weakest_category, weakness_score


def player_with(**rows) -> Player:
    p = Player(id="p_x")
    for category, (encountered, resisted) in rows.items():
        p.radar[category] = [encountered, resisted]
    return p


def test_one_round_is_not_treated_as_perfect_or_hopeless():
    assert weakness_score(1, 1) == pytest.approx(2 / 3)
    assert weakness_score(1, 0) == pytest.approx(1 / 3)
    assert weakness_score(0, 0) == 0.5


def test_lots_of_evidence_of_weakness_wins():
    # 2 of 12 resisted (17%) is clearly weaker than 0 of 1 (0% but one round)
    p = player_with(urgency=(1, 0), financial=(12, 2))
    assert weakest_category(p)["category"] == "financial"


def test_tie_goes_to_the_category_seen_more():
    p = player_with(urgency=(2, 1), emotional=(4, 2))   # same score 0.5
    assert weakest_category(p)["category"] == "emotional"


def test_display_percent_stays_the_real_rate():
    row = weakest_category(player_with(financial=(12, 2)))
    assert row["percent"] == 17


def test_no_data_means_no_pick():
    assert weakest_category(Player(id="p_new")) is None
