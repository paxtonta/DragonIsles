"""Exact probability calculations for configurable custom dice."""

from functools import lru_cache
from itertools import combinations, product

# Confirmed DragonIsles die faces.
DIE_FACES = (1, 2, 2, 3, 3, 4)


@lru_cache(maxsize=None)
def sum_distribution(
    num_dice: int, faces: tuple[int, ...] = DIE_FACES, rerolls: int = 0
) -> dict[int, float]:
    """Return the exact probability distribution of the sum of ``num_dice``."""
    if num_dice < 0:
        raise ValueError("num_dice cannot be negative")
    if not faces:
        raise ValueError("faces cannot be empty")
    distribution = {0: 1.0}
    for _ in range(num_dice):
        next_distribution: dict[int, float] = {}
        for current, probability in distribution.items():
            for face in faces:
                next_distribution[current + face] = next_distribution.get(
                    current + face, 0.0
                ) + probability / len(faces)
        distribution = next_distribution
    return distribution


@lru_cache(maxsize=None)
def probability_at_least(
    num_dice: int,
    target: int,
    bonus: int = 0,
    faces: tuple[int, ...] = DIE_FACES,
    rerolls: int = 0,
    reroll_ones: bool = False,
) -> float:
    """Return P(sum of dice plus ``bonus`` is at least ``target``)."""
    if rerolls or reroll_ones:
        total_probability = 0.0
        for initial in product(faces, repeat=num_dice):
            auto_indices = (
                tuple(index for index, value in enumerate(initial) if value == 1)
                if reroll_ones
                else ()
            )
            auto_outcomes = product(faces, repeat=len(auto_indices))
            auto_probability = len(faces) ** len(auto_indices)
            outcome_probability = 0.0
            for auto_replacement in auto_outcomes:
                rolled = list(initial)
                for index, value in zip(auto_indices, auto_replacement):
                    rolled[index] = value
                best = 0.0
                index_sets = [
                    indices
                    for count in range(min(rerolls, num_dice) + 1)
                    for indices in combinations(range(num_dice), count)
                ]
                for indices in index_sets:
                    success_probability = sum(
                        sum(
                            (
                                replacement[indices.index(index)]
                                if index in indices
                                else rolled[index]
                            )
                            for index in range(num_dice)
                        )
                        + bonus
                        >= target
                        for replacement in product(faces, repeat=len(indices))
                    ) / (len(faces) ** len(indices))
                    best = max(best, success_probability)
                outcome_probability += best / auto_probability
            total_probability += outcome_probability / (len(faces) ** num_dice)
        return total_probability
    probability = sum(
        probability
        for total, probability in sum_distribution(num_dice, faces, rerolls).items()
        if total + bonus >= target
    )
    if probability > 1 - 1e-12:
        return 1.0
    if probability < 1e-12:
        return 0.0
    return probability
