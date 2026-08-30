from itertools import product

import pytest

from dragonisles.dice import DIE_FACES, probability_at_least, sum_distribution


def test_distribution_matches_brute_force():
    for count in range(7):
        outcomes = [sum(roll) for roll in product(DIE_FACES, repeat=count)]
        expected = {
            total: outcomes.count(total) / len(outcomes) for total in set(outcomes)
        }
        assert sum_distribution(count) == pytest.approx(expected)


def test_bonus_probability():
    assert probability_at_least(1, 5, bonus=1) == pytest.approx(1 / 6)
    assert probability_at_least(1, 4, bonus=1) == pytest.approx(0.5)


def test_distribution_uses_configured_face_count():
    assert sum_distribution(1, (1, 2, 3)) == pytest.approx(
        {1: 1 / 3, 2: 1 / 3, 3: 1 / 3}
    )


def test_confirmed_faces_are_six_sided():
    assert DIE_FACES == (1, 2, 2, 3, 3, 4)
