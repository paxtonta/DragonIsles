from dragonisles.bot import (
    Decision,
    DecisionContext,
    LiteralPolicy,
    MonkPolicy,
    PiratePolicy,
    TraderPolicy,
    _adventure_draw_value,
    policy_for_character,
)
from dragonisles.cards import Card
from dragonisles.characters import CHARACTERS
from dragonisles.encounters import ChallengeReward, Encounter
from dragonisles.engine import Game, Player, RulesConfig
from dragonisles.potions import DRAW_TWO, PLUS_TWO, PURGE, PotionToken


EASY = Encounter("Easy", 2, 3, 3, 3)
HARD = Encounter("Hard", 10, 20, 20, 20)


def test_bot_attempts_above_threshold():
    decision = LiteralPolicy().choose(
        DecisionContext([Card("red", 1), Card("blue", 2)], [EASY])
    )
    assert decision.action == "attempt"


def test_bot_uses_fewest_cards_above_threshold():
    hand = [
        Card("red", 5),
        Card("blue", 5),
        Card("green", 5),
        Card("yellow", 5),
    ]
    encounter = Encounter("Low-risk", 1, 3, 3, 3)

    decision = LiteralPolicy().choose(DecisionContext(hand, [encounter]))

    assert decision.action == "attempt"
    assert decision.method == "steal"
    assert len(decision.combo) == 2


def test_bot_uses_fewest_cards_above_threshold_for_higher_targets():
    hand = [
        Card("red", 5),
        Card("blue", 5),
        Card("green", 5),
        Card("yellow", 5),
    ]
    encounter = Encounter("Higher target", 1, 7, 7, 7)

    decision = LiteralPolicy().choose(DecisionContext(hand, [encounter]))

    assert decision.action == "attempt"
    assert decision.method == "steal"
    assert len(decision.combo) == 3


def test_bot_preserves_wild_when_steal_options_are_equally_reliable():
    hand = [
        Card("purple", 12),
        Card("yellow", 12),
        Card.wild_card(),
        Card("red", 6),
    ]
    encounter = Encounter("Wild tie", 1, 8, 8, 4, blocked_method="sneak")

    decision = LiteralPolicy().choose(DecisionContext(hand, [encounter]))

    assert decision.action == "attempt"
    assert decision.method == "steal"
    assert decision.combo == (Card("purple", 12), Card("yellow", 12))


def test_monk_prepares_when_best_option_is_hopeless():
    hand = [Card("red", 1), Card("red", 2)]
    assert LiteralPolicy().choose(DecisionContext(hand, [HARD])).action == "prepare"


def test_monk_uses_expected_roll_condition():
    decision = MonkPolicy().choose(
        DecisionContext(
            [Card("red", 1), Card("red", 2)],
            [Encounter("Possible", 1, 6, 6, 6)],
            character=CHARACTERS["Monk"],
        )
    )
    assert decision.action == "attempt"


def test_monk_does_not_use_potion_to_meet_expected_roll_threshold():
    decision = MonkPolicy().choose(
        DecisionContext(
            [Card("red", 1), Card("red", 2)],
            [Encounter("Too risky", 1, 7, 7, 7)],
            character=CHARACTERS["Monk"],
            potions=[PotionToken(PLUS_TWO)],
        )
    )
    assert decision.action == "prepare"


def test_monk_prepares_when_expected_roll_is_too_low():
    decision = MonkPolicy().choose(
        DecisionContext(
            [Card("red", 1), Card("red", 2)],
            [Encounter("Unlikely", 1, 10, 10, 10)],
            character=CHARACTERS["Monk"],
        )
    )
    assert decision.action == "prepare"


def test_bot_prepare_returns_a_prepare_action():
    decision = LiteralPolicy().choose(
        DecisionContext(
            [Card("blue", 9)],
            [HARD],
            [Card("red", 1), Card("green", 12)],
            CHARACTERS["Pirate"],
        )
    )
    assert decision.action == "prepare"


