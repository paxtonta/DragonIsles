"""Parsing and comparing answers to the boat question."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date, timedelta


CHILDHOOD_FOLLOWUP = (
    'Roughly how many years ago was that? Give a number of years, '
    'e.g. "20 years ago".'
)


@dataclass(frozen=True)
class BoatAnswer:
    raw: str
    tier: int  # 3 dated, 1 never, 0 unreadable
    date: date | None
    followup: str | None = None


@dataclass(frozen=True)
class BoatTime:
    raw: str
    start: int
    end: int


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

_TIME_ZONES = {
    "et": 3 * 60,
    "edt": 3 * 60,
    "est": 3 * 60,
    "ct": 2 * 60,
    "cdt": 2 * 60,
    "cst": 2 * 60,
    "mt": 60,
    "mdt": 60,
    "mst": 60,
    "pt": 0,
    "pdt": 0,
    "pst": 0,
    "utc": 8 * 60,
    "gmt": 8 * 60,
}
TIME_FOLLOWUP = (
    'That is not precise enough to settle the tie. Give a clock time, '
    'e.g. "9am".'
)


def _clean(text: str) -> str:
    text = " ".join(text.strip().split())
    return "".join(character for character in text if character.isprintable())


def _time_interval(start: int, end: int, offset: int) -> tuple[int, int]:
    # Time zones use fixed offsets; they are deliberately not DST-exact.
    return (
        min(23 * 60 + 59, max(0, start - offset)),
        min(23 * 60 + 59, max(0, end - offset)),
    )


def parse_boat_time(text: str) -> BoatTime | None:
    raw = _clean(text)
    if not raw:
        return None
    normalized = raw.casefold()
    zone_match = re.search(
        r"(?:\s+)(et|edt|est|ct|cdt|cst|mt|mdt|mst|pt|pdt|pst|utc|gmt)$",
        normalized,
    )
    zone = _TIME_ZONES[zone_match.group(1)] if zone_match else 0
    clock = normalized[: zone_match.start()].rstrip() if zone_match else normalized

    ranges = {
        "morning": (5 * 60, 11 * 60 + 59),
        "afternoon": (12 * 60, 16 * 60 + 59),
        "evening": (17 * 60, 20 * 60 + 59),
        "night": (21 * 60, 23 * 60 + 59),
    }
    if clock in ranges:
        start, end = ranges[clock]
        start, end = _time_interval(start, end, zone)
        return BoatTime(raw, start, end)

    if clock == "noon":
        minutes = 12 * 60
    elif clock == "midnight":
        minutes = 0
    else:
        match = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*([ap])m", clock)
        if match is not None:
            hour, minute, meridiem = match.groups()
            hour = int(hour)
            minute = int(minute or 0)
            if not 1 <= hour <= 12 or minute > 59:
                return None
            if hour == 12:
                hour = 0
            if meridiem == "p":
                hour += 12
            minutes = hour * 60 + minute
        else:
            match = re.fullmatch(r"(\d{1,2}):(\d{2})", clock)
            if match is None:
                return None
            hour, minute = (int(value) for value in match.groups())
            if hour > 23 or minute > 59:
                return None
            minutes = hour * 60 + minute
    start, end = _time_interval(minutes, minutes, zone)
    return BoatTime(raw, start, end)


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
    match = re.fullmatch(
        r"(\d{1,2})(?:st|nd|rd|th)? ([A-Za-z]+)(?: (\d{4}))?",
        text,
        re.IGNORECASE,
    )
    if match is not None:
        day, month_name, year = match.groups()
        month = _MONTHS.get(month_name.casefold())
        if month is not None:
            return _month_date(month, int(day), int(year) if year else None, today)
    match = re.fullmatch(
        r"([A-Za-z]+) (\d{1,2})(?:st|nd|rd|th)?(?:,? (\d{4}))?",
        text,
        re.IGNORECASE,
    )
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

    if any(
        phrase in normalized
        for phrase in (
            "childhood",
            "as a kid",
            "when i was a kid",
            "as a child",
        )
    ):
        return BoatAnswer(raw, 0, None, CHILDHOOD_FOLLOWUP)

    return BoatAnswer(raw, 0, None)


def resolve_first_seat(
    answers: dict[int, BoatAnswer],
    rng: random.Random,
    names: dict[int, str],
    times: dict[int, BoatTime] | None = None,
) -> tuple[int, str] | None:
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
    if times is not None:
        return resolve_boat_times(answers, times, rng, names)
    winner = 0
    return (
        winner,
        explanation + f"neither answer was more recent, so {names[winner]} goes first by seat order.",
    )


def resolve_boat_times(
    answers: dict[int, BoatAnswer],
    times: dict[int, BoatTime],
    rng: random.Random,
    names: dict[int, str],
) -> tuple[int, str] | None:
    first = times[0]
    second = times[1]
    first_display = f'{names[0]}: "{answers[0].raw}" at {first.raw}'
    second_display = f'{names[1]}: "{answers[1].raw}" at {second.raw}'
    explanation = f"{first_display} · {second_display} — "
    if first.start > second.end:
        return 0, explanation + f"{names[0]} travelled later that day and goes first."
    if second.start > first.end:
        return 1, explanation + f"{names[1]} travelled later that day and goes first."
    if first.start != first.end or second.start != second.end:
        return None
    winner = 0
    return (
        winner,
        explanation + f"both at the same time, so {names[winner]} goes first by seat order.",
    )
