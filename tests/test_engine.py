import random
import re
from collections import Counter
from pathlib import Path

from dragonisles.cards import SUITS, AdventurerDeck, Card
from dragonisles.characters import (
    CHARACTERS,
    SKILL_TRACKS,
    TrackStep,
    hand_limit_bonus,
    reroll_count,
    track_reward,
    track_value,
)
from dragonisles.cli import _completed_encounters_text, _print_state
from dragonisles.combos import is_legal
import pytest

from dragonisles.encounters import (
    ChallengeReward,
    Encounter,
    load_encounters,
    validate_encounters,
)
from dragonisles.engine import Game, GameInteraction, Player, RulesConfig
from dragonisles.potions import DRAW_TWO, PLUS_TWO, PURGE, PotionToken
from dragonisles.scoring import ScoreBreakdown
from dragonisles.treasures import Treasure, default_treasure_supply


def _name_words(name: str) -> set[str]:
    return set(re.findall(r"[a-z]+(?:'[a-z]+)?", name.lower()))


def encounters(count=10):
    return [
        Encounter(f"Encounter {i}", 1, 1, 1, 1, encounter_type=f"type{i % 5}")
        for i in range(count)
    ]


def test_bot_draw_valuation_uses_known_card_pool_not_private_draw_pile():
    cards = [Card("red", rank) for rank in range(1, 13)] + [
        Card("blue", rank) for rank in range(1, 9)
    ]
    game = Game(
        encounters(),
        rules=RulesConfig(
            deck_factory=lambda: AdventurerDeck(cards, rng=random.Random(1)),
        ),
        characters=[CHARACTERS["Monk"], CHARACTERS["Warrior"]],
        rng=random.Random(2),
    )
    bot = next(player for player in game.state.players if player.is_bot)
    human = next(player for player in game.state.players if not player.is_bot)
    context = game.decision_context(bot)

    assert bot.hand[0] not in context.adventure_cards
    assert human.hand[0] in context.adventure_cards
    assert set(context.adventure_cards) != set(game.state.deck.draw_pile)
def test_prepare_draws_two_and_refills_market():
    game = Game(encounters(), rng=random.Random(2))
    player = game.state.players[0]
    before = len(player.hand)
    market_card = game.state.market[0]
    drawn = game.prepare(player, ("deck", market_card))
    assert len(drawn) == 2
    assert len(player.hand) == before + 2
    assert len(game.state.market) == 2


