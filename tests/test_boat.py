import random
from datetime import date, timedelta

import pytest

from dragonisles.boat import BoatAnswer, parse_boat_answer, resolve_first_seat


TODAY = date(2026, 8, 10)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("", (0, None)),
        (" \t ", (0, None)),
        ("2026-08-06", (3, date(2026, 8, 6))),
        ("6 Aug", (3, date(2026, 8, 6))),
        ("August 6, 2026", (3, date(2026, 8, 6))),
        ("aug 6", (3, date(2026, 8, 6))),
        ("August 20", (3, date(2025, 8, 20))),
        ("today", (3, TODAY)),
        ("this morning", (3, TODAY)),
        ("this week", (3, TODAY)),
        ("yesterday", (3, TODAY - timedelta(days=1))),
        ("last night", (3, TODAY - timedelta(days=1))),
        ("2 days ago", (3, TODAY - timedelta(days=2))),
        ("two weeks ago", (3, TODAY - timedelta(days=14))),
        ("a month ago", (3, TODAY - timedelta(days=30))),
        ("three years ago", (3, TODAY - timedelta(days=365 * 3))),
        ("last week", (3, TODAY - timedelta(days=7))),
        ("last month", (3, TODAY - timedelta(days=30))),
        ("last year", (3, TODAY - timedelta(days=365))),
        ("last tuesday", (3, date(2026, 8, 4))),
        ("on friday", (3, date(2026, 8, 7))),
        ("tuesday", (3, date(2026, 8, 4))),
        ("sometime in 2019", (3, date(2019, 12, 31))),
        ("August 20, 2030", (3, TODAY)),
        ("never", (1, None)),
        ("never have", (1, None)),
        ("i have never", (1, None)),
        ("i've never", (1, None)),
        ("not ever", (1, None)),
        ("no", (1, None)),
        ("nope", (1, None)),
        ("n/a", (1, None)),
        ("years ago", (3, TODAY - timedelta(days=730))),
        ("years back", (3, TODAY - timedelta(days=730))),
        ("a few years ago", (3, TODAY - timedelta(days=730))),
        ("some years ago", (3, TODAY - timedelta(days=730))),
        ("ages", (3, TODAY - timedelta(days=3650))),
        ("ages ago", (3, TODAY - timedelta(days=3650))),
        ("long ago", (3, TODAY - timedelta(days=3650))),
        ("long time ago", (3, TODAY - timedelta(days=3650))),
        ("forever ago", (3, TODAY - timedelta(days=3650))),
        ("childhood", (0, None)),
        ("as a kid", (0, None)),
        ("when i was a kid", (0, None)),
        ("as a child", (0, None)),
        ("can't remember", (0, None)),
        ("cant remember when", (0, None)),
        ("cannot remember", (0, None)),
        ("don't remember", (0, None)),
        ("dont remember", (0, None)),
        ("do not remember", (0, None)),
        ("no idea", (0, None)),
        ("forget", (0, None)),
        ("forgotten", (0, None)),
        ("a while ago", (0, None)),
        ("while back", (0, None)),
        ("a while back", (0, None)),
        ("a long time", (0, None)),
        ("gibberish", (0, None)),
    ),
)
def test_parse_boat_answer(text, expected):
    answer = parse_boat_answer(text, TODAY)
    assert (answer.tier, answer.date) == expected
    assert answer.raw == " ".join(text.strip().split())


def test_parse_boat_answer_sanitizes_text():
    answer = parse_boat_answer("  two\tweeks\nago  ", TODAY)
    assert answer.raw == "two weeks ago"
    assert answer.tier == 3


def test_two_years_ago_is_a_numeric_date():
    answer = parse_boat_answer("2 years ago", TODAY)
    assert answer.tier == 3
    assert answer.date == TODAY - timedelta(days=730)


def test_literal_years_back_loses_to_a_more_recent_numeric_date():
    answers = {
        0: parse_boat_answer("years back", TODAY),
        1: parse_boat_answer("51 days ago", TODAY),
    }
    winner, _ = resolve_first_seat(answers, random.Random(1), {0: "Ari", 1: "Crendia"})
    assert winner == 1


def test_future_iso_date_is_clamped_to_today():
    answer = parse_boat_answer("2030-01-01", TODAY)
    assert answer == BoatAnswer("2030-01-01", 3, TODAY)


def test_weekday_never_resolves_to_today():
    today = date(2026, 8, 11)
    answer = parse_boat_answer("tuesday", today)
    assert answer.date == date(2026, 8, 4)


def test_resolve_first_seat_prefers_tier_then_date():
    answers = {
        0: BoatAnswer("never", 1, None),
        1: BoatAnswer("last week", 3, TODAY - timedelta(days=7)),
    }
    winner, explanation = resolve_first_seat(
        answers, random.Random(1), {0: "Ari", 1: "Crendia"}
    )
    assert winner == 1
    assert 'Ari: "never"' in explanation
    assert 'Crendia: "last week"' in explanation
    assert "Crendia has travelled by boat and Ari never has, so Crendia goes first." in explanation


def test_resolve_first_seat_prefers_later_dated_answer():
    answers = {
        0: BoatAnswer("6 Aug", 3, date(2026, 8, 6)),
        1: BoatAnswer("last week", 3, date(2026, 8, 3)),
    }
    assert resolve_first_seat(answers, random.Random(1), {0: "Ari", 1: "Crendia"})[0] == 0


def test_resolve_first_seat_draws_equal_answers_deterministically():
    answers = {
        0: BoatAnswer("never", 1, None),
        1: BoatAnswer("nope", 1, None),
    }
    expected = random.Random(22).randrange(2)
    winner, explanation = resolve_first_seat(
        answers, random.Random(22), {0: "Ari", 1: "Crendia"}
    )
    assert winner == expected
    assert "drawn at random" in explanation
