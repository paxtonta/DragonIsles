"""Confirmed potion token types and effect constants."""

from dataclasses import dataclass
import random
from typing import Callable

PLUS_TWO = "+2"
DRAW_TWO = "Draw 2"
PURGE = "Purge"
POTION_TYPES = (PLUS_TWO, DRAW_TWO, PURGE)


@dataclass(frozen=True, slots=True)
class PotionToken:
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in POTION_TYPES:
            raise ValueError(f"unknown potion type: {self.kind}")

    def __str__(self) -> str:
        return self.kind


PotionFactory = Callable[[], PotionToken]


def random_potion() -> PotionToken:
    # TODO(rulebook): confirm that the three potion types are equally likely.
    return PotionToken(random.choice(POTION_TYPES))
