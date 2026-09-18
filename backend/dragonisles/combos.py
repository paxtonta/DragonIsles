"""Enumeration and evaluation of legal encounter combinations."""

from dataclasses import dataclass
from functools import lru_cache
from itertools import combinations
from typing import Iterable

from .cards import Card
from .dice import DIE_FACES, probability_at_least

# Verified from the authoritative tutorial transcript.
METHOD_SHAPES = {"sneak": "run", "steal": "same_number", "strike": "same_suit"}
METHODS = tuple(METHOD_SHAPES)

# Method-specific maximums: Steal is limited by five suits; Sneak and Strike
# are limited to six dice (and therefore six selected cards).
METHOD_MAX_CARDS = {"sneak": 6, "steal": 5, "strike": 6}


@dataclass(frozen=True, slots=True)
class Combo:
    method: str
    cards: tuple[Card, ...]

    @property
    def card_count(self) -> int:
        return len(self.cards)


def _run_legal(cards: tuple[Card, ...]) -> bool:
    fixed_ranks = [card.rank for card in cards if not card.wild]
    if len(fixed_ranks) != len(set(fixed_ranks)):
        return False
    wilds = len(cards) - len(fixed_ranks)
    length = len(cards)
    return any(
        all(start <= rank <= start + length - 1 for rank in fixed_ranks)
        and len(set(range(start, start + length)) - set(fixed_ranks)) <= wilds
        for start in range(1, 14 - length)
    )


def _same_number_legal(cards: tuple[Card, ...]) -> bool:
    fixed = [card for card in cards if not card.wild]
    ranks = {card.rank for card in fixed}
    suits = {card.suit for card in fixed}
    wilds = len(cards) - len(fixed)
    return len(ranks) <= 1 and len(suits) == len(fixed) and len(suits) + wilds <= 5


def _same_suit_legal(cards: tuple[Card, ...]) -> bool:
    suits = {card.suit for card in cards if not card.wild}
    return len(suits) <= 1


def is_legal(cards: Iterable[Card], method: str) -> bool:
    """Return whether cards can be played by the named method."""
    if method not in METHODS:
        raise ValueError(f"unknown method: {method}")
    selected = tuple(cards)
    if not selected:
        return False
    if len(selected) > METHOD_MAX_CARDS[method]:
        return False
    return {
        "sneak": _run_legal,
        "steal": _same_number_legal,
        "strike": _same_suit_legal,
    }[method](selected)


def is_legal_reason(cards: Iterable[Card], method: str) -> str:
    """Return a short reason string for a method being disabled."""
    if method not in METHODS:
        raise ValueError(f"unknown method: {method}")
    selected = tuple(cards)
    if not selected or len(selected) > METHOD_MAX_CARDS[method]:
        return "no legal combination"
    if not {
        "sneak": _run_legal,
        "steal": _same_number_legal,
        "strike": _same_suit_legal,
    }[method](selected):
        return "no legal combination"
    return ""


@lru_cache(maxsize=16384)
def _enumerate_combos_cached(cards: tuple[Card, ...]) -> tuple[Combo, ...]:
    """Enumerate every legal one-or-more-card set in a hand."""
    return tuple(
        Combo(method, selected)
        for count in range(1, len(cards) + 1)
        for selected in combinations(cards, count)
        for method in METHODS
        if is_legal(selected, method)
    )


def enumerate_combos(hand: Iterable[Card]) -> list[Combo]:
    return list(_enumerate_combos_cached(tuple(hand)))


@lru_cache(maxsize=8192)
def _best_combo_cached(
    hand: tuple[Card, ...],
    method: str,
    target: int,
    bonus: int,
    faces: tuple[int, ...],
    rerolls: int,
    reroll_ones: bool,
) -> tuple[Combo, float] | None:
    """Return the highest-probability legal combo and its exact probability."""
    if method not in METHODS:
        raise ValueError(f"unknown method: {method}")
    candidates = [
        (
            combo,
            probability_at_least(
                combo.card_count,
                target,
                bonus,
                faces,
                rerolls=rerolls,
                reroll_ones=reroll_ones,
            ),
        )
        for combo in enumerate_combos(hand)
        if combo.method == method
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda item: (item[1], -item[0].card_count))


def best_combo(
    hand: Iterable[Card],
    *,
    method: str,
    target: int,
    bonus: int = 0,
    faces: tuple[int, ...] = DIE_FACES,
    rerolls: int = 0,
    reroll_ones: bool = False,
) -> tuple[Combo, float] | None:
    """Return the highest-probability legal combo and its exact probability."""
    canonical = tuple(
        sorted(hand, key=lambda card: (card.wild, card.suit or "", card.rank or 0))
    )
    return _best_combo_cached(
        canonical, method, target, bonus, faces, rerolls, reroll_ones
    )
