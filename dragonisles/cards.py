"""Adventurer cards and deck management."""

from dataclasses import dataclass
import random
from typing import Iterable

SUITS = ("red", "yellow", "green", "blue", "purple")
RANKS = range(1, 13)
WILDS = 4


@dataclass(frozen=True, slots=True)
class Card:
    suit: str | None = None
    rank: int | None = None
    wild: bool = False

    def __post_init__(self) -> None:
        if self.wild:
            if self.suit is not None or self.rank is not None:
                raise ValueError("wild cards cannot have a suit or rank")
        elif self.suit is None or self.rank is None:
            raise ValueError("normal cards require a suit and rank from the deck")

    @classmethod
    def wild_card(cls) -> "Card":
        return cls(wild=True)

    def __str__(self) -> str:
        return "Wild" if self.wild else f"{self.suit} {self.rank}"


class AdventurerDeck:
    """A draw pile and discard pile, reshuffling discards when needed."""

    def __init__(
        self,
        cards: Iterable[Card] | None = None,
        *,
        rng: random.Random | None = None,
    ) -> None:
        self.rng = rng or random.Random()
        self.draw_pile = list(cards) if cards is not None else self.standard_cards()
        self.cards = tuple(self.draw_pile)
        self.discard_pile: list[Card] = []
        self.rng.shuffle(self.draw_pile)

    @staticmethod
    def standard_cards() -> list[Card]:
        return [Card(suit, rank) for suit in SUITS for rank in RANKS] + [
            Card.wild_card() for _ in range(WILDS)
        ]

    def __len__(self) -> int:
        return len(self.draw_pile) + len(self.discard_pile)

    def draw(self) -> Card:
        if not self.draw_pile:
            if not self.discard_pile:
                raise RuntimeError("cannot draw from an empty adventurer deck")
            self.draw_pile = self.discard_pile
            self.discard_pile = []
            self.rng.shuffle(self.draw_pile)
        return self.draw_pile.pop()

    def discard(self, cards: Card | Iterable[Card]) -> None:
        if isinstance(cards, Card):
            self.discard_pile.append(cards)
        else:
            self.discard_pile.extend(cards)
