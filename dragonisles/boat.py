"""Parsing and comparing answers to the boat question."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class BoatAnswer:
    raw: str
    tier: int  # 3 dated, 1 never, 0 unreadable
    date: date | None


_MONTHS = {
    name.casefold(): number
    for number, names in enumerate(
        (
            ("january", "jan"),
            ("february", "feb"),
            ("march", "mar"),
            ("april", "apr"),
            ("may",),
            ("june", "jun"),
            ("july", "jul"),
            ("august", "aug"),
            ("september", "sep", "sept"),
            ("october", "oct"),
            ("november", "nov"),
            ("december", "dec"),
        ),
        1,
    )
    for name in names
}
_WEEKDAYS = {
    name.casefold(): number
    for number, name in enumerate(
        (
            "monday",
            "tuesday",
            "wednesday",
            "thursday",
            "friday",
            "saturday",
            "sunday",
        )
    )
}
_NUMBER_WORDS = {
    word: number
    for number, word in enumerate(
        (
            "zero",
            "one",
            "two",
            "three",
            "four",
            "five",
            "six",
            "seven",
            "eight",
            "nine",
            "ten",
            "eleven",
            "twelve",
        )
    )
}
_NUMBER_WORDS.update({"a": 1, "an": 1})


def _clean(text: str) -> str:
    text = " ".join(text.strip().split())
    return "".join(character for character in text if character.isprintable())


def _clamp(value: date, today: date) -> date:
    return min(value, today)


def _make_date(year: int, month: int, day: int, today: date) -> date | None:
    try:
        return _clamp(date(year, month, day), today)
    except ValueError:
        return None


def _month_date(month: int, day: int, year: int | None, today: date) -> date | None:
    if year is not None:
        return _make_date(year, month, day, today)
    for candidate_year in (today.year, today.year - 1):
        try:
            candidate = date(candidate_year, month, day)
        except ValueError:
            continue
        if candidate <= today:
            return candidate
    return None


def _parse_month_date(text: str, today: date) -> date | None:
    match = re.fullmatch(r"(\d{1,2}) ([A-Za-z]+)(?: (\d{4}))?", text)
    if match is not None:
        day, month_name, year = match.groups()
        month = _MONTHS.get(month_name.casefold())
        if month is not None:
            return _month_date(month, int(day), int(year) if year else None, today)
    match = re.fullmatch(r"([A-Za-z]+) (\d{1,2})(?:,? (\d{4}))?", text)
    if match is not None:
        month_name, day, year = match.groups()
        month = _MONTHS.get(month_name.casefold())
        if month is not None:
            return _month_date(month, int(day), int(year) if year else None, today)
    return None


def _parse_ago(text: str, today: date) -> date | None:
    match = re.fullmatch(
        r"(\d+|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|a|an) "
        r"(day|days|week|weeks|month|months|year|years) ago",
        text,
    )
    if match is None:
        return None
    amount, unit = match.groups()
    count = int(amount) if amount.isdigit() else _NUMBER_WORDS[amount]
    unit_days = {
        "day": 1,
        "days": 1,
        "week": 7,
        "weeks": 7,
        "month": 30,
        "months": 30,
        "year": 365,
        "years": 365,
    }[unit]
    try:
        return today - timedelta(days=count * unit_days)
    except OverflowError:
        return date.min


def _parse_weekday(text: str, today: date) -> date | None:
    match = re.fullmatch(r"(?:(?:last|on) )?([A-Za-z]+)", text)
    if match is None:
        return None
    weekday = _WEEKDAYS.get(match.group(1).casefold())
    if weekday is None:
        return None
    days_ago = (today.weekday() - weekday) % 7 or 7
    return today - timedelta(days=days_ago)


def parse_boat_answer(text: str, today: date) -> BoatAnswer:
    raw = _clean(text)
    if not raw:
        return BoatAnswer(raw, 0, None)
    normalized = raw.casefold()

    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw):
        year, month, day = (int(part) for part in raw.split("-"))
        parsed = _make_date(year, month, day, today)
        if parsed is not None:
            return BoatAnswer(raw, 3, parsed)
        return BoatAnswer(raw, 0, None)

    parsed = _parse_month_date(raw, today)
    if parsed is not None:
        return BoatAnswer(raw, 3, parsed)

    relative_days = {
        "today": 0,
        "this morning": 0,
        "this week": 0,
        "yesterday": 1,
        "last night": 1,
        "last week": 7,
        "last month": 30,
        "last year": 365,
    }
    if normalized in relative_days:
        return BoatAnswer(raw, 3, today - timedelta(days=relative_days[normalized]))

    parsed = _parse_ago(normalized, today)
    if parsed is not None:
        return BoatAnswer(raw, 3, parsed)

    literal_distances = {
        "years ago": 730,
        "years back": 730,
        "a few years ago": 730,
        "some years ago": 730,
        "ages": 3650,
        "ages ago": 3650,
        "long ago": 3650,
        "long time ago": 3650,
        "forever ago": 3650,
    }
    for phrase, days in literal_distances.items():
        if phrase in normalized:
            return BoatAnswer(raw, 3, today - timedelta(days=days))

    parsed = _parse_weekday(normalized, today)
    if parsed is not None:
        return BoatAnswer(raw, 3, parsed)

    year_match = re.search(r"(?<!\d)(\d{4})(?!\d)", raw)
    if year_match is not None:
        year = int(year_match.group(1))
        if 1900 <= year <= today.year:
            parsed = _make_date(year, 12, 31, today)
            if parsed is not None:
                return BoatAnswer(raw, 3, parsed)

    if normalized in {
        "never",
        "never have",
        "i have never",
        "i've never",
        "not ever",
        "no",
        "nope",
        "n/a",
    }:
        return BoatAnswer(raw, 1, None)

    return BoatAnswer(raw, 0, None)


def resolve_first_seat(
    answers: dict[int, BoatAnswer],
    rng: random.Random,
    names: dict[int, str],
) -> tuple[int, str]:
    first = answers[0]
    second = answers[1]
    if first.tier == 0 or second.tier == 0:
        raise ValueError("boat answers must be readable")
    first_display = f'{names[0]}: "{first.raw}"'
    second_display = f'{names[1]}: "{second.raw}"'
    explanation = f"{first_display} · {second_display} — "
    if first.tier > second.tier:
        return (
            0,
            explanation
            + f"{names[0]} has travelled by boat and {names[1]} never has, "
            f"so {names[0]} goes first.",
        )
    if second.tier > first.tier:
        return (
            1,
            explanation
            + f"{names[1]} has travelled by boat and {names[0]} never has, "
            f"so {names[1]} goes first.",
        )
    if first.tier == 3 and first.date != second.date:
        winner = 0 if first.date > second.date else 1
        return (
            winner,
            explanation
            + f"{names[winner]} travelled by boat most recently and goes first.",
        )
    winner = rng.randrange(2)
    return (
        winner,
        explanation + "neither answer was more recent, so the first turn was drawn at random.",
    )