def test_sorcerer_bot_prepare_has_three_choices():
    decision = LiteralPolicy().choose(
        DecisionContext([Card("blue", 9)], [HARD], character=CHARACTERS["Sorcerer"])
    )
    assert decision.action == "prepare"


def test_bot_uses_plus_two_when_it_flips_attempt_threshold():
    hand = [Card("red", 1), Card("red", 2)]
    encounter = Encounter("Borderline", 1, 6, 6, 6)
    decision = LiteralPolicy().choose(
        DecisionContext(hand, [encounter], potions=[PotionToken(PLUS_TWO)])
    )
    assert decision.action == "attempt"
    assert decision.potion is None


def test_bot_keeps_plus_two_for_a_low_value_failure_potion():
    policy = LiteralPolicy()
    context = DecisionContext(
        [Card("red", 1)],
        [],
        potions=[PotionToken(PLUS_TWO)],
    )
    encounter = Encounter("One point", 1, 5, 5, 5)

    assert not policy.choose_plus_two_after_roll(context, encounter, "strike", 4)


def test_bot_spends_plus_two_when_success_beats_failure_potion():
    policy = LiteralPolicy()
    context = DecisionContext(
        [Card("red", 1)],
        [],
        potions=[PotionToken(PLUS_TWO)],
    )
    encounter = Encounter("Three points", 3, 5, 5, 5)

    assert policy.choose_plus_two_after_roll(context, encounter, "strike", 4)


def test_monk_purges_regardless_of_hand_size():
    character = CHARACTERS["Monk"]
    context = DecisionContext(
        [Card("red", 1)] * (character.starting_hand_limit - 1),
        [],
        character=character,
        potions=[PotionToken(PURGE)],
    )

    decision = LiteralPolicy()._non_attempt_decision(context)

    assert decision.action == "use_potion"
    assert decision.potion == PotionToken(PURGE)


def test_non_attempt_decision_skips_purge_for_a_plannable_target():
    character = CHARACTERS["Warrior"]
    context = DecisionContext(
        [Card("red", 1)] * (character.starting_hand_limit - 1),
        [Encounter("Plannable", 1, 1, 1, 1)],
        character=character,
        potions=[PotionToken(PURGE)],
    )

    decision = LiteralPolicy()._non_attempt_decision(context)

    assert decision.action == "prepare"


def test_non_attempt_decision_uses_purge_without_a_plannable_target():
    character = CHARACTERS["Warrior"]
    context = DecisionContext(
        [Card("red", 1)] * (character.starting_hand_limit - 1),
        [HARD],
        character=character,
        potions=[PotionToken(PURGE)],
    )

    decision = LiteralPolicy()._non_attempt_decision(context)

    assert decision.action == "use_potion"
    assert decision.potion == PotionToken(PURGE)


def test_monk_prefers_purge_before_draw_two_with_room():
    character = CHARACTERS["Monk"]
    context = DecisionContext(
        [Card("red", 1)] * (character.starting_hand_limit - 2),
        [],
        character=character,
        potions=[PotionToken(PURGE), PotionToken(DRAW_TWO)],
    )
    draw_two_context = DecisionContext(
        context.hand,
        [],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
    )

    decision = LiteralPolicy()._non_attempt_decision(context)
    draw_two_decision = LiteralPolicy()._non_attempt_decision(draw_two_context)

    assert decision.action == "use_potion"
    assert decision.potion == PotionToken(PURGE)
    assert draw_two_decision.action == "prepare"


def test_monk_uses_draw_two_with_three_safe_slots():
    character = CHARACTERS["Monk"]
    context = DecisionContext(
        [Card("red", 1)] * (character.starting_hand_limit - 3),
        [],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
    )

    decision = LiteralPolicy()._non_attempt_decision(context)

    assert decision.action == "use_potion"
    assert decision.potion == PotionToken(DRAW_TWO)


def test_draw_two_sheds_two_undesirable_cards_past_hand_limit():
    character = CHARACTERS["Warrior"]
    context = DecisionContext(
        [Card("red", rank) for rank in range(1, 6)]
        + [Card("blue", 11), Card("blue", 12)],
        [Encounter("High target", 1, 20, 20, 20)],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
        adventure_cards=[Card("red", 6)],
    )

    policy = LiteralPolicy()
    decision = policy._non_attempt_decision(context)

    assert policy._undesirable_card_count(context) == 2
    assert decision.action == "use_potion"
    assert decision.potion == PotionToken(DRAW_TWO)


