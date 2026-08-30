"""Audit strict dominance between encounters of the same type.

Dominance pairs are balance-review warnings, not automatic deck errors:
near-duplicate encounters can be intentional for deck variety.
"""

import math
import random
import sys
from functools import lru_cache
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from dragonisles.cards import AdventurerDeck
from dragonisles.combos import is_legal
from dragonisles.dice import probability_at_least
from dragonisles.encounters import METHODS, Encounter, load_encounters
from dragonisles.treasures import expected_treasure_value

AVAILABILITY_TRIALS = 100_000


def _reward_value(encounter: Encounter, method: str) -> float:
    reward = encounter.rewards.get(method)
    if reward is None:
        return 0.0
    return reward.coins + (expected_treasure_value() if reward.treasure else 0.0)


def _target_card_count(target: int, method: str) -> int:
    count = max(1, math.ceil(target / 2.5))
    if method == "steal":
        return min(count, 5)
    return min(count, 8)


@lru_cache(maxsize=None)
def _method_availability(method: str, card_count: int) -> float:
    if method == "steal" and card_count > 5:
        return 0.0
    seed = sum(ord(char) for char in method) * 101 + card_count
    rng = random.Random(seed)
    deck = AdventurerDeck.standard_cards()
    successes = 0
    for _ in range(AVAILABILITY_TRIALS):
        hand = rng.sample(deck, card_count)
        successes += is_legal(hand, method)
    return successes / AVAILABILITY_TRIALS


def _effective_difficulty(encounter: Encounter, method: str) -> float:
    card_count = _target_card_count(encounter.target_for(method), method)
    availability = max(
        _method_availability(method, card_count), 1 / AVAILABILITY_TRIALS
    )
    roll_success = probability_at_least(card_count, encounter.target_for(method))
    success = max(availability * roll_success, 1 / AVAILABILITY_TRIALS)
    return -math.log(success)


def dominated_cards(encounters: list[Encounter]) -> list[tuple[str, str]]:
    dominated: list[tuple[str, str]] = []
    for candidate in encounters:
        for other in encounters:
            if candidate is other or candidate.encounter_type != other.encounter_type:
                continue
            if other.victory_points < candidate.victory_points:
                continue
            if other.icons < candidate.icons:
                continue
            strict = (
                other.victory_points > candidate.victory_points
                or other.icons > candidate.icons
            )
            valid = True
            for method in METHODS:
                candidate_blocked = candidate.blocked_method == method
                other_blocked = other.blocked_method == method
                if other_blocked and not candidate_blocked:
                    valid = False
                    break
                if candidate_blocked and not other_blocked:
                    strict = True
                    continue
                if candidate_blocked:
                    continue
                if other.target_for(method) > candidate.target_for(
                    method
                ) or _reward_value(other, method) < _reward_value(candidate, method):
                    valid = False
                    break
                strict |= other.target_for(method) < candidate.target_for(
                    method
                ) or _reward_value(other, method) > _reward_value(candidate, method)
            if valid and strict:
                dominated.append((candidate.id, other.id))
    return dominated


def _materially_dominates(candidate: Encounter, other: Encounter) -> bool:
    difficulty_advantage = max(
        _effective_difficulty(candidate, method) - _effective_difficulty(other, method)
        for method in METHODS
        if candidate.blocked_method != method
    )
    reward_advantage = any(
        other.rewards.get(method, None) is not None
        and other.rewards[method].treasure
        and not (
            candidate.rewards.get(method, None) is not None
            and candidate.rewards[method].treasure
        )
        for method in METHODS
    )
    blocked_advantage = (
        candidate.blocked_method is not None and other.blocked_method is None
    )
    return (
        other.victory_points > candidate.victory_points
        or other.icons > candidate.icons
        or difficulty_advantage >= 2
        or reward_advantage
        or blocked_advantage
    )


def materially_dominated_cards(
    encounters: list[Encounter],
) -> list[tuple[str, str]]:
    by_id = {encounter.id: encounter for encounter in encounters}
    return [
        (candidate_id, other_id)
        for candidate_id, other_id in dominated_cards(encounters)
        if _materially_dominates(by_id[candidate_id], by_id[other_id])
    ]


def material_shape_warnings(encounters: list[Encounter]) -> list[str]:
    """Find extreme no-reward method profiles that are not Pareto pairs."""
    warnings = []
    for encounter in encounters:
        legal_methods = [
            method for method in METHODS if encounter.blocked_method != method
        ]
        targets = [encounter.target_for(method) for method in legal_methods]
        steal_is_hardest = (
            "steal" in legal_methods
            and all(
                encounter.steal_target > encounter.target_for(method)
                for method in legal_methods
                if method != "steal"
            )
            and "steal" not in encounter.rewards
        )
        if steal_is_hardest or (
            not encounter.rewards
            and min(targets) <= 6
            and max(targets) >= 10
            and max(targets) - min(targets) >= 6
        ):
            warnings.append(encounter.id)
    return warnings


def value_per_average_dice(encounter: Encounter) -> float:
    average_dice = (
        sum(encounter.target_for(method) for method in METHODS) / len(METHODS) / 2.5
    )
    return encounter.victory_points / average_dice


def value_warnings(encounters: list[Encounter]) -> list[tuple[str, float]]:
    """Flag unusually high or low VP per average die for tsukumogami."""
    warnings: list[tuple[str, float]] = []
    for encounter in encounters:
        if encounter.encounter_type != "tsukumogami":
            continue
        ratio = value_per_average_dice(encounter)
        if ratio < 0.4 or ratio > 1.5:
            warnings.append((encounter.id, ratio))
    return warnings


if __name__ == "__main__":
    encounters = load_encounters(Path("data/encounters.json"))
    print(dominated_cards(encounters))
    print(f"material dominance warnings: {materially_dominated_cards(encounters)}")
    print(f"material shape warnings: {material_shape_warnings(encounters)}")
    for encounter in encounters:
        if encounter.encounter_type == "tsukumogami":
            print(
                f"{encounter.id} ({encounter.name}): "
                f"{value_per_average_dice(encounter):.2f} VP/average-die"
            )
    print(f"warnings: {value_warnings(encounters)}")