def test_prepare_discards_after_each_individual_draw():
    discard_observations = []
    game = Game(
        encounters(),
        interaction=GameInteraction(
            choose_discards=lambda player, count: (
                discard_observations.append((len(player.hand), count))
                or player.hand[:count]
            )
        ),
        characters=[CHARACTERS["Warrior"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.hand[:] = [
        Card("red", rank) for rank in range(1, player.hand_limit + 1)
    ]

    game.prepare(player, ("deck", "deck"))

    assert discard_observations == [
        (player.hand_limit + 1, 1),
        (player.hand_limit + 1, 1),
    ]
    assert len(player.hand) == player.hand_limit


def test_prepare_resolves_market_replacement_before_second_draw():
    game = Game(encounters(), rng=random.Random(2))
    player = game.state.players[0]
    first = Card("red", 1)
    second = Card("blue", 1)
    replacement = Card("green", 5)
    filler = Card("yellow", 6)
    game.state.market[:] = [first, second]
    game.state.deck.draw_pile[:] = [filler, replacement]

    assert game.prepare_one(player, first) == first
    assert game.state.market == [second, replacement]
    assert game.prepare_one(player, replacement) == replacement
    game.finish_prepare(player)
    assert player.hand[-2:] == [first, replacement]


def test_bot_prepare_rederives_source_after_market_refill():
    game = Game(
        encounters(),
        characters=[CHARACTERS["Trader"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.is_bot = True
    first = Card("red", 1)
    second = Card("blue", 1)
    replacement = Card("green", 5)
    filler = Card("yellow", 6)
    game.state.market[:] = [first, second]
    game.state.deck.draw_pile[:] = [filler, replacement]

    class SourcePolicy:
        def __init__(self):
            self.markets = []

        def choose_prepare_source(self, context):
            self.markets.append(tuple(context.market))
            return context.market[0] if len(self.markets) == 1 else context.market[1]

    policy = SourcePolicy()
    assert game.bot_prepare(player, policy) == (first, replacement)
    assert policy.markets == [(first, second), (second, replacement)]


def test_bot_prepare_events_reveal_market_source_but_not_deck_card():
    events = []
    game = Game(
        encounters(),
        characters=[CHARACTERS["Trader"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(announce=events.append),
    )
    player = game.state.players[0]
    first = Card("red", 1)
    deck_card = Card("green", 5)
    filler = Card("yellow", 6)
    game.state.market[:] = [first, Card("blue", 2)]
    game.state.deck.draw_pile[:] = [filler, deck_card]

    class SourcePolicy:
        def __init__(self):
            self.draws = 0

        def choose_prepare_source(self, context):
            self.draws += 1
            return context.market[0] if self.draws == 1 else "deck"

    game.bot_prepare(player, SourcePolicy())

    assert events == [
        "Human Prepared from market card red 1.",
        "Human Prepared from the deck.",
    ]
    assert "green 5" not in "\n".join(events)


def test_confirmed_adventurer_deck_composition():
    cards = AdventurerDeck.standard_cards()
    assert len(cards) == 64
    assert Counter(card.wild for card in cards) == {False: 60, True: 4}
    assert {card.suit for card in cards if not card.wild} == {
        "red",
        "purple",
        "yellow",
        "green",
        "blue",
    }
    assert {card.rank for card in cards if not card.wild} == set(range(1, 13))


def test_adventurer_suits_use_purple_instead_of_orange():
    assert "purple" in SUITS
    assert "orange" not in SUITS


def test_cli_marks_sea_encounters(capsys):
    sea = Encounter("Misty Straits", 3, 10, 11, 12, is_sea=True)
    game = Game([sea, *encounters(3)])
    _print_state(game, game.state.players[0])
    assert "[SEA]" in capsys.readouterr().out


def test_steal_requires_distinct_colors_and_wilds_fill_missing_colors():
    same_color = (Card("red", 4), Card("red", 4))
    distinct_colors = (Card("red", 4), Card("blue", 4))
    with_wild = (Card("red", 4), Card("blue", 4), Card(None, None, wild=True))
    assert not is_legal(same_color, "steal")
    assert is_legal(distinct_colors, "steal")
    assert is_legal(with_wild, "steal")


def test_reconstructed_encounter_deck_has_confirmed_shape():
    loaded = load_encounters(Path("data/encounters.json"))
    assert len(loaded) == 50
    assert Counter(card.encounter_type for card in loaded) == {
        "dragon": 10,
        "oni": 10,
        "bakemono": 10,
        "tsukumogami": 10,
        "location": 10,
    }
    assert loaded[0].name == "Mountain of Darkness"
    assert loaded[0].encounter_type == "location"
    assert len({card.id for card in loaded}) == 50
    assert sum(card.is_sea for card in loaded) == 25
    assert all(
        card.is_sea and card.icons == 1
        for card in loaded
        if card.encounter_type == "dragon"
    )
    assert next(card for card in loaded if card.id == "tengu_peak")
    assert {"Mountain of Darkness", "Thorned Pass"} <= {
        card.name for card in loaded if card.encounter_type == "location"
    }
    assert sum(card.blocked_method is not None for card in loaded) == 10
    assert all(
        getattr(card, f"{card.blocked_method}_target") == 0
        for card in loaded
        if card.blocked_method
    )


def test_duplicate_stat_groups_only_vary_by_name():
    cards = {card.id: card for card in load_encounters(Path("data/encounters.json"))}
    groups = (
        ("mountain_of_darkness_1", "mountain_of_darkness_2"),
        ("thorned_pass_1", "thorned_pass_2"),
        ("eternal_blossom_forest_1", "eternal_blossom_forest_2"),
        ("luck_dragon_1", "luck_dragon_2", "luck_dragon_3"),
        ("sea_dragon_1", "sea_dragon_2", "sea_dragon_3"),
        ("rain_dragon_1", "rain_dragon_2"),
        ("oni_1", "oni_2"),
        ("kasha_1", "kasha_2"),
        ("kasha_3", "kasha_4"),
        ("kitsune_1", "kitsune_2"),
        ("tanuki_1", "tanuki_2"),
        ("tanuki_3", "tanuki_4"),
        ("kamaitachi_1", "kamaitachi_2"),
    )
    for group in groups:
        first = cards[group[0]]
        signature = (
            first.encounter_type,
            first.family,
            first.is_sea,
            first.icons,
            first.victory_points,
            first.sneak_target,
            first.steal_target,
            first.strike_target,
            first.blocked_method,
            first.rewards,
        )
        assert all(
            (
                cards[card_id].encounter_type,
                cards[card_id].family,
                cards[card_id].is_sea,
                cards[card_id].icons,
                cards[card_id].victory_points,
                cards[card_id].sneak_target,
                cards[card_id].steal_target,
                cards[card_id].strike_target,
                cards[card_id].blocked_method,
                cards[card_id].rewards,
            )
            == signature
            for card_id in group
        )


def test_encounter_names_match_sea_land_status():
    assert _name_words("Smugglers' Cove") == {"smugglers", "cove"}
    assert "sea" not in _name_words("Seaside")


def test_standard_encounter_names_are_not_all_caps():
    cards = load_encounters(Path("data/encounters.json"))
    assert all(card.name != card.name.upper() for card in cards)


def test_completed_encounter_display_always_uses_plain_names():
    cards = load_encounters(Path("data/encounters.json"))
    single = [next(card for card in cards if card.id == "shogoro")]
    duplicate = [
        card for card in cards if card.id in {"luck_dragon_1", "luck_dragon_2"}
    ]
    assert _completed_encounters_text(single) == "Shogoro"
    assert _completed_encounters_text(duplicate) == "Luck Dragon, Luck Dragon"


def test_setup_redeals_homogeneous_rows_until_sea_status_is_mixed():
    cards = [Encounter(f"Sea {i}", 1, 1, 1, 1, is_sea=True) for i in range(4)] + [
        Encounter(f"Land {i}", 1, 1, 1, 1) for i in range(4)
    ]
    game = Game(cards, rng=random.Random(4))
    assert any(card.is_sea for card in game.state.encounters)
    assert not all(card.is_sea for card in game.state.encounters)


def test_replacing_an_encounter_rebalances_the_row():
    cards = [Encounter(f"Sea {i}", 1, 1, 1, 1, is_sea=True) for i in range(4)] + [
        Encounter(f"Land {i}", 1, 1, 1, 1) for i in range(4)
    ]
    game = Game(cards, rng=random.Random(7))
    game.state.encounters[:] = [
        Encounter(f"Current Sea {i}", 1, 1, 1, 1, is_sea=True) for i in range(4)
    ]
    game._encounter_deck = [
        Encounter("Replacement Land", 1, 1, 1, 1),
        Encounter("Replacement Sea", 1, 1, 1, 1, is_sea=True),
    ]
    game.replace_encounter(game.state.encounters[0])
    assert any(card.is_sea for card in game.state.encounters)
    assert not all(card.is_sea for card in game.state.encounters)


def test_purge_refill_rebalances_the_row():
    cards = [Encounter(f"Sea {i}", 1, 1, 1, 1, is_sea=True) for i in range(4)] + [
        Encounter(f"Land {i}", 1, 1, 1, 1) for i in range(4)
    ]
    game = Game(cards, rng=random.Random(9))
    player = game.state.players[0]
    purge = PotionToken(PURGE)
    player.potions.append(purge)
    game.state.encounters[:] = [
        Encounter(f"Current Land {i}", 1, 1, 1, 1) for i in range(4)
    ]
    game._encounter_deck = [
        Encounter("Purge Land", 1, 1, 1, 1),
        Encounter("Purge Sea", 1, 1, 1, 1, is_sea=True),
    ]
    game.use_potion(player, purge)
    assert any(card.is_sea for card in game.state.encounters)
    assert not all(card.is_sea for card in game.state.encounters)


def test_row_redeal_falls_back_when_no_mixed_row_is_possible():
    cards = [Encounter(f"Sea {i}", 1, 1, 1, 1, is_sea=True) for i in range(8)]
    game = Game(cards, rng=random.Random(1))
    assert len(game.state.encounters) == 4
    assert all(card.is_sea for card in game.state.encounters)


def test_encounter_discard_recycles_after_repeated_purges():
    cards = [Encounter(f"Sea {i}", 1, 1, 1, 1, is_sea=True) for i in range(4)] + [
        Encounter(f"Land {i}", 1, 1, 1, 1) for i in range(4)
    ]
    game = Game(
        cards,
        rng=random.Random(14),
        interaction=GameInteraction(
            choose_discards=lambda player, count: player.hand[:count]
        ),
    )
    player = game.state.players[0]
    for _ in range(5):
        player.potions.append(PotionToken(PURGE))
        game.use_potion(player, player.potions[-1])
        assert len(game.state.encounters) == 4


def test_encounter_discard_recycles_only_after_draw_pile_is_empty():
    cards = [Encounter("Initial", 1, 1, 1, 1)] * 8
    game = Game(cards, rng=random.Random(15))
    deck_card = Encounter("Draw first", 1, 1, 1, 1)
    discard_cards = [
        Encounter("Discard one", 1, 1, 1, 1),
        Encounter("Discard two", 1, 1, 1, 1),
    ]
    game._encounter_deck = [deck_card]
    game._encounter_discard = discard_cards.copy()
    assert game._draw_encounter() == deck_card
    assert set(game._encounter_deck) == set()
    recycled = game._draw_encounter()
    assert recycled in discard_cards
    assert set(game._encounter_discard) == set()


def test_won_encounter_is_never_added_to_encounter_discard():
    cards = [Encounter(f"Card {i}", 1, 1, 1, 1) for i in range(8)]
    game = Game(cards, rng=random.Random(16))
    won = game.state.encounters[0]
    game.replace_encounter(won)
    assert won not in game.state.encounters
    assert won not in game._encounter_deck
    assert won not in game._encounter_discard


def test_skill_tracks_upgrade_hand_limit_and_sea_roll_bonus():
    sea = Encounter("Sea", 1, 2, 3, 4, encounter_type="location", is_sea=True)
    game = Game(
        [sea, *encounters(5)],
        rules=RulesConfig(die_faces=(1,)),
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
        rng=random.Random(8),
    )
    player = game.state.players[0]
    player.skill_levels["hand_limit"] = 1
    player.skill_levels["sea"] = 1
    assert player.hand_limit == 8
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    from dragonisles.bot import Decision

    assert game.attempt(
        player, sea, Decision("attempt", sea, tuple(player.hand[:2]), "strike")
    )
    assert game.last_roll is not None
    assert game.last_roll[1] == 1


def test_prepare_refills_market_after_each_market_card():
    game = Game(encounters(), rng=random.Random(9))
    first = game.state.market[0]
    second = game.state.market[1]
    game.prepare(game.state.players[0], (first, second))
    assert len(game.state.market) == 2


def test_confirmed_starting_hand_size_and_character_limits():
    expected_limits = {
        "Warrior": 7,
        "Pirate": 7,
        "Trader": 7,
        "Monk": 8,
        "Sorcerer": 8,
    }
    for name, limit in expected_limits.items():
        opponent = "Pirate" if name != "Pirate" else "Monk"
        game = Game(encounters(), characters=[CHARACTERS[name], CHARACTERS[opponent]])
        assert len(game.state.players[0].hand) == 5
        assert game.state.players[0].hand_limit == limit


def test_skill_track_advancement_is_announced_for_bots():
    announcements = []
    game = Game(
        encounters(),
        players=[
            Player("Bot A", CHARACTERS["Monk"], is_bot=True),
            Player("Bot B", CHARACTERS["Pirate"], is_bot=True),
        ],
        interaction=GameInteraction(announce=announcements.append),
    )
    game.advance_experience(game.state.players[0])
    assert announcements
    assert "Bot A advanced the" in announcements[-1]


def test_game_accepts_explicit_players_and_controller_flags():
    players = [
        Player("Adaptive", CHARACTERS["Pirate"], is_bot=True),
        Player("Baseline", CHARACTERS["Pirate"], is_bot=True),
    ]
    game = Game(encounters(), players=players)
    assert game.state.players == players
    assert all(player.is_bot for player in game.state.players)


def test_default_game_deals_two_distinct_random_characters():
    game = Game(encounters(), rng=random.Random(17))
    assert game.state.players[0].character != game.state.players[1].character
    assert all(player.character.name in CHARACTERS for player in game.state.players)


def test_sorcerer_prepare_draws_three_cards():
    interaction = GameInteraction(
        choose_discards=lambda player, count: player.hand[:count]
    )
    game = Game(
        encounters(),
        characters=[CHARACTERS["Sorcerer"], CHARACTERS["Pirate"]],
        interaction=interaction,
    )
    player = game.state.players[0]
    assert len(game.prepare(player)) == 3


def test_confirmed_hand_limit_tracks_have_bounded_steps_and_caps():
    expected_caps = {
        "Monk": 10,
        "Sorcerer": 10,
        "Warrior": 10,
        "Pirate": 10,
        "Trader": 11,
    }
    for name, character in CHARACTERS.items():
        steps = SKILL_TRACKS[name]["hand_limit"]
        assert all(
            (step.value if isinstance(step, TrackStep) else step) in (0, 1, 2)
            for step in steps
        )
        total = sum(
            step.value if isinstance(step, TrackStep) else step for step in steps
        )
        assert character.starting_hand_limit + total == expected_caps[name]
        assert hand_limit_bonus(character, {"hand_limit": len(steps)}) == total


def test_reconstructed_skill_rewards_cover_majority_and_guarantee_trader():
    slots = [
        step
        for tracks in SKILL_TRACKS.values()
        for steps in tracks.values()
        for step in steps
        if (step.value if isinstance(step, TrackStep) else step) != 0
    ]
    rewards = [step for step in slots if isinstance(step, TrackStep) and step.reward]
    assert len(rewards) > len(slots) / 2
    for steps in SKILL_TRACKS["Trader"].values():
        assert all(
            isinstance(step, TrackStep) and step.reward in {"coin", "treasure"}
            for step in steps
        )


def test_skill_track_caps_and_requested_reward_landmarks():
    assert track_value(CHARACTERS["Warrior"], {"strike": 3}, "strike") == 4
    assert track_reward(CHARACTERS["Warrior"], "strike", 2) == "treasure"
    assert track_reward(CHARACTERS["Warrior"], "strike", 4) == "coin"
    assert track_value(CHARACTERS["Pirate"], {"sea": 3}, "sea") == 3
    assert track_value(CHARACTERS["Pirate"], {"reroll": 3}, "reroll") == 3
    assert track_value(CHARACTERS["Trader"], {"sneak": 3}, "sneak") == 4
    assert track_reward(CHARACTERS["Trader"], "sneak", 1) == "treasure"
    assert track_reward(CHARACTERS["Trader"], "sneak", 2) == "coin"
    assert track_reward(CHARACTERS["Trader"], "sneak", 3) == "treasure"
    assert track_value(CHARACTERS["Monk"], {"sneak": 3}, "sneak") == 3
    assert track_reward(CHARACTERS["Monk"], "sneak", 3) == "treasure"
    assert track_value(CHARACTERS["Sorcerer"], {"sneak": 3}, "sneak") == 3
    assert track_value(CHARACTERS["Sorcerer"], {"strike": 3}, "strike") == 3


def test_the_starting_player_is_an_even_coin_flip():
    counts = Counter(
        Game(
            encounters(),
            rng=random.Random(seed),
            characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
        ).state.current_player
        for seed in range(400)
    )
    assert set(counts) == {0, 1}
    assert abs(counts[0] - counts[1]) < 60


def test_every_character_can_level_up_after_all_eight_encounters():
    """A character with fewer than 8 slots would stop advancing before the end."""
    for name, tracks in SKILL_TRACKS.items():
        slots = sum(len(steps) for steps in tracks.values())
        assert slots == 12, f"{name} has {slots} available level-up spaces"
        assert (
            sum(1 for steps in tracks.values() if len(steps) > 1) >= 2
        ), f"{name} offers no real choice of track late in the game"


def test_shipped_deck_tiers_match_family_ladders_and_rebalanced_cards():
    cards = load_encounters(Path("data/encounters.json"))
    by_id = {card.id: card for card in cards}
    assert all(card.difficulty_tier == "" for card in cards)
    assert (
        by_id["mountain_of_darkness_1"].sneak_target,
        by_id["mountain_of_darkness_1"].steal_target,
        by_id["mountain_of_darkness_1"].strike_target,
    ) == (0, 5, 8)
    assert by_id["mountain_of_darkness_1"].blocked_method == "sneak"
    assert (
        by_id["rain_dragon_1"].victory_points,
        by_id["rain_dragon_1"].sneak_target,
        by_id["rain_dragon_1"].steal_target,
        by_id["rain_dragon_1"].strike_target,
    ) == (5, 15, 11, 16)
    assert by_id["rain_dragon_1"].rewards["strike"].treasure
    assert by_id["dragon_king"].is_sea
    assert by_id["dragon_king"].icons == 1


def test_only_sea_encounters_can_have_multiple_icons():
    cards = load_encounters(Path("data/encounters.json"))
    assert all(card.is_sea for card in cards if card.icons > 1)
    shogoro = next(card for card in cards if card.id == "shogoro")
    assert shogoro.icons == 1
    assert shogoro.victory_points == 1
    assert (shogoro.sneak_target, shogoro.steal_target, shogoro.strike_target) == (
        8,
        4,
        4,
    )


def test_same_type_dominance_check_is_clear():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "tools/check_dominance.py"],
        check=True,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    cards = load_encounters(Path("data/encounters.json"))
    assert {card.blocked_method for card in cards if card.blocked_method} == {
        "sneak",
        "steal",
        "strike",
    }


def test_encounter_validation_rejects_reward_on_blocked_method():
    invalid = Encounter(
        "Unreachable reward",
        1,
        4,
        4,
        4,
        encounter_type="location",
        blocked_method="strike",
        rewards={"strike": ChallengeReward(coins=1)},
    )
    with pytest.raises(ValueError, match="blocked method"):
        validate_encounters([invalid], expected_count=None)


def test_easy_tsukumogami_groups_trade_off_method_profiles():
    cards = [
        card
        for card in load_encounters(Path("data/encounters.json"))
        if card.encounter_type == "tsukumogami"
    ]
    assert len(cards) == 10
    assert {card.name for card in cards} == {
        "Jatai",
        "Seto Taisho",
        "Kasa Obaki",
        "Morinji no Kama",
        "Shogoro",
        "Hyotan Kozu",
        "Hahakigami",
        "Bakezori",
        "Biwa Bokuboku",
        "Chochin-Obake",
    }


def test_sorcerer_sequential_prepare_has_three_resolved_draws():
    game = Game(
        encounters(),
        characters=[CHARACTERS["Sorcerer"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    drawn = [
        game.prepare_one(player, "deck")
        for _ in range(player.character.prepare_draw_count)
    ]
    game.finish_prepare(player)
    assert len(drawn) == 3
    assert len(set(drawn)) == 3
    assert player.prepares == 1


def test_green_treasures_trigger_on_roll_and_success_conditions():
    announcements = []
    interaction = GameInteraction(
        announce=announcements.append,
        choose_discards=lambda player, count: player.hand[:count],
    )
    game = Game(
        encounters(),
        rules=RulesConfig(die_faces=(1,)),
        interaction=interaction,
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.treasures = [
        Treasure("green", passive_effect="roll_ones"),
        Treasure("green", passive_effect="three_color_success"),
        Treasure("green", passive_effect="low_hand_success"),
    ]
    hard = Encounter("Hard", 1, 3, 3, 3, encounter_type="type0")
    game.state.encounters[0] = hard
    player.hand[:3] = [Card("red", 1), Card("red", 2), Card("red", 3)]
    from dragonisles.bot import Decision

    assert game.attempt(
        player, hard, Decision("attempt", hard, tuple(player.hand[:3]), "strike")
    )
    assert player.coins == 0
    assert len(player.hand) >= 3
    assert any("rerolled" in message for message in announcements)


def test_green_treasure_draws_batch_before_discarding():
    discard_observations = []
    game = Game(
        encounters(),
        interaction=GameInteraction(
            choose_discards=lambda player, count: (
                discard_observations.append((len(player.hand), count))
                or player.hand[:count]
            )
        ),
        characters=[CHARACTERS["Warrior"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.hand[:] = [
        Card("red", rank) for rank in range(1, player.hand_limit + 1)
    ]
    player.treasures = [
        Treasure("green", passive_effect="three_color_draw"),
        Treasure("green", passive_effect="three_color_draw"),
    ]

    game._trigger_green_effect(player, "three_color_success")

    assert discard_observations == [(player.hand_limit + 2, 2)]
    assert len(player.hand) == player.hand_limit


def test_daruma_draws_batch_before_discarding():
    discard_observations = []
    game = Game(
        encounters(),
        interaction=GameInteraction(
            choose_discards=lambda player, count: (
                discard_observations.append((len(player.hand), count))
                or player.hand[:count]
            )
        ),
        characters=[CHARACTERS["Warrior"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.hand[:] = [
        Card("red", rank) for rank in range(1, player.hand_limit + 1)
    ]
    player.treasures = [
        Treasure("green", passive_effect="roll_ones_draw"),
        Treasure("green", passive_effect="roll_ones_draw"),
    ]

    game._reroll_green_ones(player, (1,))

    assert discard_observations == [(player.hand_limit + 2, 2)]
    assert len(player.hand) == player.hand_limit


def test_roll_time_green_treasures_announce_coins_draws_and_extra_dice():
    events = []
    game = Game(
        encounters(),
        interaction=GameInteraction(announce=events.append),
    )
    player = game.state.players[0]
    player.treasures = [
        Treasure("green", passive_effect="roll_ones_coin"),
        Treasure("green", passive_effect="roll_ones_draw"),
        Treasure("green", passive_effect="roll_ones_reroll_extra"),
    ]

    game._reroll_green_ones(player, (1, 3))

    assert f"{player.name}'s green treasure grants 1 coin." in events
    assert f"{player.name}'s green treasure drew 1 Adventure card." in events
    assert f"{player.name}'s green treasure added 1 die." in events


def test_each_roll_one_treasure_rerolls_current_ones_and_adds_one_die():
    game = Game(
        encounters(),
        interaction=GameInteraction(
            choose_discards=lambda player, count: player.hand[:count]
        ),
        characters=[CHARACTERS["Warrior"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.treasures = [
        Treasure("green", passive_effect="roll_ones_reroll_extra"),
        Treasure("green", passive_effect="roll_ones_reroll_extra"),
    ]
    choices = iter((1, 1, 2, 2, 2))
    game.rng.choice = lambda faces: next(choices)

    assert game._reroll_green_ones(player, (1, 3, 3)) == (2, 3, 3, 2, 2)


def test_each_copy_adds_a_die_when_the_initial_roll_had_a_one():
    game = Game(
        encounters(),
        interaction=GameInteraction(
            choose_discards=lambda player, count: player.hand[:count]
        ),
        characters=[CHARACTERS["Warrior"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.treasures = [
        Treasure("green", passive_effect="roll_ones_reroll_extra"),
        Treasure("green", passive_effect="roll_ones_reroll_extra"),
    ]
    choices = iter((1, 3, 1, 4))
    game.rng.choice = lambda faces: next(choices)

    result = game._reroll_green_ones(player, (1, 4))
    assert len(result) == 4
    assert sum(result) == 12


def test_lucky_mallet_respects_the_six_dice_limit():
    game = Game(
        encounters(),
        interaction=GameInteraction(
            choose_discards=lambda player, count: player.hand[:count]
        ),
    )
    player = game.state.players[0]
    player.treasures = [
        Treasure("green", passive_effect="roll_ones_reroll_extra"),
    ]
    game.rng.choice = lambda faces: 4

    result = game._reroll_green_ones(player, (1, 4, 4, 4, 4, 4))

    assert len(result) == 6


def test_roll_one_draw_and_coin_treasures_also_reroll_and_reward():
    game = Game(
        encounters(),
        rules=RulesConfig(die_faces=(2,)),
        characters=[CHARACTERS["Warrior"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.treasures = [
        Treasure("green", passive_effect="roll_ones_draw"),
        Treasure("green", passive_effect="roll_ones_coin"),
    ]
    hand_size = len(player.hand)

    assert game._reroll_green_ones(player, (1, 3)) == (2, 3)
    assert len(player.hand) == hand_size + 1
    assert player.coins == 1


def test_three_color_green_treasure_counts_each_wild_as_a_favourable_color():
    announcements: list[str] = []
    interaction = GameInteraction(announce=announcements.append)
    game = Game(
        encounters(),
        rules=RulesConfig(die_faces=(1,)),
        interaction=interaction,
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    player = game.state.players[0]
    player.treasures = [Treasure("green", passive_effect="three_color_success")]
    encounter = Encounter("Wild colours", 1, 3, 3, 3, encounter_type="type0")
    game.state.encounters[0] = encounter
    combo = (Card("red", 1), Card.wild_card(), Card.wild_card())

    from dragonisles.bot import Decision

    player.hand[:3] = combo
    assert game.attempt(
        player, encounter, Decision("attempt", encounter, combo, "strike")
    )
    assert player.coins == 1
    assert any("1 coin" in message for message in announcements)


def test_hand_limit_discards_immediately():
    interaction = GameInteraction(
        choose_discards=lambda player, count: player.hand[:count]
    )
    game = Game(encounters(), rng=random.Random(3), interaction=interaction)
    player = game.state.players[0]
    player.character = CHARACTERS["Monk"]
    player.hand.extend([Card("red", 1), Card("red", 2), Card("red", 3), Card("red", 4)])
    game.discard_down(player)
    assert len(player.hand) == player.hand_limit == 8


def test_coin_supply_exchanges_denominations_before_taking_from_opponent():
    game = Game(
        encounters(),
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    human, bot = game.state.players
    game._coin_supply = {1: 0, 5: 1, 10: 0}

    assert game.gain_coin(human)
    assert human.coins == 1
    assert bot.coins == 0
    assert game._coin_supply == {1: 4, 5: 0, 10: 0}

    game._coin_supply = {1: 0, 5: 0, 10: 0}
    bot.coins = 1
    assert game.gain_coin(human)
    assert human.coins == 2
    assert bot.coins == 0


def test_potion_supply_takes_from_opponent_then_recycles_used_tokens():
    game = Game(
        encounters(),
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    human, bot = game.state.players
    game._potion_supply = []
    game._used_potions = []
    bot.potions = [PotionToken(PURGE)]

    assert game.gain_potion(human)
    assert human.potions == [PotionToken(PURGE)]
    assert bot.potions == []

    human.potions.clear()
    game._used_potions = [PotionToken(PLUS_TWO)]
    assert game.gain_potion(human)
    assert human.potions == [PotionToken(PLUS_TWO)]


def test_card_validation_does_not_enforce_placeholder_composition():
    assert Card("violet", 99)


def test_failed_challenge_gives_potion_and_success_refills_encounter():
    rules = RulesConfig(
        die_faces=(1,),
        played_cards_on_success="discard",
    )
    cards = encounters()
    cards[0] = Encounter("Hard", 1, 3, 3, 3, encounter_type="type0")
    game = Game(cards, rules=rules, rng=random.Random(4))
    player = game.state.players[0]
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    target = cards[0]
    game.state.encounters[0] = target
    from dragonisles.bot import Decision

    assert not game.attempt(
        player, target, Decision("attempt", target, tuple(player.hand[:2]), "strike")
    )
    assert player.potions


def test_failed_challenge_keeps_played_cards_by_default():
    rules = RulesConfig(die_faces=(1,))
    game = Game(encounters(), rules=rules, rng=random.Random(4))
    player = game.state.players[0]
    target = Encounter("Hard", 1, 3, 3, 3, encounter_type="type0")
    game.state.encounters[0] = target
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    played = tuple(player.hand[:2])
    from dragonisles.bot import Decision

    assert not game.attempt(
        player, target, Decision("attempt", target, played, "strike")
    )
    assert all(card in player.hand for card in played)
    assert not any(card in game.state.deck.discard_pile for card in played)


def test_challenge_discards_played_cards_by_default():
    rules = RulesConfig(die_faces=(1,))
    game = Game(encounters(), rules=rules, rng=random.Random(4))
    player = game.state.players[0]
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    target = game.state.encounters[0]
    from dragonisles.bot import Decision

    before_discard = len(game.state.deck.discard_pile)
    game.attempt(
        player,
        target,
        Decision("attempt", target, tuple(player.hand[:2]), "strike"),
    )
    assert len(game.state.deck.discard_pile) == before_discard + 2


def test_success_takes_encounter_and_refills_row():
    rules = RulesConfig(die_faces=(1,))
    game = Game(encounters(), rules=rules, rng=random.Random(5))
    player = game.state.players[0]
    target = game.state.encounters[0]
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    cards = tuple(player.hand[:2])
    from dragonisles.bot import Decision

    assert game.attempt(player, target, Decision("attempt", target, cards, "strike"))
    assert target in player.encounters
    assert len(game.state.encounters) == 4


def test_success_awards_typed_method_reward():
    reward = ChallengeReward(coins=2, treasure=True)
    cards = [
        Encounter(
            "Reward", 1, 1, 1, 1, encounter_type="type0", rewards={"strike": reward}
        ),
        *encounters(3),
    ]
    game = Game(
        cards,
        rules=RulesConfig(die_faces=(1,)),
        rng=random.Random(7),
        interaction=GameInteraction(choose_treasure=lambda player, choices: choices[0]),
    )
    player = game.state.players[0]
    target = next(card for card in game.state.encounters if card.name == "Reward")
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    from dragonisles.bot import Decision

    assert game.attempt(
        player, target, Decision("attempt", target, tuple(player.hand[:2]), "strike")
    )
    assert player.coins == 2
    assert len(player.treasures) == 1
    assert player.treasures[0].is_orange
    assert player.treasures[0].victory_points == 1


def test_treasure_supply_is_rng_shuffled_and_replenishes():
    first = Game(
        encounters(12),
        rng=random.Random(12),
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(choose_treasure=lambda player, choices: choices[0]),
    )
    second = Game(
        encounters(12),
        rng=random.Random(12),
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(choose_treasure=lambda player, choices: choices[0]),
    )
    first_player = first.state.players[0]
    second_player = second.state.players[0]
    first.gain_treasure(first_player)
    second.gain_treasure(second_player)
    assert first_player.treasures == second_player.treasures
    first._treasure_supply.clear()
    first.gain_treasure(first_player)
    assert len(first_player.treasures) == 2


def test_treasure_reward_draws_two_and_discards_the_other():
    choices_seen = []
    game = Game(
        encounters(),
        rng=random.Random(12),
        interaction=GameInteraction(
            choose_treasure=lambda player, choices: (
                choices_seen.append(tuple(choices)) or choices[0]
            )
        ),
    )
    player = game.state.players[0]
    supply_before = len(game._treasure_supply)

    game.gain_treasure(player)

    assert len(choices_seen) == 1
    assert len(choices_seen[0]) == 2
    assert len(game._treasure_supply) == supply_before - 2
    assert player.treasures == [choices_seen[0][0]]
    assert game.used_treasures == [choices_seen[0][1]]


def test_bot_treasure_reward_chooses_without_pending_state():
    game = Game(encounters(), rng=random.Random(12))
    bot = game.state.players[1]

    game.gain_treasure(bot)

    assert len(bot.treasures) == 1
    assert game.pending_treasure_draw is None
    assert len(game.used_treasures) == 1


def test_human_treasure_reward_stages_and_resolves_keep_choice():
    game = Game(encounters(), rng=random.Random(12))
    player = game.state.players[0]

    game.gain_treasure(player)

    assert game.pending_treasure_draw is not None
    choices = game.pending_treasure_draw.treasures
    game.resolve_treasure_draw(choices[1])

    assert player.treasures == [choices[1]]
    assert game.used_treasures == [choices[0]]


def test_treasure_reward_refills_from_spent_treasures_for_second_choice():
    game = Game(encounters(), rng=random.Random(12))
    player = game.state.players[0]
    first, second, third = default_treasure_supply()[:3]
    game._treasure_supply[:] = [first]
    game._used_treasures[:] = [second, third]
    game.interaction = GameInteraction(
        choose_treasure=lambda player, choices: choices[0]
    )

    game.gain_treasure(player)

    assert len(player.treasures) == 1
    assert len(game._treasure_supply) == 1
    assert len(game.used_treasures) == 1


def test_treasure_supply_has_requested_composition():
    supply = default_treasure_supply()
    oranges = [treasure for treasure in supply if treasure.is_orange]
    greens = [treasure for treasure in supply if treasure.is_green]

    assert len(supply) == 45
    assert len(oranges) == 15
    assert len(greens) == 30
    assert Counter(treasure.encounter_type for treasure in oranges) == {
        "dragon": 3,
        "oni": 3,
        "bakemono": 3,
        "tsukumogami": 3,
        "location": 3,
    }
    assert Counter(treasure.passive_effect for treasure in greens) == {
        effect: 3
        for effect in (
            "roll_ones_reroll_extra",
            "roll_ones_draw",
            "roll_ones_coin",
            "low_hand_coin",
            "sneak_draw",
            "steal_draw",
            "strike_draw",
            "low_hand_draw",
            "three_color_coin",
            "three_color_draw",
        )
    }
    assert {treasure.display_name for treasure in greens} == {
        "Lucky Mallet",
        "Daruma",
        "Omamori",
        "Dotakubell",
        "Mirror",
        "Jewel",
        "Katana",
        "Magatama Bead",
        "Biwa",
        "Inuharaku",
    }


def test_monk_uses_potion_and_draws_one_card():
    interaction = GameInteraction(
        choose_discards=lambda player, count: player.hand[:count]
    )
    game = Game(
        encounters(),
        rng=random.Random(8),
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
        interaction=interaction,
    )
    player = game.state.players[0]
    player.hand.pop()
    potion = PotionToken(DRAW_TWO)
    player.potions.append(potion)
    plus_two = PotionToken(PLUS_TWO)
    player.potions.append(plus_two)
    before = len(player.hand)
    with pytest.raises(ValueError, match=r"\+2"):
        game.use_potion(player, plus_two)
    game.use_potion(player, potion)
    assert len(player.hand) == before + 3


def test_plus_two_potion_modifies_challenge_roll():
    prompts: list[tuple[int, int]] = []
    interaction = GameInteraction(
        choose_plus_two=lambda player, total, target: (
            prompts.append((total, target)) or True
        )
    )
    rules = RulesConfig(die_faces=(2,))
    cards = [
        Encounter("Hard", 1, 5, 5, 5, encounter_type="type0"),
        *encounters(3),
    ]
    game = Game(
        cards,
        rules=rules,
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
        interaction=interaction,
    )
    player = game.state.players[0]
    target = next(card for card in game.state.encounters if card.name == "Hard")
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    potion = PotionToken(PLUS_TWO)
    player.potions.append(potion)
    from dragonisles.bot import Decision

    assert game.attempt(
        player,
        target,
        Decision("attempt", target, tuple(player.hand[:2]), "strike"),
    )
    assert prompts == [(4, 5)]
    assert potion not in player.potions


def test_multiple_plus_two_potions_can_rescue_one_challenge():
    prompts: list[tuple[int, int]] = []
    game = Game(
        [Encounter("Hard", 1, 8, 8, 8), *encounters(3)],
        rules=RulesConfig(die_faces=(2,)),
        interaction=GameInteraction(
            choose_plus_two=lambda player, total, required: (
                prompts.append((total, required)) or True
            )
        ),
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
    )
    player = game.state.players[0]
    target_card = next(card for card in game.state.encounters if card.name == "Hard")
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    player.potions.extend([PotionToken(PLUS_TWO), PotionToken(PLUS_TWO)])
    from dragonisles.bot import Decision

    assert game.attempt(
        player,
        target_card,
        Decision("attempt", target_card, tuple(player.hand[:2]), "strike"),
    )
    assert prompts == [(4, 8), (6, 8)]
    assert not any(potion.kind == PLUS_TWO for potion in player.potions)


@pytest.mark.parametrize("target", [5, 6])
def test_plus_two_rescues_one_or_two_point_shortfall(target):
    prompts: list[tuple[int, int]] = []
    game = Game(
        [Encounter("Hard", 1, target, target, target), *encounters(3)],
        rules=RulesConfig(die_faces=(2,)),
        interaction=GameInteraction(
            choose_plus_two=lambda player, total, required: (
                prompts.append((total, required)) or True
            )
        ),
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
    )
    player = game.state.players[0]
    target_card = next(card for card in game.state.encounters if card.name == "Hard")
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    potion = PotionToken(PLUS_TWO)
    player.potions.append(potion)
    from dragonisles.bot import Decision

    assert game.attempt(
        player,
        target_card,
        Decision("attempt", target_card, tuple(player.hand[:2]), "strike"),
    )
    assert prompts == [(4, target)]


@pytest.mark.parametrize(
    ("target", "expected_prompts", "potion_remaining"),
    [(4, [], True), (7, [(4, 7)], False)],
)
def test_plus_two_is_offered_only_when_the_roll_is_short(
    target, expected_prompts, potion_remaining
):
    prompts: list[tuple[int, int]] = []
    game = Game(
        [Encounter("Hard", 1, target, target, target), *encounters(3)],
        rules=RulesConfig(die_faces=(2,)),
        interaction=GameInteraction(
            choose_plus_two=lambda player, total, required: (
                prompts.append((total, required)) or True
            )
        ),
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
    )
    player = game.state.players[0]
    target_card = next(card for card in game.state.encounters if card.name == "Hard")
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    potion = PotionToken(PLUS_TWO)
    player.potions.append(potion)
    from dragonisles.bot import Decision

    game.attempt(
        player,
        target_card,
        Decision("attempt", target_card, tuple(player.hand[:2]), "strike"),
    )
    assert prompts == expected_prompts
    if potion_remaining:
        assert potion in player.potions
    else:
        assert potion in game.used_potions


def test_bot_rescue_uses_policy_without_human_plus_two_callback():
    prompted = []
    game = Game(
        [Encounter("Hard", 1, 5, 5, 5), *encounters(3)],
        rules=RulesConfig(die_faces=(2,)),
        interaction=GameInteraction(
            choose_plus_two=lambda *args: prompted.append(args) or True
        ),
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
    )
    bot = game.state.players[1]
    target = next(card for card in game.state.encounters if card.name == "Hard")
    bot.hand[:2] = [Card("red", 1), Card("red", 2)]
    bot.potions.append(PotionToken(PLUS_TWO))
    from dragonisles.bot import Decision

    game.attempt(
        bot, target, Decision("attempt", target, tuple(bot.hand[:2]), "strike")
    )
    assert prompted == []


def test_reroll_replaces_selected_dice_and_can_lower_a_roll():
    class ChoiceRng(random.Random):
        def __init__(self):
            super().__init__(0)
            self.values = iter([4, 4, 1])

        def choice(self, sequence):
            return next(self.values)

    shown = []
    game = Game(
        [Encounter("Hard", 1, 10, 10, 10)] * 6,
        rules=RulesConfig(die_faces=(1, 4)),
        rng=ChoiceRng(),
        characters=[CHARACTERS["Sorcerer"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(
            choose_rerolls=lambda player, rolls, limit: (0,),
            show_roll=lambda player, rolls, bonus, total: shown.append(rolls),
        ),
    )
    player = game.state.players[0]
    player.skill_levels["reroll"] = 1
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    target = game.state.encounters[0]
    from dragonisles.bot import Decision

    game.attempt(
        player, target, Decision("attempt", target, tuple(player.hand[:2]), "strike")
    )
    assert shown == [(4, 4), (1, 4)]


def test_reroll_selection_cannot_exceed_level():
    game = Game(
        [Encounter("Hard", 1, 10, 10, 10)] * 6,
        rules=RulesConfig(die_faces=(2,)),
        characters=[CHARACTERS["Sorcerer"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(
            choose_rerolls=lambda player, rolls, limit: (0, 1, 2)
        ),
    )
    player = game.state.players[0]
    player.skill_levels["reroll"] = 2
    player.hand[:3] = [Card("red", 1), Card("red", 2), Card("red", 3)]
    target = game.state.encounters[0]
    from dragonisles.bot import Decision

    with pytest.raises(ValueError, match="invalid reroll selection"):
        game.attempt(
            player,
            target,
            Decision("attempt", target, tuple(player.hand[:3]), "strike"),
        )


def test_bot_skips_reroll_on_an_already_successful_roll():
    game = Game(
        [Encounter("Easy", 1, 4, 4, 4)] * 6,
        rules=RulesConfig(die_faces=(2,)),
        characters=[CHARACTERS["Sorcerer"], CHARACTERS["Pirate"]],
    )
    bot = game.state.players[1]
    bot.skill_levels["reroll"] = 1
    context = game.decision_context(bot)
    assert (
        game.bot_policy.choose_reroll_indices(
            context, game.state.encounters[0], "strike", (2, 2)
        )
        == ()
    )
    assert reroll_count(CHARACTERS["Pirate"], {"reroll": 2}) == 2


def test_fully_levelled_reroll_track_is_not_offered():
    offered = []
    game = Game(
        [Encounter("Target", 1, 1, 1, 1)] * 6,
        characters=[CHARACTERS["Sorcerer"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(
            choose_track=lambda player, tracks: offered.append(tracks) or tracks[0]
        ),
    )
    player = game.state.players[0]
    player.skill_levels["reroll"] = 5
    game.advance_experience(player)
    assert "reroll" not in offered[0]


def test_blocked_method_is_rejected_and_bot_does_not_choose_it():
    blocked = Encounter(
        "Kamaitachi",
        2,
        8,
        8,
        8,
        blocked_method="strike",
    )
    game = Game(
        [blocked, *encounters(5)],
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(
            choose_discards=lambda player, count: player.hand[:count]
        ),
    )
    game.state.encounters[0] = blocked
    human = game.state.players[0]
    human.hand[:2] = [Card("red", 1), Card("red", 2)]
    from dragonisles.bot import Decision

    with pytest.raises(ValueError, match="strike is blocked"):
        game.attempt(
            human,
            blocked,
            Decision("attempt", blocked, tuple(human.hand[:2]), "strike"),
        )
    bot = game.state.players[1]
    bot.hand[:2] = [Card("red", 1), Card("red", 2)]
    decision = game.bot_policy.choose(game.decision_context(bot))
    if decision.encounter is blocked:
        assert decision.method != "strike"


def test_skill_track_reward_is_granted_once_at_level():
    interaction = GameInteraction(
        choose_track=lambda player, tracks: "strike",
        choose_treasure_card=lambda player, cards: cards[0],
    )
    game = Game(
        encounters(8),
        characters=[CHARACTERS["Trader"], CHARACTERS["Monk"]],
        interaction=interaction,
    )
    player = game.state.players[0]
    game.advance_experience(player)
    assert player.skill_levels["strike"] == 1
    assert len(player.treasures) == 1
    game.advance_experience(player)
    assert len(player.treasures) == 1


def test_draw_two_potion_draws_two_cards():
    shown = []
    game = Game(
        encounters(),
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
        interaction=GameInteraction(
            show_cards=lambda player, label, cards: shown.append((label, cards))
        ),
    )
    player = game.state.players[0]
    potion = PotionToken(DRAW_TWO)
    player.potions.append(potion)
    before = len(player.hand)
    game.use_potion(player, potion)
    assert len(player.hand) == before + 2
    assert [label for label, cards in shown] == ["drew"]
    assert len(shown[0][1]) == 2


def test_purge_potion_draws_and_refills_encounter_row():
    shown = []
    rows = []
    game = Game(
        encounters(12),
        characters=[CHARACTERS["Pirate"], CHARACTERS["Monk"]],
        interaction=GameInteraction(
            show_cards=lambda player, label, cards: shown.append((label, cards)),
            show_encounters=lambda encounters: rows.append(tuple(encounters)),
        ),
    )
    player = game.state.players[0]
    potion = PotionToken(PURGE)
    player.potions.append(potion)
    before = len(player.hand)
    game.use_potion(player, potion)
    assert len(player.hand) == before + 1
    assert len(game.state.encounters) == 4
    assert len(shown[0][1]) == 1
    assert len(rows) == 1


def test_trader_draws_three_and_keeps_one():
    shown = []
    interaction = GameInteraction(
        choose_treasure_card=lambda player, cards: cards[0],
        show_cards=lambda player, label, cards: shown.append((label, cards)),
    )
    game = Game(
        encounters(),
        characters=[CHARACTERS["Trader"], CHARACTERS["Monk"]],
        interaction=interaction,
    )
    player = game.state.players[0]
    treasure = Treasure("orange", victory_points=2)
    before = len(player.hand)
    game.gain_treasure(player, treasure, keep_card=None)
    assert len(player.hand) == before + 1
    assert len(game.state.deck.discard_pile) >= 1
    assert len(shown) == 1
    assert shown[0][0] == "drew for Trader"
    assert len(shown[0][1]) == 3


def test_eighth_success_ends_game_immediately():
    rules = RulesConfig(die_faces=(1,))
    game = Game(encounters(12), rules=rules, rng=random.Random(6))
    player = game.state.players[0]
    player.encounters.extend(encounters(12)[:7])
    target = game.state.encounters[0]
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    from dragonisles.bot import Decision

    assert game.attempt(
        player, target, Decision("attempt", target, tuple(player.hand[:2]), "strike")
    )
    assert game.state.game_over
    assert game.state.winner is player


def test_eighth_success_skips_rewards_experience_and_trophy():
    rules = RulesConfig(die_faces=(1,))
    game = Game(encounters(12), rules=rules, rng=random.Random(6))
    player = game.state.players[0]
    player.encounters.extend(encounters(12)[:7])
    player.skill_progress.append(1)
    target = Encounter(
        "Final treasure",
        3,
        1,
        1,
        1,
        rewards={"strike": ChallengeReward(treasure=True, coins=2)},
        automatic_treasure=True,
    )
    game.state.encounters[0] = target
    player.hand[:2] = [Card("red", 1), Card("red", 2)]
    from dragonisles.bot import Decision

    assert game.attempt(
        player, target, Decision("attempt", target, tuple(player.hand[:2]), "strike")
    )
    assert game.state.game_over
    assert len(player.encounters) == 8
    assert player.treasures == []
    assert player.coins == 0
    assert len(player.skill_progress) == 1
    assert not game.state.trophy_events
    assert game.pending_treasure_draw is None
    assert game.pending_trader_draw is None


def test_seventh_encounter_still_advances_experience():
    game = Game(encounters(12), rng=random.Random(6))
    player = game.state.players[0]
    player.encounters.extend(encounters(12)[:7])

    game.complete_experience(player)

    assert not game.state.game_over
    assert len(player.skill_progress) == 1


def test_eighth_encounter_ends_game_but_highest_vp_player_wins():
    rules = RulesConfig(die_faces=(1,))
    human = Player("Human", CHARACTERS["Warrior"])
    bot = Player("Bot", CHARACTERS["Monk"], is_bot=True)
    game = Game(
        encounters(12),
        rules=rules,
        players=[human, bot],
    )
    human.encounters.extend(encounters(12)[:8])
    bot.encounters.extend(Encounter(f"High {index}", 5, 1, 1, 1) for index in range(8))

    game.complete_experience(human)

    assert game.state.game_over
    assert game.state.winner is bot


def test_eighth_encounter_tie_uses_first_player_as_winner_representative():
    game = Game(
        encounters(12),
        players=[
            Player("Human", CHARACTERS["Warrior"]),
            Player("Bot", CHARACTERS["Monk"], is_bot=True),
        ],
    )
    for player in game.state.players:
        player.encounters.extend(
            Encounter(f"Done {index}", 1, 1, 1, 1) for index in range(8)
        )

    game.complete_experience(game.state.players[0])

    assert game.state.winner is game.state.players[0]


def test_coin_percentage_uses_total_vp_as_its_denominator():
    more_coin_points = ScoreBreakdown(14, 0, 0, 6, 20)
    fewer_coin_points = ScoreBreakdown(10, 0, 0, 5, 15)

    assert more_coin_points.coin_percentage == 0.3
    assert fewer_coin_points.coin_percentage == 5 / 15
    assert more_coin_points.coin_percentage < fewer_coin_points.coin_percentage


def test_pirate_coin_multiplier_counts_in_coin_percentage_tiebreaker():
    game = Game(
        encounters(12),
        players=[
            Player("Pirate", CHARACTERS["Pirate"]),
            Player("Warrior", CHARACTERS["Warrior"], is_bot=True),
        ],
    )
    pirate, warrior = game.state.players
    pirate.encounters.extend(
        Encounter(f"Pirate {index}", 2, 1, 1, 1) for index in range(7)
    )
    pirate.encounters.append(Encounter("Pirate last", 0, 1, 1, 1))
    warrior.encounters.extend(
        Encounter(f"Warrior {index}", 2, 1, 1, 1) for index in range(7)
    )
    warrior.encounters.append(Encounter("Warrior last", 1, 1, 1, 1))
    pirate.coins = 3
    warrior.coins = 5

    game.complete_experience(pirate)

    assert game.score(pirate).total == game.score(warrior).total == 20
    assert pirate.coins < warrior.coins
    assert game.score(pirate).coin_points > game.score(warrior).coin_points
    assert game.state.winner is pirate


def test_reconstructed_encounter_dataset_is_validated():
    encounters = load_encounters(Path(__file__).parents[1] / "data" / "encounters.json")
    assert len(encounters) == 50
    assert sum(encounter.blocked_method is not None for encounter in encounters) == 10
    assert all(
        encounter.blocked_method is None
        or encounter.target_for(encounter.blocked_method) == 0
        for encounter in encounters
    )
    assert {encounter.encounter_type for encounter in encounters} == {
        "dragon",
        "oni",
        "bakemono",
        "tsukumogami",
        "location",
    }


def test_runtime_validation_accepts_equal_method_targets():
    validate_encounters(
        [Encounter("Hand-authored", 2, 5, 5, 5, encounter_type="location")],
        expected_count=None,
    )


def test_encounter_loader_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "encounters.json"
    path.write_text(
        """
        [
          {"id": "same", "name": "A", "victory_points": 1, "strike_target": 1, "sneak_target": 1, "steal_target": 1, "encounter_type": "location"},
          {"id": "same", "name": "A different card", "victory_points": 1, "strike_target": 2, "sneak_target": 2, "steal_target": 2, "encounter_type": "location"}
        ]
        """
    )
    with pytest.raises(ValueError, match="duplicate encounter id"):
        load_encounters(path)


def test_encounter_loader_rejects_tier_mismatch(tmp_path):
    path = tmp_path / "encounters.json"
    path.write_text(
        """
        [
          {
            "id": "easy_card",
            "name": "Easy card",
            "victory_points": 1,
            "strike_target": 1,
            "sneak_target": 1,
            "steal_target": 1,
            "encounter_type": "location",
            "difficulty_tier": "moderate"
          }
        ]
        """
    )
    with pytest.raises(ValueError, match="difficulty tier"):
        load_encounters(path, expected_count=None)


def test_encounter_without_flavor_is_supported(tmp_path):
    location = tmp_path / "location.json"
    location.write_text(
        """
        [
          {
            "id": "location",
            "name": "A Place",
            "victory_points": 1,
            "strike_target": 1,
            "sneak_target": 1,
            "steal_target": 1,
            "encounter_type": "location"
          }
        ]
        """
    )
    assert load_encounters(location, expected_count=None)[0].name == "A Place"

    creature = location.read_text().replace('"location"', '"oni"')
    creature_path = tmp_path / "creature.json"
    creature_path.write_text(creature)
    assert load_encounters(creature_path, expected_count=None)[0].name == "A Place"


def test_encounter_loader_rejects_wrong_card_count(tmp_path):
    path = tmp_path / "encounters.json"
    path.write_text("[]")
    with pytest.raises(ValueError, match="expected 50 encounters"):
        load_encounters(path)