def test_draw_two_stays_declined_with_only_one_undesirable_card():
    character = CHARACTERS["Warrior"]
    context = DecisionContext(
        [Card("red", rank) for rank in range(1, 7)] + [Card("blue", 12)],
        [Encounter("High target", 1, 20, 20, 20)],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
    )

    policy = LiteralPolicy()
    decision = policy._non_attempt_decision(context)

    assert policy._undesirable_card_count(context) == 1
    assert decision.action == "prepare"


def test_monk_draw_two_requires_three_undesirable_cards():
    character = CHARACTERS["Monk"]
    context = DecisionContext(
        [Card("red", rank) for rank in range(1, 6)]
        + [Card("blue", 10), Card("blue", 11), Card("blue", 12)],
        [Encounter("High target", 1, 20, 20, 20)],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
        adventure_cards=[Card("red", 6)],
    )

    policy = LiteralPolicy()
    decision = policy._non_attempt_decision(context)

    assert policy._undesirable_card_count(context) == 3
    assert decision.action == "use_potion"
    assert decision.potion == PotionToken(DRAW_TWO)


def test_monk_draw_two_rejects_only_two_undesirable_cards():
    character = CHARACTERS["Monk"]
    context = DecisionContext(
        [Card("red", rank) for rank in range(1, 7)]
        + [Card("blue", 11), Card("blue", 12)],
        [Encounter("High target", 1, 20, 20, 20)],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
    )

    policy = LiteralPolicy()
    decision = policy._non_attempt_decision(context)

    assert policy._undesirable_card_count(context) == 2
    assert decision.action == "prepare"


def test_draw_two_dead_weight_path_requires_a_useful_available_card():
    character = CHARACTERS["Warrior"]
    context = DecisionContext(
        [Card("red", rank) for rank in range(1, 6)]
        + [Card("blue", 11), Card("blue", 12)],
        [Encounter("High target", 1, 20, 20, 20)],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
        adventure_cards=[Card("purple", 12)],
    )
    policy = LiteralPolicy()

    decision = policy._non_attempt_decision(context)

    assert policy._undesirable_card_count(context) == 2
    assert _adventure_draw_value(context, 2) == 0
    assert decision.action == "prepare"


def test_non_monk_potion_thresholds_remain_unchanged():
    character = CHARACTERS["Warrior"]
    purge_context = DecisionContext(
        [Card("red", 1)] * (character.starting_hand_limit - 1),
        [],
        character=character,
        potions=[PotionToken(PURGE)],
    )
    draw_two_context = DecisionContext(
        [Card("red", 1)] * (character.starting_hand_limit - 2),
        [],
        character=character,
        potions=[PotionToken(DRAW_TWO)],
    )

    purge_decision = LiteralPolicy()._non_attempt_decision(purge_context)
    draw_two_decision = LiteralPolicy()._non_attempt_decision(draw_two_context)

    assert purge_decision.potion == PotionToken(PURGE)
    assert draw_two_decision.potion == PotionToken(DRAW_TWO)


def test_non_attempt_decision_handles_missing_character():
    context = DecisionContext(
        [Card("red", 1)] * 7,
        [],
        potions=[PotionToken(PURGE)],
    )
    policy = LiteralPolicy()

    decision = policy._non_attempt_decision(context)

    assert policy._undesirable_card_count(context) == 0
    assert decision.potion == PotionToken(PURGE)


def test_bot_discards_least_useful_card_by_exact_lookahead():
    hand = [Card("red", 1), Card("red", 2), Card("blue", 12)]
    context = DecisionContext(hand, [Encounter("Target", 1, 3, 3, 3)])
    assert LiteralPolicy().choose_discards(context, 1) == (Card("blue", 12),)


