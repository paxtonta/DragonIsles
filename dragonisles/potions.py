"""Confirmed potion token types and effect constants."""

from dataclasses import dataclass
from typing import Callable

PLUS_TWO = "+2"
DRAW_TWO = "Draw 2"
PURGE = "Purge"
POTION_TYPES = (PLUS_TWO, DRAW_TWO, PURGE)
POTION_SUPPLY_COUNTS = {PLUS_TWO: 10, DRAW_TWO: 7, PURGE: 3}


@dataclass(frozen=True, slots=True)
class PotionToken:
    kind: str

    def __post_init__(self) -> None:
        if self.kind not in POTION_TYPES:
            raise ValueError(f"unknown potion type: {self.kind}")

    def __str__(self) -> str:
        return self.kind


PotionSupplyFactory = Callable[[], list[PotionToken]]


def default_potion_supply() -> list[PotionToken]:
    """Return the fixed potion bag before it is shuffled by the game."""
    return [
        PotionToken(kind)
        for kind, count in POTION_SUPPLY_COUNTS.items()
        for _ in range(count)
    ]
