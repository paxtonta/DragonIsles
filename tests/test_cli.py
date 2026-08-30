from dragonisles.bot import challenge_probability
from dragonisles.cards import Card
from dragonisles.cli import (
    _human_action,
    _human_action_once,
    _inspect_command,
    _make_interaction,
    _print_state,
    _reward_text,
    run_cli,
)
from dragonisles.characters import CHARACTERS
from dragonisles.encounters import ChallengeReward, Encounter
from dragonisles.engine import Game, GameInteraction, Player, RulesConfig
from dragonisles.dice import probability_at_least
from dragonisles.potions import DRAW_TWO, PotionToken
from dragonisles.treasures import Treasure


def test_reward_text_omits_zero_value_reward_parts():
    assert _reward_text(ChallengeReward(treasure=True)) == "treasure"
    assert _reward_text(ChallengeReward(coins=1)) == "1 coin"


def test_success_odds_stay_internal_to_the_bot(monkeypatch, capsys):
    """The human must never see the odds, but the bot still calculates them."""
    game = Game(
        [Encounter("Target", 1, 6, 6, 6)] * 6,
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    human = game.state.players[0]
    human.hand = [Card("red", 1), Card("blue", 2)]
    human.skill_levels["sneak"] = 1
    inputs = iter(["sneak", "1 2"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(inputs))

    _human_action_once(game, human, "1")

    output = capsys.readouterr().out
    assert "probability" not in output.lower()
    assert "%" not in output

    without_bonus = probability_at_least(2, 6)
    with_bonus = challenge_probability(
        game.decision_context(human),
        Encounter("Target", 1, 6, 6, 6),
        "sneak",
        2,
    )
    assert with_bonus > without_bonus


def test_encounter_display_shows_automatic_treasure(capsys):
    game = Game([Encounter("Target", 1, 5, 5, 5)] * 6)
    game.state.encounters[0] = Encounter(
        "Ryujin",
        7,
        21,
        19,
        14,
        automatic_treasure=True,
    )

    _print_state(game, game.state.players[0])

    assert "auto:treasure" in capsys.readouterr().out


def test_inspect_shows_encounter_mechanics(capsys):
    encounter = Encounter(
        "Shogoro",
        1,
        4,
        6,
        6,
    )
    game = Game([encounter] * 6)

    _print_state(game, game.state.players[0])
    board_output = capsys.readouterr().out
    assert "VP 1 | Icons 1" in board_output

    assert _inspect_command(game, "look 1")
    inspect_output = capsys.readouterr().out
    assert "VP 1 | Icons 1" in inspect_output


def test_inspect_invalid_arguments_are_free_and_guided(capsys):
    game = Game([Encounter("Target", 1, 5, 5, 5)] * 6)

    assert _inspect_command(game, "look")
    assert _inspect_command(game, "l nope")
    assert _inspect_command(game, "look 99")

    output = capsys.readouterr().out
    assert "Usage: look" in output
    assert "numeric encounter number" in output
    assert "from 1 to 4" in output


def test_encounter_display_shows_blocked_method(capsys):
    game = Game([Encounter("Target", 1, 5, 5, 5)] * 6)
    game.state.encounters[0] = Encounter(
        "Kamaitachi",
        2,
        8,
        7,
        9,
        blocked_method="strike",
    )

    _print_state(game, game.state.players[0])

    output = capsys.readouterr().out
    assert "Strike BLOCKED" in output


def test_track_menu_shows_full_ladders_and_progress(monkeypatch, capsys):
    interaction = _make_interaction()
    player = Game(
        [Encounter("Target", 1, 5, 5, 5)] * 6,
        characters=[CHARACTERS["Trader"], CHARACTERS["Monk"]],
    ).state.players[0]
    player.skill_levels["strike"] = 1
    monkeypatch.setattr("builtins.input", lambda prompt: "1")

    assert interaction.choose_track(player, ("strike",)) == "strike"

    output = capsys.readouterr().out
    assert "strike [1/3" in output
    assert "✓1:+1" in output
    assert ">2:+2" in output
    assert "·3:+3" in output
    assert "✓1:+1/treasure" in output


def test_status_shows_current_trophy_holders(capsys):
    game = Game(
        [Encounter("Target", 1, 5, 5, 5)] * 6,
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    human, bot = game.state.players
    human.encounters.extend(
        Encounter(f"Dragon {index}", 1, 1, 1, 1, encounter_type="dragon")
        for index in range(1)
    )
    bot.encounters.extend(
        Encounter(f"{kind} {index}", 1, 1, 1, 1, encounter_type=kind)
        for index, kind in enumerate(("oni", "bakemono", "tsukumogami", "location"))
    )
    game.state.trophy_events.extend(
        [
            (0, "dragon", 1),
            (1, "oni", 1),
            (1, "bakemono", 1),
            (1, "tsukumogami", 1),
            (1, "location", 1),
        ]
    )

    _print_state(game, human)

    output = capsys.readouterr().out
    assert "dragon:Human" in output
    assert "oni:Bot" in output
    assert "all:none" in output


def test_cli_alternates_exactly_one_turn_for_each_start(monkeypatch):
    import dragonisles.cli as cli

    for starting_player in (0, 1):
        game = Game(
            [Encounter("Target", 1, 5, 5, 5)] * 6,
            characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
        )
        game.state.current_player = starting_player
        events = []

        def fake_human_action(game, human, action):
            events.append(human.name)
            if len(events) == 6:
                game.state.game_over = True
            return True

        def fake_bot_turn(game):
            events.append("Bot")
            if len(events) == 6:
                game.state.game_over = True

        monkeypatch.setattr(cli, "_human_action", fake_human_action)
        monkeypatch.setattr(cli, "_run_bot_turn", fake_bot_turn)
        monkeypatch.setattr(cli, "_make_interaction", lambda: GameInteraction())
        monkeypatch.setattr("builtins.input", lambda prompt: "p")
        cli.run_cli(game)

        expected = (
            ["Human", "Bot"] * 3 if starting_player == 0 else ["Bot", "Human"] * 3
        )
        assert events == expected


def test_encounter_display_shows_icon_count(capsys):
    game = Game([Encounter("Target", 1, 5, 5, 5)] * 6)
    game.state.encounters[0] = Encounter(
        "Two-icon Kasha",
        2,
        7,
        5,
        8,
        encounter_type="oni",
        icons=2,
        is_sea=True,
    )

    _print_state(game, game.state.players[0])

    assert "Icons 2" in capsys.readouterr().out


def test_cli_announces_highest_vp_winner_when_eighth_encounter_ends_game(capsys):
    game = Game(
        [Encounter("Target", 1, 1, 1, 1)] * 12,
        players=[
            Player("Human", CHARACTERS["Warrior"]),
            Player("Bot", CHARACTERS["Monk"], is_bot=True),
        ],
    )
    human, bot = game.state.players
    human.encounters.extend(
        Encounter(f"Done {index}", 1, 1, 1, 1) for index in range(8)
    )
    bot.encounters.extend(Encounter(f"High {index}", 5, 1, 1, 1) for index in range(8))
    game.complete_experience(human)

    run_cli(game)

    output = capsys.readouterr().out
    assert "Human: 8 VP" in output
    assert "Winner: Bot (40 VP)" in output


def test_cli_uses_coin_percentage_to_break_vp_ties(capsys):
    game = Game(
        [Encounter("Target", 1, 1, 1, 1)] * 12,
        players=[
            Player("Human", CHARACTERS["Warrior"]),
            Player("Bot", CHARACTERS["Warrior"], is_bot=True),
        ],
    )
    human, bot = game.state.players
    human.encounters.extend(
        Encounter(f"Human {index}", 2, 1, 1, 1) for index in range(7)
    )
    human.encounters.append(Encounter("Human last", 0, 1, 1, 1))
    bot.encounters.extend(Encounter(f"Bot {index}", 2, 1, 1, 1) for index in range(7))
    bot.encounters.append(Encounter("Bot last", 1, 1, 1, 1))
    human.coins = 6
    bot.coins = 5
    game.complete_experience(human)

    run_cli(game)

    assert "Winner: Human (20 VP)" in capsys.readouterr().out


def test_status_displays_both_players_public_treasures(capsys):
    game = Game(
        [Encounter("Target", 1, 5, 5, 5)] * 6,
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
    )
    human, bot = game.state.players
    human.treasures.append(Treasure("orange", victory_points=1, encounter_type="oni"))
    bot.treasures.append(Treasure("green", passive_effect="roll_ones"))

    _print_state(game, human)

    output = capsys.readouterr().out
    assert "Treasures: orange oni treasure — Worth 1 VP." in output
    assert "Bot" in output
    assert "green (reroll 1s and draw a card)" in output


def test_challenge_output_orders_roll_result_before_level_up(monkeypatch):
    events = []
    game = Game(
        [Encounter("Target", 1, 4, 4, 4)] * 6,
        rules=RulesConfig(die_faces=(2,)),
        characters=[CHARACTERS["Monk"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(
            choose_track=lambda player, tracks: (events.append("track") or tracks[0]),
            show_roll=lambda player, rolls, bonus, total: events.append("roll"),
            show_challenge_result=lambda player, success: events.append("result"),
        ),
    )
    human = game.state.players[0]
    human.hand[:2] = [Card("red", 1), Card("red", 2)]
    answers = iter(["strike", "1 2"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))

    _human_action(game, human, "1")

    assert events == ["roll", "result", "track"]


def test_illegal_human_combo_after_free_potion_reprompts_same_turn(monkeypatch):
    interaction = GameInteraction(
        choose_discards=lambda player, count: player.hand[:count]
    )
    game = Game(
        [Encounter("Target", 1, 5, 5, 5)] * 6,
        interaction=interaction,
    )
    human = game.state.players[0]
    human.character = CHARACTERS["Trader"]
    human.hand_limit_upgrade = 3
    human.hand[:2] = [Card("red", 1), Card("blue", 3)]
    selected_cards = tuple(human.hand[:2])
    human.potions.append(PotionToken(DRAW_TWO))
    answers = iter(["1", "1", "strike", "1 2", "p", "deck", "deck"])
    monkeypatch.setattr("builtins.input", lambda _prompt: next(answers))

    assert _human_action(game, human, "u") is True
    assert human.potions == []
    assert all(card in human.hand for card in selected_cards)
    assert human.encounters == []


def test_human_prepare_prompts_and_resolves_each_draw(monkeypatch, capsys):
    game = Game(
        [Encounter("Target", 1, 5, 5, 5)] * 6,
        characters=[CHARACTERS["Trader"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(
            choose_discards=lambda player, count: player.hand[:count]
        ),
    )
    human = game.state.players[0]
    first = Card("red", 1)
    second = Card("blue", 1)
    replacement = Card("green", 5)
    filler = Card("yellow", 6)
    game.state.market[:] = [first, second]
    game.state.deck.draw_pile[:] = [filler, replacement]
    answers = iter(["bad", "1", "2"])
    prompts = []
    monkeypatch.setattr(
        "builtins.input",
        lambda prompt: (prompts.append(prompt), next(answers))[1],
    )

    assert _human_action(game, human, "p") is True
    output = capsys.readouterr().out
    assert "Choose source for draw 1 of 2" in prompts[0]
    assert "Choose source for draw 1 of 2" in prompts[1]
    assert "Choose source for draw 2 of 2" in prompts[2]
    assert "Invalid source:" in output
    assert "Drew red 1." in output
    assert "Drew green 5." in output