def test_bot_prioritizes_a_method_track_for_the_highest_point_encounter():
    policy = LiteralPolicy()
    context = DecisionContext(
        [Card("red", 1), Card("red", 2)],
        [
            Encounter(
                "Sea prize",
                6,
                5,
                5,
                5,
                encounter_type="dragon",
                is_sea=True,
            )
        ],
        character=CHARACTERS["Pirate"],
    )
    assert policy.choose_track(context, ("sea", "reroll", "hand_limit")) == "sea"


def test_bot_chooses_trophy_only_after_securing_two_type_trophies():
    policy = LiteralPolicy()
    events = [(0, "dragon", 1), (0, "oni", 1)]
    context = DecisionContext(
        [],
        [],
        character=CHARACTERS["Warrior"],
        trophy_events=events,
        player_index=0,
    )
    assert policy.choose_track(context, ("trophy", "reroll")) == "trophy"


def test_bot_prefers_reroll_before_trophy_without_two_secured_trophies():
    policy = LiteralPolicy()
    context = DecisionContext(
        [],
        [],
        character=CHARACTERS["Warrior"],
        trophy_events=[(0, "dragon", 1)],
        player_index=0,
    )
    assert policy.choose_track(context, ("trophy", "reroll")) == "reroll"


def test_pirate_values_coin_track_rewards_at_double_points():
    assert LiteralPolicy._reward_score(
        DecisionContext(
            [], [], character=CHARACTERS["Pirate"], skill_levels={"reroll": 1}
        ),
        "reroll",
    ) == 2


def test_bot_never_chooses_blocked_method():
    blocked = Encounter("Blocked", 2, 3, 3, 3, blocked_method="strike")
    decision = LiteralPolicy().choose(
        DecisionContext([Card("red", 1), Card("blue", 2)], [blocked])
    )
    assert decision.method != "strike"


def test_bot_context_includes_opponents_visible_challenge_cards():
    game = Game(
        [EASY] * 6,
        characters=[CHARACTERS["Warrior"], CHARACTERS["Pirate"]],
    )
    human, bot = game.state.players
    human.hand[:2] = [Card("green", 5), Card("green", 6)]
    game.begin_attempt(
        human,
        EASY,
        Decision("attempt", EASY, tuple(human.hand[:2]), "strike"),
    )

    context = game.decision_context(bot)

    assert context.opponent_challenge_cards == (Card("green", 5), Card("green", 6))


def test_literal_policy_progresses_through_encounters_by_ease(monkeypatch):
    encounters = [
        Encounter("First", 1, 3, 3, 3),
        Encounter("Second", 2, 6, 6, 6),
        Encounter("Third", 3, 9, 9, 9),
        Encounter("Hardest", 4, 12, 12, 12),
    ]
    hand = [
        Card("red", 1),
        Card("red", 2),
        Card("blue", 1),
        Card("green", 1),
        Card("yellow", 1),
    ]
    policy = LiteralPolicy()
    monkeypatch.setattr(
        policy, "_encounter_is_winnable", lambda context, encounter: True
    )

    for completed, expected in (
        (0, encounters[0]),
        (1, encounters[0]),
        (2, encounters[1]),
        (3, encounters[1]),
        (4, encounters[2]),
        (5, encounters[2]),
        (6, encounters[3]),
    ):
        assert (
            policy._target_encounter(
                DecisionContext(
                    hand,
                    encounters,
                    completed_encounters=[encounters[0]] * completed,
                )
            )
            == expected
        )


def test_literal_policy_clamps_doubled_ramp_for_short_rows():
    encounters = [
        Encounter("First", 1, 3, 3, 3),
        Encounter("Second", 2, 6, 6, 6),
    ]

    assert (
        LiteralPolicy()._target_encounter(
            DecisionContext([], encounters, completed_encounters=encounters[:6])
        )
        == encounters[1]
    )


