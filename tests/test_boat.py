import random
from datetime import date, timedelta

import pytest

from dragonisles.boat import (
    CHILDHOOD_FOLLOWUP,
    DATE_FORMAT_FOLLOWUP,
    BoatAnswer,
    BoatTime,
    parse_boat_answer,
    parse_boat_time,
    resolve_first_seat,
)


TODAY = date(2026, 8, 10)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("", (0, None)),
        (" \t ", (0, None)),
        ("2026-08-06", (3, date(2026, 8, 6))),
        ("13-08-2021", (3, date(2021, 8, 13))),
        ("13.08.2021", (3, date(2021, 8, 13))),
        ("13/08/2021", (3, date(2021, 8, 13))),
        ("08-13-2021", (3, date(2021, 8, 13))),
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


@pytest.mark.parametrize("text", ("06-07-2026", "07.06.2026", "06/07/2026"))
def test_ambiguous_numeric_dates_request_clarification(text):
    answer = parse_boat_answer(text, TODAY)
    assert answer.tier == 0
    assert answer.date is None
    assert answer.followup.startswith(DATE_FORMAT_FOLLOWUP)
    assert {choice for choice, _ in answer.clarifications} == {
        "June 7, 2026",
        "July 6, 2026",
    }


def test_ambiguous_numeric_dates_offer_ordered_interpretations():
    answer = parse_boat_answer("07-06-2026", TODAY)
    assert answer.followup == (
        'Please clarify that numeric date. Did you mean '
        '"July 6, 2026" or "June 7, 2026"?'
    )


def test_relative_date_answers_use_the_other_player_as_reference():
    reference = parse_boat_answer("June 7, 2026", TODAY)
    assert parse_boat_answer("Later than that", TODAY, reference).date == date(
        2026, 6, 8
    )
    assert parse_boat_answer("Earlier than that", TODAY, reference).date == date(
        2026, 6, 6
    )


def test_relative_date_answers_require_a_reference():
    answer = parse_boat_answer("Later than that", TODAY)
    assert answer.tier == 0
    assert answer.followup


def test_childhood_answers_request_a_years_followup():
    for text in ("childhood", "as a kid", "when i was a kid", "as a child"):
        answer = parse_boat_answer(text, TODAY)
        assert answer.tier == 0
        assert answer.date is None
        assert answer.followup == CHILDHOOD_FOLLOWUP


def test_other_unreadable_answers_have_no_followup():
    answer = parse_boat_answer("gibberish", TODAY)
    assert answer.tier == 0
    assert answer.followup is None


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        ("9am", (540, 540)),
        ("9 am", (540, 540)),
        ("1PM", (780, 780)),
        ("1 p.m.", (780, 780)),
        ("9:30am", (570, 570)),
        ("9:30 pm", (1290, 1290)),
        ("12am", (0, 0)),
        ("12pm", (720, 720)),
        ("14:00", (840, 840)),
        ("09:30", (570, 570)),
        ("noon", (720, 720)),
        ("midnight", (0, 0)),
        ("17:00 et", (840, 840)),
        ("17:00 ct", (900, 900)),
        ("17:00 mt", (960, 960)),
        ("17:00 pt", (1020, 1020)),
        ("17:00 utc", (540, 540)),
        ("5pm GMT", (540, 540)),
        ("2am et", (0, 0)),
        ("morning", (300, 719)),
        ("afternoon", (720, 1019)),
        ("evening", (1020, 1259)),
        ("night", (1260, 1439)),
        ("5", None),
        ("17", None),
        ("don't know", None),
        ("gibberish", None),
    ),
)
def test_parse_boat_time(text, expected):
    parsed = parse_boat_time(text)
    if expected is None:
        assert parsed is None
    else:
        assert parsed is not None
        assert (parsed.start, parsed.end) == expected
        assert parsed.raw == " ".join(text.strip().split())


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


def test_ordinal_month_dates_parse_as_specific_dates():
    assert parse_boat_answer("July 3rd 2026", TODAY).date == date(2026, 7, 3)
    assert parse_boat_answer("3rd July 2026", TODAY).date == date(2026, 7, 3)


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


def test_resolve_first_seat_orders_ordinal_date_before_later_date():
    answers = {
        0: parse_boat_answer("July 3rd 2026", TODAY),
        1: parse_boat_answer("July 6, 2026", TODAY),
    }
    assert resolve_first_seat(answers, random.Random(1), {0: "Scott", 1: "Paxton"})[0] == 1


def test_resolve_first_seat_uses_seat_order_for_equal_never_answers():
    answers = {
        0: BoatAnswer("never", 1, None),
        1: BoatAnswer("nope", 1, None),
    }
    winner, explanation = resolve_first_seat(
        answers, random.Random(22), {0: "Ari", 1: "Crendia"}
    )
    assert winner == 0
    assert "Ari goes first by seat order." in explanation


def test_resolve_first_seat_uses_later_same_day_time():
    answers = {
        0: BoatAnswer("6 Aug", 3, TODAY),
        1: BoatAnswer("6 Aug", 3, TODAY),
    }
    times = {
        0: BoatTime("2:30pm", 870, 870),
        1: BoatTime("9am", 540, 540),
    }
    winner, explanation = resolve_first_seat(
        answers, random.Random(1), {0: "Crendia", 1: "Ari"}, times=times
    )
    assert winner == 0
    assert explanation == (
        'Crendia: "6 Aug" at 2:30pm · Ari: "6 Aug" at 9am — '
        "Crendia travelled later that day and goes first."
    )


def test_resolve_first_seat_orders_relative_later_answer_first():
    reference = parse_boat_answer("June 7, 2026", TODAY)
    answers = {
        0: reference,
        1: parse_boat_answer("Later than that", TODAY, reference),
    }
    assert resolve_first_seat(
        answers, random.Random(1), {0: "Ari", 1: "Crendia"}
    )[0] == 1


def test_resolve_first_seat_reasks_for_equal_same_day_times():
    answers = {
        0: BoatAnswer("6 Aug", 3, TODAY),
        1: BoatAnswer("6 Aug", 3, TODAY),
    }
    times = {
        0: BoatTime("9am", 540, 540),
        1: BoatTime("9am", 540, 540),
    }
    result = resolve_first_seat(
        answers, random.Random(22), {0: "Crendia", 1: "Ari"}, times=times
    )
    assert result is None
