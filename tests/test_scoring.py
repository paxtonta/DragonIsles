from dragonisles.characters import CHARACTERS
from dragonisles.encounters import Encounter
from dragonisles.scoring import score_player, trophy_holders
from dragonisles.treasures import Treasure


def test_scoring_includes_variety_trophy_orange_treasure_and_pirate_coins():
    encounters = [
        Encounter(str(i), 2, 1, 1, 1, encounter_type=f"type{i}") for i in range(5)
    ]
    orange = Treasure("orange", victory_points=1, encounter_type="type0")
    score = score_player(
        encounters,
        [orange],
        coins=3,
        character=CHARACTERS["Pirate"],
        encounter_types=tuple(f"type{i}" for i in range(5)),
    )
    assert score.encounter_points == 10
    assert score.orange_treasure_points == 1
    assert score.trophy_points == 20
    assert score.coin_points == 6
    assert score.total == 37


def test_multiple_icons_count_toward_type_trophy_without_extra_vp():
    encounters = [
        Encounter("two oni icons", 2, 1, 1, 1, encounter_type="oni", icons=2),
        Encounter("dragon", 2, 1, 1, 1, encounter_type="dragon"),
    ]
    score = score_player(
        encounters,
        [],
        coins=0,
        character=CHARACTERS["Monk"],
        encounter_types=("oni", "dragon"),
    )

    assert score.encounter_points == 4
    assert score.trophy_points == 11
    assert score.total == 15


def test_trophy_track_adds_cumulative_bonus_to_all_six_trophies():
    encounter_types = ("dragon", "oni", "bakemono", "tsukumogami", "location")
    encounters = [
        Encounter(kind, 1, 1, 1, 1, encounter_type=kind) for kind in encounter_types
    ]
    score = score_player(
        encounters,
        [],
        coins=0,
        character=CHARACTERS["Monk"],
        encounter_types=encounter_types,
        skill_levels={"trophy": 3},
    )

    assert score.trophy_points == 38


def test_trophy_lead_is_kept_when_opponent_catches_up():
    holders, _ = trophy_holders(
        [(0, "tsukumogami", 2), (1, "tsukumogami", 1), (1, "tsukumogami", 1)],
        player_count=2,
        encounter_types=("tsukumogami",),
    )
    assert holders["tsukumogami"] == 0


def test_trophy_transfers_only_after_strict_surpass():
    holders, _ = trophy_holders(
        [(0, "oni", 1), (1, "oni", 1), (1, "oni", 1)],
        player_count=2,
        encounter_types=("oni",),
    )
    assert holders["oni"] == 1


def test_two_icon_event_can_jump_past_existing_trophy_holder():
    holders, _ = trophy_holders(
        [(0, "dragon", 1), (1, "dragon", 2)],
        player_count=2,
        encounter_types=("dragon",),
    )
    assert holders["dragon"] == 1


def test_orange_treasure_tying_a_type_does_not_transfer_trophy():
    holders, _ = trophy_holders(
        [(0, "tsukumogami", 2), (1, "tsukumogami", 1), (1, "tsukumogami", 1)],
        player_count=2,
        encounter_types=("tsukumogami",),
    )
    assert holders["tsukumogami"] == 0


def test_shogoro_lead_keeps_tsukumogami_trophy_at_two_to_two():
    events = [
        (1, "tsukumogami", 2),
        (0, "tsukumogami", 1),
        (0, "tsukumogami", 1),
    ]
    holders, _ = trophy_holders(
        events,
        player_count=2,
        encounter_types=("tsukumogami",),
    )
    assert holders["tsukumogami"] == 1


def test_each_player_keeps_their_all_types_trophy_after_completing_set():
    events = [(0, item, 1) for item in ("dragon", "oni", "bakemono", "tsukumogami")]
    events += [(1, "location", 1), (0, "location", 1)]
    holders, all_types_holder = trophy_holders(
        events,
        player_count=2,
        encounter_types=("dragon", "oni", "bakemono", "tsukumogami", "location"),
    )
    assert all_types_holder == frozenset({0})

    events += [(1, item, 1) for item in ("dragon", "oni", "bakemono", "tsukumogami")]
    holders, all_types_holders = trophy_holders(
        events,
        player_count=2,
        encounter_types=("dragon", "oni", "bakemono", "tsukumogami", "location"),
    )
    assert all_types_holders == frozenset({0, 1})