def test_literal_policy_falls_back_to_hardest_winnable_at_or_before_schedule(
    monkeypatch,
):
    encounters = [
        Encounter("Easy", 1, 3, 3, 3),
        Encounter("Winnable", 2, 6, 6, 6),
        Encounter("Scheduled", 3, 9, 9, 9),
        Encounter("Hardest", 4, 12, 12, 12),
    ]
    policy = LiteralPolicy()
    monkeypatch.setattr(
        policy,
        "_encounter_is_winnable",
        lambda context, encounter: encounter is encounters[1],
    )

    context = DecisionContext([], encounters, completed_encounters=[encounters[0]] * 4)

    assert policy._target_encounter(context) == encounters[1]


def test_literal_policy_keeps_a_winnable_scheduled_target(monkeypatch):
    encounters = [
        Encounter("Easy", 1, 3, 3, 3),
        Encounter("Winnable", 2, 6, 6, 6),
        Encounter("Scheduled", 3, 9, 9, 9),
    ]
    policy = LiteralPolicy()
    monkeypatch.setattr(
        policy,
        "_encounter_is_winnable",
        lambda context, encounter: encounter is encounters[2],
    )

    context = DecisionContext([], encounters, completed_encounters=[encounters[0]] * 4)

    assert policy._target_encounter(context) == encounters[2]


def test_literal_policy_keeps_unwinnable_schedule_when_no_fallback_exists(
    monkeypatch,
):
    encounters = [
        Encounter("Easy", 1, 3, 3, 3),
        Encounter("Scheduled", 2, 6, 6, 6),
    ]
    policy = LiteralPolicy()
    monkeypatch.setattr(
        policy, "_encounter_is_winnable", lambda context, encounter: False
    )

    context = DecisionContext([], encounters, completed_encounters=[encounters[0]] * 4)

    assert policy._target_encounter(context) == encounters[1]
    assert policy.choose(context).action == "prepare"


def test_endgame_policy_chooses_easiest_winnable_encounter_when_it_wins():
    easy = Encounter("Easy close", 1, 3, 3, 3)
    hard = Encounter("Hard close", 5, 9, 9, 9)
    completed = [Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)]
    context = DecisionContext(
        [Card("red", 1), Card("red", 2), Card("blue", 1)],
        [easy, hard],
        character=CHARACTERS["Warrior"],
        completed_encounters=completed,
        opponent_character=CHARACTERS["Warrior"],
    )

    assert LiteralPolicy()._target_encounter(context) == easy


def test_endgame_policy_keeps_ramp_when_finishing_would_still_lose(monkeypatch):
    easy = Encounter("Easy close", 1, 3, 3, 3)
    hard = Encounter("Hard close", 5, 9, 9, 9)
    completed = [Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)]
    opponent = [Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(4)]
    context = DecisionContext(
        [Card("red", 1), Card("red", 2), Card("blue", 1)],
        [easy, hard],
        character=CHARACTERS["Warrior"],
        completed_encounters=completed,
        opponent_encounters=opponent,
        opponent_character=CHARACTERS["Warrior"],
    )
    policy = LiteralPolicy()
    monkeypatch.setattr(
        policy, "_encounter_is_winnable", lambda context, encounter: True
    )

    assert policy._target_encounter(context) == hard


def test_endgame_policy_falls_back_when_hardest_slot_is_unwinnable(monkeypatch):
    encounters = [
        Encounter("Easy close", 1, 3, 3, 3),
        Encounter("Hard close", 5, 9, 9, 9),
    ]
    completed = [Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)]
    opponent = [Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(4)]
    context = DecisionContext(
        [Card("red", 1), Card("red", 2), Card("blue", 1)],
        encounters,
        character=CHARACTERS["Warrior"],
        completed_encounters=completed,
        opponent_encounters=opponent,
        opponent_character=CHARACTERS["Warrior"],
    )
    policy = LiteralPolicy()
    monkeypatch.setattr(
        policy,
        "_encounter_is_winnable",
        lambda context, encounter: encounter is encounters[0],
    )

    assert policy._target_encounter(context) == encounters[0]


