"""Character data and extensibility hooks."""

from dataclasses import dataclass
from typing import Any, Callable


AbilityHook = Callable[[Any], None]
WARRIOR_DRAW_TRIGGER = "on_completing_encounter"
STARTING_HAND_SIZE = 5
DEFAULT_PREPARE_DRAW_COUNT = 2


@dataclass(frozen=True, slots=True)
class TrackStep:
    value: int
    reward: str | None = None


SKILL_TRACKS: dict[str, dict[str, tuple[int | TrackStep, ...]]] = {
    "Monk": {
        "sneak": (
            TrackStep(1, "potion"),
            1,
            TrackStep(1, "treasure"),
            TrackStep(1, "potion"),
        ),
        "steal": (1, TrackStep(1, "treasure"), TrackStep(1, "potion")),
        "trophy": (
            TrackStep(1, "treasure"),
            TrackStep(1, "potion"),
            TrackStep(1, "treasure"),
        ),
        "hand_limit": (TrackStep(1, "potion"), TrackStep(1, "treasure")),
    },
    "Sorcerer": {
        "sneak": (
            TrackStep(1, "treasure"),
            TrackStep(1, "coin"),
            1,
            TrackStep(1, "treasure"),
        ),
        "strike": (1, TrackStep(1, "treasure"), TrackStep(1, "coin")),
        "reroll": (
            TrackStep(1, "treasure"),
            1,
            TrackStep(1, "treasure"),
        ),
        "hand_limit": (TrackStep(1, "coin"), TrackStep(1, "treasure")),
    },
    "Trader": {
        "sneak": (
            TrackStep(1, "treasure"),
            TrackStep(1, "coin"),
            TrackStep(2, "treasure"),
        ),
        "steal": (
            TrackStep(1, "treasure"),
            TrackStep(1, "coin"),
            TrackStep(1, "treasure"),
        ),
        "strike": (
            TrackStep(1, "treasure"),
            TrackStep(1, "coin"),
            TrackStep(1, "treasure"),
        ),
        "hand_limit": (
            TrackStep(1, "treasure"),
            TrackStep(2, "coin"),
            TrackStep(1, "treasure"),
        ),
    },
    "Warrior": {
        "strike": (1, TrackStep(1, "treasure"), 2, TrackStep(1, "coin")),
        "sneak": (
            TrackStep(1, "potion"),
            TrackStep(1, "treasure"),
            TrackStep(1, "coin"),
        ),
        "trophy": (
            TrackStep(1, "treasure"),
            TrackStep(1, "coin"),
            TrackStep(1, "treasure"),
        ),
        "hand_limit": (TrackStep(1, "potion"), TrackStep(2, "treasure")),
    },
    "Pirate": {
        "sea": (1, TrackStep(1, "treasure"), TrackStep(1, "coin")),
        "reroll": (
            1,
            TrackStep(1, "coin"),
            TrackStep(1, "treasure"),
            TrackStep(1, "coin"),
        ),
        "trophy": (
            TrackStep(1, "treasure"),
            1,
            TrackStep(1, "treasure"),
        ),
        "hand_limit": (TrackStep(1, "coin"), TrackStep(2, "treasure")),
    },
}


@dataclass(frozen=True, slots=True)
class Character:
    name: str
    starting_hand_limit: int
    skill_tracks: tuple[str, ...] = ()
    ability_hook: AbilityHook | None = None
    coin_multiplier: int = 1
    prepare_draw_count: int = DEFAULT_PREPARE_DRAW_COUNT
    potion_draw_count: int = 0
    warrior_draw_trigger: str | None = None
    trader_draw_count: int = 0


def track_value(character: Character, levels: dict[str, int], track: str) -> int:
    steps = SKILL_TRACKS.get(character.name, {}).get(track, ())
    level = levels.get(track, 0)
    return sum(
        step.value if isinstance(step, TrackStep) else step for step in steps[:level]
    )


def track_reward(character: Character, track: str, level: int) -> str | None:
    step = SKILL_TRACKS.get(character.name, {}).get(track, ())[level - 1]
    return step.reward if isinstance(step, TrackStep) else None


def hand_limit_bonus(character: Character, levels: dict[str, int]) -> int:
    return track_value(character, levels, "hand_limit")


def roll_bonus(
    character: Character,
    levels: dict[str, int],
    *,
    method: str,
    is_sea: bool = False,
) -> int:
    bonus = track_value(character, levels, method)
    if character.name == "Pirate" and is_sea:
        bonus += track_value(character, levels, "sea")
    return bonus


def trophy_bonus(character: Character, levels: dict[str, int]) -> int:
    return track_value(character, levels, "trophy")


def reroll_count(character: Character, levels: dict[str, int]) -> int:
    return track_value(character, levels, "reroll")


def available_tracks(
    character: Character, levels: dict[str, int] | None = None
) -> tuple[str, ...]:
    levels = levels or {}
    return tuple(
        track
        for track, steps in SKILL_TRACKS.get(character.name, {}).items()
        if steps and levels.get(track, 0) < len(steps)
    )


CHARACTERS = {
    "Monk": Character("Monk", 8, potion_draw_count=1),
    "Pirate": Character("Pirate", 7, coin_multiplier=2),
    "Warrior": Character("Warrior", 7, warrior_draw_trigger=WARRIOR_DRAW_TRIGGER),
    "Sorcerer": Character("Sorcerer", 8, prepare_draw_count=3),
    "Trader": Character("Trader", 7, trader_draw_count=3),
}

# TODO(user): confirm whether the Warrior draw trigger is encounter completion.
