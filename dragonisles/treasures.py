"""Treasure definitions and the reconstructed treasure supply."""

from dataclasses import dataclass
from typing import Literal


GreenEffect = Literal[
    "roll_ones",
    "roll_ones_reroll_extra",
    "roll_ones_draw",
    "roll_ones_coin",
    "three_color_draw",
    "three_color_coin",
    "low_hand_draw",
    "low_hand_coin",
    "sneak_draw",
    "steal_draw",
    "strike_draw",
    "steal_coin",
    "strike_coin",
    "three_color_success",
    "low_hand_success",
]

GREEN_TREASURE_DEFINITIONS: dict[str, tuple[str, str]] = {
    "roll_ones": ("roll_ones", "reroll_draw"),
    "roll_ones_reroll_extra": ("roll_ones", "reroll_extra"),
    "roll_ones_draw": ("roll_ones", "draw"),
    "roll_ones_coin": ("roll_ones", "coin"),
    "three_color_draw": ("three_color_success", "draw"),
    "three_color_coin": ("three_color_success", "coin"),
    "low_hand_draw": ("low_hand_success", "draw"),
    "low_hand_coin": ("low_hand_success", "coin"),
    "sneak_draw": ("sneak_success", "draw"),
    "steal_coin": ("steal_success", "coin"),
    "strike_coin": ("strike_success", "coin"),
    "steal_draw": ("steal_success", "draw"),
    "strike_draw": ("strike_success", "draw"),
    "three_color_success": ("three_color_success", "coin"),
    "low_hand_success": ("low_hand_success", "potion"),
}

GREEN_TREASURE_NAMES = {
    "roll_ones_reroll_extra": "Lucky Mallet",
    "roll_ones_draw": "Daruma",
    "roll_ones_coin": "Omamori",
    "low_hand_coin": "Dotakubell",
    "steal_draw": "Jewel",
    "strike_draw": "Katana",
    "sneak_draw": "Mirror",
    "low_hand_draw": "Magatama Bead",
    "three_color_coin": "Biwa",
    "three_color_draw": "Inuharaku",
}

GREEN_TREASURE_DESCRIPTIONS = {
    "roll_ones_reroll_extra": (
        "Once per Challenge, when you roll a 1, reroll all 1s and roll 1 additional die."
    ),
    "roll_ones_draw": (
        "Once per Challenge, when you roll a 1, reroll all 1s and draw 1 Adventure Card."
    ),
    "roll_ones_coin": (
        "Once per Challenge, when you roll a 1, reroll all 1s and earn 1 Coin Token."
    ),
    "low_hand_coin": (
        "When you have fewer than 3 Adventure Cards in hand after successfully "
        "Challenging an Encounter, earn 1 Coin Token."
    ),
    "low_hand_draw": (
        "When you have fewer than 3 Adventure Cards in hand after successfully "
        "Challenging an Encounter, draw 1 Adventure Card."
    ),
    "steal_draw": "When you successfully Challenge by Stealing, draw 1 Adventure Card.",
    "strike_draw": "When you successfully Challenge by Striking, draw 1 Adventure Card.",
    "sneak_draw": "When you successfully Challenge by Sneaking, draw 1 Adventure Card.",
    "three_color_coin": (
        "When you successfully complete a Challenge with at least 3 different colors, "
        "earn 1 Coin Token."
    ),
    "three_color_draw": (
        "When you successfully complete a Challenge with at least 3 different colors, "
        "draw 1 Adventure Card."
    ),
}

GREEN_EFFECT_NAMES = {
    "roll_ones": "reroll 1s and draw a card",
    "roll_ones_reroll_extra": "reroll all 1s and add one die",
    "roll_ones_draw": "draw 1 card after rolling a 1",
    "roll_ones_coin": "get 1 coin after rolling a 1",
    "three_color_draw": "draw 1 card after a 3-color success",
    "three_color_coin": "get 1 coin after a 3-color success",
    "low_hand_draw": "draw 1 card with fewer than 3 cards",
    "low_hand_coin": "get 1 coin with fewer than 3 cards",
    "sneak_draw": "draw 1 card after Sneaking",
    "steal_coin": "get 1 coin after Stealing",
    "strike_coin": "get 1 coin after Striking",
    "steal_draw": "draw 1 card after Stealing",
    "strike_draw": "draw 1 card after Striking",
    "three_color_success": "coin on 3-color success",
    "low_hand_success": "potion below 3 cards",
}


@dataclass(frozen=True, slots=True)
class Treasure:
    color: str
    victory_points: int = 0
    encounter_type: str | None = None
    passive_effect: GreenEffect | None = None

    @property
    def is_orange(self) -> bool:
        return self.color.lower() == "orange"

    @property
    def is_green(self) -> bool:
        return self.color.lower() == "green"

    @property
    def display_name(self) -> str:
        if self.is_orange:
            return f"orange {self.encounter_type} treasure"
        if self.passive_effect in GREEN_TREASURE_NAMES:
            return GREEN_TREASURE_NAMES[self.passive_effect]
        return f"green ({GREEN_EFFECT_NAMES[self.passive_effect]})"

    @property
    def description(self) -> str:
        if self.is_orange:
            return "Worth 1 VP."
        if self.passive_effect in GREEN_TREASURE_DESCRIPTIONS:
            return GREEN_TREASURE_DESCRIPTIONS[self.passive_effect]
        return GREEN_EFFECT_NAMES[self.passive_effect]


def default_treasure_supply() -> list[Treasure]:
    """Return the reconstructed supply before it is shuffled by the game."""
    oranges = [
        Treasure("orange", victory_points=1, encounter_type=encounter_type)
        for encounter_type in ("dragon", "oni", "bakemono", "tsukumogami", "location")
        for _ in range(3)
    ]
    greens = [
        Treasure("green", passive_effect=effect)
        for effect in (
            "roll_ones_reroll_extra",
            "roll_ones_draw",
            "roll_ones_coin",
            "low_hand_coin",
            "steal_draw",
            "strike_draw",
            "sneak_draw",
            "low_hand_draw",
            "three_color_coin",
            "three_color_draw",
        )
        for _ in range(3)
    ]
    return oranges + greens


def green_trigger(effect: str | None) -> str | None:
    if effect is None:
        return None
    definition = GREEN_TREASURE_DEFINITIONS.get(effect)
    return definition[0] if definition else None


def green_outcome(effect: str | None) -> str | None:
    if effect is None:
        return None
    definition = GREEN_TREASURE_DEFINITIONS.get(effect)
    return definition[1] if definition else None


def expected_treasure_value() -> float:
    """Return the bot's reconstructed expected value of an unknown treasure."""
    supply = default_treasure_supply()
    values = {
        "roll_ones_reroll_extra": 1.5,
        "roll_ones_draw": 1.0,
        "roll_ones_coin": 1.0,
        "three_color_draw": 1.0,
        "three_color_coin": 1.0,
        "low_hand_draw": 1.0,
        "low_hand_coin": 1.0,
        "sneak_draw": 1.0,
        "steal_coin": 1.0,
        "strike_coin": 1.0,
        "steal_draw": 1.0,
        "strike_draw": 1.0,
        "roll_ones": 1.25,
        "three_color_success": 1.0,
        "low_hand_success": 1.0,
    }
    return sum(
        (
            treasure.victory_points
            if treasure.is_orange
            else values[treasure.passive_effect]
        )
        for treasure in supply
    ) / len(supply)


# TODO(rulebook): replace the reconstructed supply composition and effects.