def test_endgame_fallback_target_can_reach_game_over():
    easy = Encounter("Easy close", 1, 3, 3, 3)
    hard = Encounter("Hard close", 5, 9, 9, 9)
    human = Player("Human", CHARACTERS["Warrior"])
    bot = Player("Bot", CHARACTERS["Warrior"], is_bot=True)
    game = Game(
        [easy, hard],
        rules=RulesConfig(die_faces=(6,)),
        players=[human, bot],
    )
    bot.encounters.extend(
        [Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)]
    )
    human.encounters.extend(
        [Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(1)]
    )
    bot.hand[:] = [Card("red", 1)]
    context = game.decision_context(bot)

    decision = game.bot_policy.choose(context)

    assert decision.encounter == easy
    assert decision.action == "attempt"
    assert game.attempt(bot, easy, decision)
    assert game.state.game_over


def test_endgame_policy_stalls_when_no_encounter_can_catch_up():
    encounter = Encounter("Easy but losing", 1, 1, 1, 1)
    context = DecisionContext(
        [Card("red", 1)],
        [encounter],
        character=CHARACTERS["Warrior"],
        completed_encounters=[
            Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)
        ],
        opponent_encounters=[
            Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(4)
        ],
        opponent_character=CHARACTERS["Warrior"],
        potions=[PotionToken(PURGE)],
    )

    decision = LiteralPolicy().choose(context)

    assert decision.action == "use_potion"
    assert decision.potion == PotionToken(PURGE)


def test_endgame_policy_attempts_an_encounter_that_wins_on_printed_vp():
    encounter = Encounter("Winning close", 1, 1, 1, 1)
    context = DecisionContext(
        [Card("red", 1)],
        [encounter],
        character=CHARACTERS["Warrior"],
        completed_encounters=[
            Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)
        ],
        opponent_encounters=[Encounter("Opponent", 1, 3, 3, 3)],
        opponent_character=CHARACTERS["Warrior"],
    )

    decision = LiteralPolicy().choose(context)

    assert decision.action == "attempt"
    assert decision.encounter == encounter


def test_endgame_policy_attempts_an_exact_tie():
    encounter = Encounter("Tying close", 1, 1, 1, 1)
    context = DecisionContext(
        [Card("red", 1)],
        [encounter],
        character=CHARACTERS["Warrior"],
        completed_encounters=[
            Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)
        ],
        opponent_encounters=[
            Encounter(f"Opponent {index}", 4, 9, 9, 9) for index in range(2)
        ],
        opponent_character=CHARACTERS["Warrior"],
    )

    decision = LiteralPolicy().choose(context)

    assert decision.action == "attempt"
    assert decision.encounter == encounter


def test_eighth_encounter_projection_excludes_rewards_and_trophy_events():
    encounter = Encounter(
        "Reward close",
        1,
        1,
        1,
        1,
        encounter_type="dragon",
        icons=2,
        rewards={"strike": ChallengeReward(coins=2, treasure=True)},
    )
    context = DecisionContext(
        [Card("red", 1)],
        [encounter],
        character=CHARACTERS["Pirate"],
        completed_encounters=[
            Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)
        ],
        coins=0,
        trophy_events=[(1, "dragon", 1)],
        opponent_encounters=[
            Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(2)
        ],
        opponent_character=CHARACTERS["Pirate"],
    )

    assert not LiteralPolicy()._would_close_out_a_win(context, encounter)


def test_eighth_encounter_projection_excludes_method_rewards():
    encounter = Encounter(
        "Coin close",
        1,
        1,
        1,
        1,
        rewards={"strike": ChallengeReward(coins=2, treasure=True)},
    )
    context = DecisionContext(
        [Card("red", 1)],
        [encounter],
        character=CHARACTERS["Pirate"],
        completed_encounters=[
            Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)
        ],
        opponent_encounters=[
            Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(2)
        ],
        opponent_character=CHARACTERS["Pirate"],
    )

    assert not LiteralPolicy()._would_close_out_a_win(context, encounter)


