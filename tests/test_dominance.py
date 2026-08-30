from tools.check_dominance import (
    _effective_difficulty,
    _method_availability,
    material_shape_warnings,
    materially_dominated_cards,
)
from dragonisles.encounters import ChallengeReward, Encounter


def _encounter(
    encounter_id: str,
    *,
    sneak: int,
    steal: int,
    strike: int,
    rewards: dict[str, ChallengeReward] | None = None,
) -> Encounter:
    return Encounter(
        encounter_id,
        3,
        strike,
        sneak,
        steal,
        id=encounter_id,
        encounter_type="oni",
        rewards=rewards or {},
    )


def test_dominance_model_uses_deck_method_constraints_and_dice():
    assert _method_availability("steal", 6) == 0.0
    assert _method_availability("steal", 4) < _method_availability("strike", 4)
    assert _effective_difficulty(
        _encounter("hard", sneak=12, steal=12, strike=12), "strike"
    ) > _effective_difficulty(_encounter("easy", sneak=8, steal=8, strike=8), "strike")


def test_coin_only_technical_pair_is_not_material():
    plain = _encounter("plain", sneak=10, steal=10, strike=10)
    coin = _encounter(
        "coin",
        sneak=10,
        steal=10,
        strike=10,
        rewards={"strike": ChallengeReward(coins=1)},
    )

    assert materially_dominated_cards([plain, coin]) == []


def test_extreme_no_reward_tradeoff_is_a_shape_warning():
    kasha = _encounter("kasha", sneak=5, steal=8, strike=11)

    assert material_shape_warnings([kasha]) == ["kasha"]


def test_steal_cannot_be_hardest_route_without_steal_reward():
    no_reward = _encounter("no_reward", sneak=4, steal=6, strike=5)
    steal_coin = _encounter(
        "steal_coin",
        sneak=4,
        steal=6,
        strike=5,
        rewards={"steal": ChallengeReward(coins=1)},
    )

    assert material_shape_warnings([no_reward]) == ["no_reward"]
    assert material_shape_warnings([steal_coin]) == []