def test_endgame_fallback_skips_encounters_that_would_lose(monkeypatch):
    losing = Encounter("Losing close", 1, 1, 1, 1)
    winning = Encounter("Winning close", 5, 1, 1, 1)
    context = DecisionContext(
        [Card("red", 1)],
        [losing, winning],
        character=CHARACTERS["Warrior"],
        completed_encounters=[
            Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(7)
        ],
        opponent_encounters=[
            Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(2)
        ],
        opponent_character=CHARACTERS["Warrior"],
    )
    policy = LiteralPolicy()
    monkeypatch.setattr(policy, "_target_encounter", lambda context: losing)

    decision = policy.choose(context)

    assert decision.action == "attempt"
    assert decision.encounter == winning


def test_six_completed_encounters_do_not_trigger_endgame_gate():
    encounter = Encounter("Still ramping", 1, 1, 1, 1)
    context = DecisionContext(
        [Card("red", 1)],
        [encounter],
        character=CHARACTERS["Warrior"],
        completed_encounters=[
            Encounter(f"Done {index}", 1, 3, 3, 3) for index in range(6)
        ],
        opponent_encounters=[
            Encounter(f"Opponent {index}", 5, 9, 9, 9) for index in range(4)
        ],
        opponent_character=CHARACTERS["Warrior"],
    )

    decision = LiteralPolicy().choose(context)

    assert decision.action == "attempt"
    assert decision.encounter == encounter


def test_character_reward_preferences_break_equal_difficulty_target_ties():
    coin = Encounter(
        "Coin tie",
        1,
        5,
        5,
        5,
        rewards={"steal": ChallengeReward(coins=1)},
    )
    treasure = Encounter(
        "Treasure tie",
        1,
        5,
        5,
        5,
        rewards={"steal": ChallengeReward(treasure=True)},
    )
    context = DecisionContext(
        [Card("red", 1), Card("red", 2), Card("blue", 1), Card("green", 1)],
        [coin, treasure],
        character=CHARACTERS["Trader"],
    )

    assert TraderPolicy()._target_encounter(context) == treasure


def test_steal_method_attainability_makes_equal_target_card_harder():
    steal = Encounter(
        "Steal card",
        1,
        20,
        20,
        6,
        blocked_method="strike",
    )
    sneak = Encounter(
        "Sneak card",
        1,
        6,
        0,
        20,
        blocked_method="steal",
    )
    policy = LiteralPolicy()

    assert (
        policy._encounter_order_key(DecisionContext([], []), steal)[0]
        > policy._encounter_order_key(DecisionContext([], []), sneak)[0]
    )


def test_prepare_source_prioritizes_the_ramp_target(monkeypatch):
    hand = [
        Card("red", 5),
        Card("red", 7),
        Card("purple", 4),
    ]
    market = [Card("red", 11), Card.wild_card()]
    target = Encounter("Ramp", 1, 5, 5, 5)
    other = Encounter("Other", 1, 3, 3, 3)
    context = DecisionContext(
        hand,
        [target, other],
        market=market,
        character=CHARACTERS["Warrior"],
    )
    policy = LiteralPolicy()
    monkeypatch.setattr(policy, "_target_encounter", lambda context: target)

    assert policy.choose_prepare_source(context) == market[1]


def test_prepare_source_prefers_market_when_its_gain_exceeds_deck_value(monkeypatch):
    market = Card("red", 1)
    context = DecisionContext(
        [],
        [Encounter("Small target", 3, 2, 2, 2)],
        market=[market],
    )
    monkeypatch.setattr(
        "dragonisles.bot._adventure_draw_value",
        lambda context, draw_count: 1.0,
    )

    assert LiteralPolicy().choose_prepare_source(context) == market


def test_prepare_source_prefers_deck_when_market_gain_does_not_exceed_it(
    monkeypatch,
):
    market = Card("red", 1)
    context = DecisionContext(
        [],
        [Encounter("Small target", 1, 2, 2, 2)],
        market=[market],
    )
    monkeypatch.setattr(
        "dragonisles.bot._adventure_draw_value",
        lambda context, draw_count: 1.0,
    )

    assert LiteralPolicy().choose_prepare_source(context) == "deck"


def test_prepare_source_does_not_count_visible_needed_card_as_drawable():
    hand = [Card("red", 1)]
    market = [Card("blue", 1)]
    context = DecisionContext(
        hand,
        [Encounter("Steal target", 1, 100, 100, 5)],
        market=market,
        adventure_cards=[Card("green", 12)],
    )

    assert _adventure_draw_value(context, 1) == 0
    assert LiteralPolicy().choose_prepare_source(context) == market[0]


def test_prepare_source_accounts_for_method_skill_bonus(monkeypatch):
    hand = [
        Card("purple", 2),
        Card("purple", 6),
        Card("blue", 2),
        Card("red", 12),
    ]
    market = [Card("yellow", 2), Card("red", 11)]
    target = Encounter("Ramp", 1, 8, 8, 8)
    policy = LiteralPolicy()
    plain = DecisionContext(
        hand,
        [target],
        market=market,
        character=CHARACTERS["Warrior"],
    )
    skilled = DecisionContext(
        hand,
        [target],
        market=market,
        character=CHARACTERS["Warrior"],
        skill_levels={"sneak": 3},
    )
    monkeypatch.setattr(policy, "_target_encounter", lambda context: target)

    assert policy.choose_prepare_source(plain) == market[0]
    assert policy.choose_prepare_source(skilled) == market[1]


def test_literal_policy_prefers_a_rewarded_method_when_both_qualify():
    encounter = Encounter(
        "Reward",
        1,
        3,
        3,
        3,
        rewards={"strike": ChallengeReward(coins=1)},
    )
    decision = LiteralPolicy().choose(
        DecisionContext(
            [
                Card("red", 1),
                Card("red", 2),
                Card("blue", 1),
                Card("green", 1),
            ],
            [encounter],
        )
    )
    assert decision.method == "strike"


def test_trader_prefers_treasure_reward_without_changing_target():
    encounter = Encounter(
        "Rewards",
        1,
        5,
        5,
        5,
        rewards={
            "steal": ChallengeReward(coins=1),
            "strike": ChallengeReward(treasure=True),
        },
    )
    hand = [
        Card("red", 1),
        Card("red", 2),
        Card("red", 3),
        Card("blue", 1),
        Card("green", 1),
    ]
    decision = TraderPolicy().choose(
        DecisionContext(hand, [encounter], character=CHARACTERS["Trader"])
    )
    assert decision.encounter == encounter
    assert decision.method == "strike"


def test_pirate_prefers_coin_rewarded_steal_to_unrewarded_method():
    decision = PiratePolicy().choose(
        DecisionContext(
            [
                Card("red", 1),
                Card("red", 2),
                Card("blue", 1),
                Card("green", 1),
            ],
            [
                Encounter(
                    "Coin",
                    1,
                    5,
                    4,
                    7,
                    rewards={"steal": ChallengeReward(coins=1)},
                )
            ],
            character=CHARACTERS["Pirate"],
        )
    )
    assert decision.action == "attempt"
    assert decision.method == "steal"


def test_pirate_selects_the_easier_coin_rewarded_encounter():
    coin = Encounter(
        "Coin",
        1,
        5,
        4,
        7,
        rewards={"steal": ChallengeReward(coins=1)},
    )
    high = Encounter("High", 2, 5, 5, 5)
    decision = PiratePolicy().choose(
        DecisionContext(
            [Card("red", 1), Card("red", 2), Card("blue", 1), Card("green", 1)],
            [coin, high],
            character=CHARACTERS["Pirate"],
        )
    )
    assert decision.action == "attempt"
    assert decision.encounter is not None
    assert decision.encounter.name == "Coin"


def test_game_selects_character_specific_bot_policy():
    from dragonisles.engine import Game

    game = Game(
        [Encounter("Target", 1, 5, 5, 5)] * 6,
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    assert isinstance(game.bot_policy, PiratePolicy)
    assert isinstance(policy_for_character(CHARACTERS["Monk"]), MonkPolicy)
    assert isinstance(policy_for_character(CHARACTERS["Trader"]), TraderPolicy)
    assert isinstance(policy_for_character(CHARACTERS["Sorcerer"]), LiteralPolicy)
    assert isinstance(policy_for_character(CHARACTERS["Warrior"]), LiteralPolicy)
