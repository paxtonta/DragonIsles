import http.client
import json
import random
import re
from http.server import ThreadingHTTPServer
import threading
from pathlib import Path

import pytest

from dragonisles.bot import Decision
from dragonisles.cards import Card
from dragonisles.characters import CHARACTERS, SKILL_TRACKS
from dragonisles.encounters import Encounter, load_encounters
from dragonisles.engine import ChallengeProgress, Player
from dragonisles.potions import DRAW_TWO, PLUS_TWO, PotionToken
from dragonisles.treasures import Treasure
from dragonisles.web import (
    HTML,
    Handler,
    WebSession,
    configure,
    serialize_card,
    serialize_ladders,
    serialize_treasure,
)


def _web_request(server, method, path, body=None, cookie=None):
    connection = http.client.HTTPConnection(*server.server_address)
    headers = {}
    if body is not None:
        headers["Content-Type"] = "application/json"
        body = json.dumps(body)
    if cookie is not None:
        headers["Cookie"] = cookie
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    data = response.read()
    connection.close()
    return response.status, response.getheaders(), json.loads(data or b"{}")


def _relative_luminance(color):
    channels = [int(color[index : index + 2], 16) / 255 for index in (1, 3, 5)]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4
        for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _contrast_ratio(first, second):
    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter = max(first_luminance, second_luminance)
    darker = min(first_luminance, second_luminance)
    return (lighter + 0.05) / (darker + 0.05)


def test_web_light_mode_colors_clear_contrast_floor_on_all_surfaces():
    backgrounds = ("#dbe5f0", "#ffffff", "#e7edf5", "#f4f7fb")
    selectors = (
        "suit-red",
        "suit-yellow",
        "suit-green",
        "suit-blue",
        "suit-purple",
        "treasure-orange",
        "treasure-green",
    )
    for selector in selectors:
        match = re.search(
            rf':root\[data-theme="light"\] \.{selector}\{{color:(#[0-9a-f]+)\}}',
            HTML,
        )
        assert match is not None
        color = match.group(1)
        assert (
            min(_contrast_ratio(color, background) for background in backgrounds) >= 3
        )


def test_web_state_exposes_board_and_public_state():
    session = WebSession()
    state = session.state()

    assert len(state["encounters"]) == 4
    assert len(state["hand"]) >= 2
    assert len(state["players"]) == 2
    assert all("score" in player for player in state["players"])
    assert all(
        player["hand_limit"]
        == next(
            game_player
            for game_player in session.game.state.players
            if game_player.name == player["name"]
        ).hand_limit
        for player in state["players"]
    )
    assert set(state["trophies"]) >= {"dragon", "oni", "all"}


def test_web_new_game_button_resets_the_session():
    assert "New game" in HTML
    session = WebSession()
    old_game = session.game
    old_encounters = old_game.state.encounters
    session.revision = 7
    session.pending = {"stale": True}
    session.pending_challenge = object()
    session.pending_prepare = {
        "player": session.human,
        "remaining": 1,
        "drawn": [],
    }
    session.pending_free_action_discard = session.human
    session.events.append("old game")
    session.action({"action": "new_game"})

    state = session.state()
    assert session.game is not old_game
    assert session.game.state.encounters is not old_encounters
    assert state["revision"] == 0
    assert state["turn"] in (1, 2)
    players = session.game.state.players
    assert "stale" not in session.pending
    assert (
        session.pending_challenge is None
        or session.pending_challenge.player in players
    )
    assert session.pending_prepare is None
    assert session.pending_bot_prepare is None or (
        session.pending_bot_prepare["player"] in players
    )
    assert session.pending_free_action_discard is None
    assert (
        session.game.pending_discard is None
        or session.game.pending_discard.player in players
    )
    assert (
        session.game.pending_treasure_draw is None
        or session.game.pending_treasure_draw.player in players
    )
    assert (
        session.game.pending_trader_draw is None
        or session.game.pending_trader_draw.player in players
    )
    assert "old game" not in state["events"]


def test_web_new_game_rebinds_interaction_callbacks_to_the_live_session():
    session = WebSession()
    lock = session.lock

    session.new_game()

    interaction = session.game.interaction
    for callback_name in (
        "choose_discards",
        "choose_treasure",
        "choose_treasure_card",
        "choose_track",
        "choose_plus_two",
        "choose_rerolls",
        "show_roll",
        "show_challenge_result",
    ):
        assert getattr(interaction, callback_name).__self__ is session
    assert interaction.announce.__self__ is session.events
    assert session.lock is lock


def test_web_new_game_skill_choice_uses_the_live_session_callback():
    session = WebSession()
    session.new_game()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Monk"]
    encounter = Encounter("New game skill", 1, 1, 1, 1, encounter_type="type0")
    session.pending_challenge = ChallengeProgress(
        human,
        encounter,
        Decision("attempt", encounter, (), "strike"),
        (4,),
        0,
        4,
        1,
        0,
    )

    track = session.state()["challenge"]["tracks"][0]
    session.action({"action": "skill", "track": track})

    assert human.skill_levels[track] == 1


def test_web_game_over_uses_highest_vp_player_as_winner():
    session = WebSession()
    human, bot = session.game.state.players
    human.encounters[:] = [Encounter(f"Done {index}", 1, 1, 1, 1) for index in range(8)]
    bot.encounters[:] = [Encounter(f"High {index}", 5, 1, 1, 1) for index in range(8)]
    session.game.state.game_over = True

    state = session.state()

    scores = {player["name"]: player["score"] for player in state["players"]}
    assert scores[bot.name] > scores[human.name]
    assert "winner" not in state
    assert "coin_points" in state["players"][0]
    assert "coinPercentage" in HTML
    assert "coinPercentage(p)===highCoin" in HTML


def test_web_game_over_uses_coin_percentage_to_break_vp_ties():
    session = WebSession()
    human, bot = session.game.state.players
    human.character = CHARACTERS["Warrior"]
    bot.character = CHARACTERS["Warrior"]
    human.encounters[:] = [
        Encounter(f"Human {index}", 2, 1, 1, 1) for index in range(7)
    ] + [Encounter("Human last", 0, 1, 1, 1)]
    bot.encounters[:] = [
        Encounter(f"Bot {index}", 2, 1, 1, 1) for index in range(7)
    ] + [Encounter("Bot last", 1, 1, 1, 1)]
    human.treasures.clear()
    bot.treasures.clear()
    session.game.state.trophy_events.clear()
    human.coins = 6
    bot.coins = (20 - 15) // bot.character.coin_multiplier
    session.game.state.game_over = True

    state = session.state()
    players = {player["name"]: player for player in state["players"]}

    assert players[human.name]["score"] == players[bot.name]["score"] == 20
    assert players[human.name]["coin_points"] > players[bot.name]["coin_points"]
    assert (
        players[human.name]["coin_points"] / 20 > players[bot.name]["coin_points"] / 20
    )


def test_game_over_html_hides_pending_choice_panels():
    assert "if(S.game_over||!t)" in HTML
    assert "if(S.game_over||!d)" in HTML
    assert "if(S&&S.game_over&&body.action!=='new_game')return;" in HTML
    assert "let actionDisabled=S.game_over?' disabled':'';" in HTML
    assert "S.game_over?'Game over'" in HTML
    assert "${S.game_over?'':` onclick=\"pick('${c.id}')\"`}" in HTML
    assert "__ID__" not in HTML


def test_live_encounter_markup_has_balanced_pick_attribute():
    assert "class=\"card encounter ${selected===c.id?'selected':''}\"" in HTML


def test_game_ui_shows_die_faces_without_a_reference_tab():
    assert "onclick=\"location.href='/reference'\"" not in HTML
    assert "Die faces: ${S.die_faces.join(', ')}" in HTML
    assert "die_faces" in WebSession().state()


def test_tavern_cards_are_public_and_not_repeated_in_the_trader_panel():
    state = WebSession().state()

    assert len(state["market"]) == 2
    assert "let market=S.market.map(cardHtml).join(', ');" in HTML
    assert (
        "<b>Tavern</b>: ${market}</div><div class=panel><b>Discard pile top</b>"
        in HTML
    )
    assert "Tavern cards available for Prepare afterward" not in HTML
    assert "let tavern=S.market.map(cardHtml).join(', ');" not in HTML


def test_web_public_state_hides_other_players_potion_types():
    session = WebSession()
    session.human.potions.append(PotionToken(PLUS_TWO))
    bot = session.game.state.players[1]
    bot.potions.append(PotionToken(PLUS_TWO))

    state = session.state()

    assert PLUS_TWO in state["players"][0]["potions"]
    assert state["players"][1]["potions"] == len(bot.potions)


def test_web_public_state_shows_discard_pile_top_card():
    session = WebSession()
    first = Card("red", 2)
    second = Card("blue", 6)
    session.game.state.deck.discard(first)

    state = session.state()

    assert state["discard_top"]["label"] == "2"
    assert state["discard_top"]["suit"] == "red"
    session.game.state.deck.discard(second)

    state = session.state()

    assert state["discard_top"]["label"] == "6"
    assert state["discard_top"]["suit"] == "blue"
    assert "Discard pile top" in HTML


def test_web_state_shows_only_active_challenge_cards():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    encounter = session.game.state.encounters[0]
    human.hand[:2] = [Card("red", 1), Card("red", 2)]
    method = next(
        method for method in ("strike", "sneak", "steal")
        if method != encounter.blocked_method
    )

    session.action(
        {
            "action": "attempt",
            "encounter": encounter.id,
            "method": method,
            "cards": [0, 1],
        }
    )

    challenge = session.state()["challenge"]
    assert [card["label"] for card in challenge["cards"]] == ["1", "2"]
    assert "Last challenge cards:" not in HTML
    assert "cards.map(cardHtml)" in HTML


def test_web_active_challenge_cards_are_not_persisted_after_turn():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    encounter = session.game.state.encounters[0]
    human.hand[:2] = [Card("red", 1), Card("red", 2)]
    method = next(
        method for method in ("strike", "sneak", "steal")
        if method != encounter.blocked_method
    )

    session.action(
        {
            "action": "attempt",
            "encounter": encounter.id,
            "method": method,
            "cards": [0, 1],
        }
    )
    session.action({"action": "resolve", "plus_two": False})

    state = session.state()
    challenge = state["challenge"]
    assert all("challenge_cards" not in player for player in state["players"])
    if challenge is not None and challenge["player"] == human.name:
        assert challenge["phase"] == "skill"


def test_web_card_and_treasure_labels_preserve_visual_colors():
    assert serialize_card(Card("blue", 2), 0) == {
        "index": 0,
        "label": "2",
        "suit": "blue",
        "rank": 2,
        "wild": False,
    }
    assert serialize_treasure(
        Treasure("orange", victory_points=1, encounter_type="oni")
    ) == {
        "label": "oni treasure",
        "color": "orange",
        "description": "Worth 1 VP.",
    }
    assert serialize_treasure(Treasure("green", passive_effect="roll_ones")) == {
        "label": "(reroll 1s and draw a card)",
        "color": "green",
        "description": "reroll 1s and draw a card",
    }
    assert serialize_treasure(
        Treasure("green", passive_effect="roll_ones_reroll_extra")
    )["description"] == (
        "Once per Challenge, when you roll a 1, reroll all 1s and roll 1 additional die."
    )


def test_web_ladders_show_cumulative_bonuses():
    player = Player("Sorcerer", CHARACTERS["Sorcerer"])
    ladders = serialize_ladders(player)
    assert [step["bonus"] for step in ladders["reroll"]["steps"]] == [1, 2, 3]


def test_web_options_uses_engine_legality_and_blocking():
    session = WebSession()
    encounter = session.state()["encounters"][0]
    options = session.options({"encounter": encounter["id"], "cards": []})

    assert set(options) == {"sneak", "steal", "strike"}
    assert all(not option["enabled"] for option in options.values())
    assert all(
        option["reason"] in {"no legal combination", "blocked method"}
        for option in options.values()
    )


def _force_human_turn(session):
    state = session.game.state
    state.current_player = state.players.index(session.human)


def test_web_prepare_stages_discard_between_human_draws():
    session = WebSession()
    _force_human_turn(session)
    session.pending_challenge = None
    human = session.human
    initial_turn = session.game.state.turn_number
    human.character = CHARACTERS["Warrior"]
    human.hand[:] = [
        Card("red", rank) for rank in range(1, human.hand_limit + 1)
    ]

    session.action({"action": "prepare_start"})
    session.action({"action": "prepare_source", "source": "deck"})

    assert session.game.pending_discard is not None
    assert session.pending_prepare["remaining"] == 1
    assert len(session.pending_prepare["drawn"]) == 1
    assert session.state()["prepare"]["remaining"] == 1
    assert session.game.state.players[session.game.state.current_player] is human

    session.action({"action": "discard", "cards": [0]})

    assert session.game.pending_discard is None
    assert session.pending_prepare["remaining"] == 1
    assert session.game.state.players[session.game.state.current_player] is human
    assert human.prepares == 0

    session.action({"action": "prepare_source", "source": "deck"})
    assert session.game.pending_discard is not None
    assert session.pending_prepare["remaining"] == 0

    session.action({"action": "discard", "cards": [0]})

    assert session.pending_prepare is None
    assert human.prepares == 1
    assert session.game.state.turn_number > initial_turn


def test_web_bot_prepare_stages_one_discard_per_draw():
    session = WebSession()
    bot = session.game.state.players[1]
    initial_prepares = bot.prepares
    session.pending_challenge = None
    session.pending_bot_prepare = None
    session.game.pending_discard = None
    bot.character = CHARACTERS["Warrior"]
    bot.hand[:] = [Card("red", rank) for rank in range(1, bot.hand_limit + 1)]
    session.game.state.current_player = 1
    session.game.bot_policy.choose = lambda context: Decision("prepare")

    session._run_bots()

    draw_count = bot.character.prepare_draw_count
    assert session.pending_bot_prepare == {"player": bot, "remaining": draw_count - 1}
    assert session.game.pending_discard is not None

    for remaining in range(draw_count - 1, 0, -1):
        session.action({"action": "continue_bot_discard"})
        assert session.game.pending_discard is not None
        assert session.pending_bot_prepare == {
            "player": bot,
            "remaining": remaining - 1,
        }

    session.action({"action": "continue_bot_discard"})

    assert session.game.pending_discard is None
    assert session.pending_bot_prepare is None
    assert bot.prepares == initial_prepares + 1
    assert (
        session.game.state.players[session.game.state.current_player]
        is session.human
    )


def test_web_challenge_pauses_for_rerolls_plus_two_and_skill_choice():
    """The browser must decide rerolls and the +2 after seeing the dice."""
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Sorcerer"]
    human.skill_levels["reroll"] = 1
    encounter = Encounter("Test", 1, 3, 3, 3, encounter_type="type0")
    session.game.state.encounters[0] = encounter
    human.hand[:2] = [Card("red", 4), Card("red", 5)]

    session.action(
        {
            "action": "attempt",
            "encounter": encounter.id,
            "method": "strike",
            "cards": [0, 1],
        }
    )
    challenge = session.state()["challenge"]
    assert challenge["phase"] == "reroll"
    assert len(challenge["rolls"]) == 2
    assert challenge["target"] == 3

    session.action({"action": "reroll", "indices": [0]})
    challenge = session.state()["challenge"]
    assert challenge["phase"] == "resolve"
    assert challenge["rerolls_used"] is True

    session.action({"action": "resolve", "plus_two": False})
    state = session.state()
    assert (
        state["challenge"] is None
        or state["challenge"]["phase"] == "skill"
        or state["challenge"]["player_is_bot"]
    )


def test_web_prepare_offers_each_draw_source_in_turn():
    session = WebSession()
    _force_human_turn(session)
    before = len(session.human.hand)

    session.action({"action": "prepare_start"})
    prepare = session.state()["prepare"]
    assert prepare["remaining"] == session.game.prepare_draw_count(session.human)

    session.action({"action": "prepare_source", "source": "deck"})
    remaining = session.state()["prepare"]
    assert remaining is None or remaining["remaining"] == prepare["remaining"] - 1
    assert len(session.human.hand) >= before


def test_prepare_can_be_cancelled_until_the_first_card_is_drawn():
    """A misclicked Prepare must be recoverable while nothing has happened."""
    session = WebSession()
    _force_human_turn(session)
    before = len(session.human.hand)

    session.action({"action": "prepare_start"})
    session.action({"action": "prepare_cancel"})
    state = session.state()
    assert state["prepare"] is None
    assert state["human_turn"] is True
    assert len(session.human.hand) == before

    session.action({"action": "prepare_start"})
    session.action({"action": "prepare_source", "source": "deck"})
    if session.state()["prepare"] is not None:
        with pytest.raises(ValueError, match="cannot be cancelled"):
            session.action({"action": "prepare_cancel"})


def test_trader_treasure_stages_its_keep_choice_in_the_browser():
    """The Trader's keep-1-of-3 draw must be a browser choice, not an error."""
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Trader"]
    before = len(human.hand)

    session.game.gain_treasure(human)
    treasure = session.state()["treasure"]
    assert treasure is not None
    assert len(treasure["treasures"]) == 2
    assert session.state()["trader"] is None

    session.action({"action": "treasure_keep", "treasure": 1})
    trader = session.state()["trader"]
    assert trader is not None
    assert len(trader["cards"]) == human.character.trader_draw_count
    assert len(human.hand) == before

    session.action({"action": "trader_keep", "card": 1})
    assert session.state()["trader"] is None
    assert len(human.hand) == min(before + 1, human.hand_limit)


def test_browser_lets_human_choose_hand_limit_discards():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.hand.extend(
        [
            Card("red", 1),
            Card("blue", 2),
            Card("green", 3),
            Card("yellow", 4),
            Card("purple", 5),
        ]
    )

    count = len(human.hand) - human.hand_limit
    session.game.discard_down(human)
    assert session.state()["discard"] == {
        "count": count,
        "player": "Human",
        "player_is_bot": False,
    }
    original_hand = list(human.hand)
    discarded = []
    for _ in range(count):
        card = human.hand[-1]
        discarded.append(card)
        session.action({"action": "discard", "cards": [len(human.hand) - 1]})
        if session.game.pending_discard is not None:
            assert session.state()["discard"]["count"] == count - len(discarded)
            assert session.state()["discard_top"]["label"] == str(card.rank)
    assert session.state()["discard"] is None
    assert all(card in human.hand for card in original_hand if card not in discarded)


def test_free_potion_discard_does_not_end_human_turn():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.potions.append(PotionToken(DRAW_TWO))
    human.hand.extend([Card("red", 1), Card("blue", 2)])

    session.action({"action": "potion", "potion": 0})
    assert session.game.pending_discard is not None
    while session.game.pending_discard is not None:
        session.action({"action": "discard", "cards": [len(human.hand) - 1]})

    assert session.state()["human_turn"] is True
    session.action({"action": "prepare_start"})
    assert session.state()["prepare"] is not None


def test_browser_stages_bot_hand_limit_discards_one_at_a_time():
    session = WebSession()
    bot = session.game.state.players[1]
    session.game.state.current_player = 1
    bot.hand.extend(
        [
            Card("red", 1),
            Card("blue", 2),
            Card("green", 3),
            Card("yellow", 4),
        ]
    )
    while len(bot.hand) <= bot.hand_limit:
        bot.hand.append(Card("purple", 5))

    count = len(bot.hand) - bot.hand_limit
    session.game.discard_down(bot)
    assert session.state()["discard"]["player_is_bot"] is True
    assert session.state()["discard"]["count"] == count

    while session.game.pending_discard is not None:
        session.action({"action": "continue_bot_discard"})
        if session.game.pending_discard is not None:
            assert session.state()["discard"]["count"] < count
            assert session.state()["discard_top"] is not None

    assert session.state()["discard"] is None


def test_a_failed_skill_reward_cannot_be_applied_twice():
    """A challenge must not stay clickable after its skill choice was taken."""
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Trader"]
    encounter = Encounter("Test", 1, 1, 1, 1, encounter_type="type0")
    session.game.state.encounters[0] = encounter
    human.hand[:2] = [Card("red", 4), Card("red", 5)]

    session.action(
        {
            "action": "attempt",
            "encounter": encounter.id,
            "method": "strike",
            "cards": [0, 1],
        }
    )
    session.action({"action": "reroll", "indices": []})
    session.action({"action": "resolve", "plus_two": False})
    state = session.state()
    if state["challenge"] and state["challenge"]["phase"] == "skill":
        track = state["challenge"]["tracks"][0]
        session.action({"action": "skill", "track": track})
        level = human.skill_levels[track]
        with pytest.raises(ValueError):
            session.action({"action": "skill", "track": track})
        assert human.skill_levels[track] == level


def test_web_skill_choice_does_not_fall_back_to_sneak():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Monk"]
    encounter = Encounter("Test", 1, 1, 1, 1, encounter_type="type0")
    session.game.state.encounters[0] = encounter
    human.hand[:2] = [Card("red", 4), Card("red", 5)]

    session.action(
        {
            "action": "attempt",
            "encounter": encounter.id,
            "method": "strike",
            "cards": [0, 1],
        }
    )
    session.action({"action": "reroll", "indices": []})
    session.action({"action": "resolve", "plus_two": False})
    assert session.state()["challenge"]["phase"] == "skill"
    assert "trophy" in session.state()["challenge"]["tracks"]

    with pytest.raises(ValueError, match="invalid skill track"):
        session.action({"action": "skill", "track": "not-a-track"})
    assert human.skill_levels == {}

    session.action({"action": "skill", "track": "trophy"})
    assert human.skill_levels == {"trophy": 1}


def test_stale_human_skill_choice_cannot_interfere_with_bot_challenge():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    bot = session.game.state.players[1]
    human.character = CHARACTERS["Trader"]
    encounter = Encounter("Bot challenge", 1, 1, 1, 1, encounter_type="type0")
    session.game.state.encounters[0] = encounter
    decision = Decision("attempt", encounter, tuple(bot.hand[:1]), "strike")
    session.pending_challenge = session.game.begin_attempt(bot, encounter, decision)

    with pytest.raises(ValueError, match="skill choice has expired"):
        session.action({"action": "skill", "track": "strike"})

    assert human.skill_levels == {}
    assert session.pending_challenge is not None
    assert session.state()["human_turn"] is True


def test_stale_bot_continuation_cannot_advance_the_turn():
    session = WebSession()
    bot = session.game.state.players[1]
    session.game.state.current_player = 1
    encounter = Encounter("Bot challenge", 1, 1, 1, 1, encounter_type="type0")
    session.game.state.encounters[0] = encounter
    decision = Decision("attempt", encounter, tuple(bot.hand[:1]), "strike")
    session.pending_challenge = session.game.begin_attempt(bot, encounter, decision)
    session.revision = 2

    with pytest.raises(ValueError, match="stale bot action"):
        session.action({"action": "continue_bot", "revision": 1})

    assert session.pending_challenge is not None
    assert session.game.state.current_player == 1


def test_failed_skill_upgrade_keeps_the_choice_and_human_turn(monkeypatch):
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Trader"]
    encounter = Encounter("Skill failure", 1, 1, 1, 1, encounter_type="type0")
    session.pending_challenge = ChallengeProgress(
        human,
        encounter,
        Decision("attempt", encounter, (), "strike"),
        (4,),
        0,
        4,
        1,
        0,
    )

    def fail_complete_experience(player):
        raise ValueError("simulated skill failure")

    monkeypatch.setattr(session.game, "complete_experience", fail_complete_experience)

    with pytest.raises(ValueError, match="simulated skill failure"):
        session.action({"action": "skill", "track": "strike"})

    assert session.pending_challenge is not None
    assert session.state()["human_turn"] is True
    assert human.skill_levels == {}


def test_stale_skill_request_is_expired_but_displayed_track_remains_retryable():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Trader"]
    encounter = Encounter("Skill retry", 1, 1, 1, 1, encounter_type="type0")
    session.pending_challenge = ChallengeProgress(
        human,
        encounter,
        Decision("attempt", encounter, (), "strike"),
        (4,),
        0,
        4,
        1,
        0,
    )
    session.pending_skill_tracks = ("strike", "sneak", "steal", "hand_limit")
    session.revision = 4

    with pytest.raises(ValueError, match="skill choice has expired"):
        session.action({"action": "skill", "track": "strike", "revision": 3})

    assert session.pending_challenge is not None
    session.action({"action": "skill", "track": "strike", "revision": 4})
    assert human.skill_levels == {"strike": 1}


def test_every_displayed_skill_track_accepts_each_unmaxed_level():
    for character_name, track_steps in SKILL_TRACKS.items():
        for track, steps in track_steps.items():
            for level in range(len(steps)):
                session = WebSession()
                _force_human_turn(session)
                human = session.human
                human.character = CHARACTERS[character_name]
                human.skill_levels[track] = level
                encounter = Encounter(
                    f"{character_name} {track} {level}",
                    1,
                    1,
                    1,
                    1,
                    encounter_type="type0",
                )
                session.pending_challenge = ChallengeProgress(
                    human,
                    encounter,
                    Decision("attempt", encounter, (), "strike"),
                    (4,),
                    0,
                    4,
                    1,
                    0,
                )

                assert track in session.state()["challenge"]["tracks"]
                session.action({"action": "skill", "track": track})

                assert human.skill_levels[track] == level + 1


def test_web_skill_choices_do_not_reuse_the_previous_track():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Monk"]

    for track in ("sneak", "steal"):
        encounter = Encounter(
            f"Test {track}", 1, 1, 1, 1, encounter_type="type0"
        )
        session.game.state.encounters[0] = encounter
        human.hand[:2] = [Card("red", 4), Card("red", 5)]
        session.action(
            {
                "action": "attempt",
                "encounter": encounter.id,
                "method": "strike",
                "cards": [0, 1],
            }
        )
        session.action({"action": "reroll", "indices": []})
        session.action({"action": "resolve", "plus_two": False})
        assert session.state()["challenge"]["phase"] == "skill"
        session.action({"action": "skill", "track": track})
        _force_human_turn(session)

    assert human.skill_levels == {"sneak": 1, "steal": 1}


def test_web_monk_can_choose_sneak_for_consecutive_skill_upgrades():
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Monk"]

    for index in range(2):
        encounter = Encounter(
            f"Test sneak {index}", 1, 1, 1, 1, encounter_type="type0"
        )
        session.game.state.encounters[0] = encounter
        human.hand[:2] = [Card("red", 4), Card("red", 5)]
        session.action(
            {
                "action": "attempt",
                "encounter": encounter.id,
                "method": "strike",
                "cards": [0, 1],
            }
        )
        session.action({"action": "reroll", "indices": []})
        session.action({"action": "resolve", "plus_two": False})
        assert session.state()["challenge"]["phase"] == "skill"
        session.action({"action": "skill", "track": "sneak"})
        _force_human_turn(session)

    assert human.skill_levels == {"sneak": 2}


def test_web_refreshes_after_rejected_skill_choice():
    assert "if(!r.ok){await get();alert(d.error);return}" in HTML
    assert "requestInFlight" in HTML
    assert "stateRevision" in HTML
    assert "stateRequest" in HTML
    assert "if(request!==stateRequest)return" in HTML
    assert "S=d;stateRevision++;render()" in HTML
    assert "if(revision===stateRevision)" in HTML
    assert "}else{clearTimeout(botTimer);botTimer=null}" in HTML


def test_web_logs_clicks_and_action_results_to_the_console():
    assert "[DragonIsles click]" in HTML
    assert "[DragonIsles action]" in HTML
    assert "[DragonIsles response]" in HTML
    assert "serverRevision=S.revision" in HTML
    assert "revision:serverRevision" in HTML


def test_web_eighth_encounter_skips_skill_prompt_and_ends_game():
    """Resolving the 8th Encounter must not pause for skill selection."""
    session = WebSession()
    _force_human_turn(session)
    human = session.human
    human.character = CHARACTERS["Warrior"]
    human.encounters[:] = [
        Encounter(f"Done {index}", 1, 1, 1, 1, encounter_type="type0")
        for index in range(7)
    ]
    encounter = Encounter("Last", 1, 2, 2, 2, encounter_type="type0")
    session.game.state.encounters[0] = encounter
    human.hand[:2] = [Card("red", 4), Card("red", 5)]

    session.action(
        {
            "action": "attempt",
            "encounter": encounter.id,
            "method": "strike",
            "cards": [0, 1],
        }
    )
    assert session.state()["challenge"]["phase"] == "resolve"

    session.action({"action": "resolve", "plus_two": False})
    state = session.state()
    assert state["challenge"] is None
    assert state["game_over"] is True
    assert len(human.encounters) == 8
    assert human.skill_levels == {}


def test_web_state_reports_token_supplies_and_conserves_them():
    session = WebSession()
    tokens = session.state()["tokens"]
    held = sum(len(player.potions) for player in session.game.state.players)

    assert tokens["potions"] + held + len(session.game.used_potions) == 20
    assert (
        dict(tokens["coins"])[1]
        + sum(player.coins for player in session.game.state.players)
        == 30
    )


def _seeded_game(seed):
    from dragonisles.engine import Game, GameInteraction

    encounters = load_encounters(
        Path(__file__).resolve().parent.parent / "data" / "encounters.json"
    )
    return Game(
        encounters,
        rng=random.Random(seed),
        characters=[CHARACTERS["Sorcerer"], CHARACTERS["Pirate"]],
        interaction=GameInteraction(
            choose_discards=lambda player, count: player.hand[:count],
            choose_track=lambda player, tracks: tracks[0],
            choose_plus_two=lambda player, rolled, target: False,
            choose_rerolls=lambda player, rolls, limit: (0,),
        ),
    )


def test_staged_and_single_call_challenges_agree_for_the_same_seed():
    """The browser's staged API must not diverge from the CLI's attempt()."""
    combined = _seeded_game(11)
    staged = _seeded_game(11)

    for game in (combined, staged):
        player = game.state.players[0]
        player.skill_levels["reroll"] = 1
        player.hand[:2] = [Card("red", 4), Card("red", 5)]

    encounter_combined = combined.state.encounters[0]
    encounter_staged = staged.state.encounters[0]
    method = next(
        m
        for m in ("strike", "sneak", "steal")
        if m != encounter_combined.blocked_method
    )

    combined_player = combined.state.players[0]
    combined_result = combined.attempt(
        combined_player,
        encounter_combined,
        Decision(
            "attempt", encounter_combined, tuple(combined_player.hand[:2]), method
        ),
    )

    staged_player = staged.state.players[0]
    progress = staged.begin_attempt(
        staged_player,
        encounter_staged,
        Decision("attempt", encounter_staged, tuple(staged_player.hand[:2]), method),
    )
    staged.reroll_attempt(progress, (0,))
    staged_result = staged.resolve_attempt(progress, use_plus_two=False)

    assert combined_result == staged_result
    assert combined_player.coins == staged_player.coins
    assert len(combined_player.hand) == len(staged_player.hand)
    assert len(combined_player.encounters) == len(staged_player.encounters)
    assert len(combined_player.potions) == len(staged_player.potions)


def test_versus_game_has_two_human_players_and_seat_state():
    session = WebSession("versus")

    assert all(not player.is_bot for player in session.game.state.players)
    state = session.state(1)
    assert state["mode"] == "versus"
    assert state["seat"] == 1
    assert state["seat_name"] == "Player 2"
    assert state["opponent_name"] == "Player 1"
    assert state["human_turn"] == (
        session.game.state.current_player == 1
    )


def test_versus_turn_gating_and_full_turn_handoff():
    session = WebSession("versus")
    player_one, player_two = session.game.state.players
    session.game.state.current_player = 0

    with pytest.raises(ValueError, match="it is not your turn"):
        session.action({"action": "prepare_start"}, seat=1)

    session.action({"action": "prepare_start"}, seat=0)
    while session.pending_prepare is not None:
        session.action({"action": "prepare_source", "source": "deck"}, seat=0)
        while session.game.pending_discard is not None:
            session.action(
                {"action": "discard", "cards": [len(player_one.hand) - 1]},
                seat=0,
            )

    assert session.game.state.current_player == 1
    session.action({"action": "prepare_start"}, seat=1)
    assert session.pending_prepare["player"] is player_two

    with pytest.raises(ValueError, match="it is not your turn"):
        session.action({"action": "prepare_source", "source": "deck"}, seat=0)


def test_versus_state_hides_opponent_hand_and_potion_kinds():
    session = WebSession("versus")
    player_one, player_two = session.game.state.players
    player_one.hand[:] = [Card("red", 1)]
    player_two.hand[:] = [Card("blue", 10)]
    player_one.potions[:] = [PotionToken(PLUS_TWO)]
    player_two.potions[:] = [PotionToken(DRAW_TWO)]

    state = session.state(0)

    assert [card["rank"] for card in state["hand"]] == [1]
    assert state["players"][0]["potions"] == [PLUS_TWO]
    assert state["players"][1]["potions"] == 1
    assert all(card["rank"] != 10 for card in state["hand"])
    assert DRAW_TWO not in json.dumps(state)


def test_versus_rejects_bot_continuation_actions():
    session = WebSession("versus")

    for action in ("continue_bot", "continue_bot_discard"):
        with pytest.raises(ValueError, match="unavailable in versus mode"):
            session.action({"action": action}, seat=0)


def test_passphrase_assigns_two_seats_and_rejects_a_third():
    configure("versus", "test123")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = _web_request(server, "GET", "/api/state")
        assert status == 403

        status, _, body = _web_request(
            server, "POST", "/api/join", {"passphrase": "wrong"}
        )
        assert status == 403
        assert body == {"error": "invalid passphrase"}

        status, headers, body = _web_request(
            server, "POST", "/api/join", {"passphrase": "test123"}
        )
        assert status == 200
        assert body == {"seat": 0}
        first_cookie = next(value for key, value in headers if key == "Set-Cookie")

        status, _, body = _web_request(
            server, "GET", "/api/state", cookie=first_cookie.split(";", 1)[0]
        )
        assert status == 200
        assert body["seat"] == 0

        status, headers, body = _web_request(
            server, "POST", "/api/join", {"passphrase": "test123"}
        )
        assert status == 200
        assert body == {"seat": 1}
        second_cookie = next(value for key, value in headers if key == "Set-Cookie")

        status, _, body = _web_request(
            server, "GET", "/api/state", cookie=second_cookie.split(";", 1)[0]
        )
        assert status == 200
        assert body["seat"] == 1

        status, _, body = _web_request(
            server, "POST", "/api/join", {"passphrase": "test123"}
        )
        assert status == 403
        assert body == {"error": "both seats are taken"}
    finally:
        server.shutdown()
        server.server_close()
        configure("bot", None)


def test_mode_switch_reassigns_authenticated_seats():
    configure("bot", "test123")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, headers, body = _web_request(
            server, "POST", "/api/join", {"passphrase": "test123"}
        )
        assert status == 200
        assert body == {"seat": 0}
        first_cookie = next(value for key, value in headers if key == "Set-Cookie")
        first_cookie = first_cookie.split(";", 1)[0]

        status, _, body = _web_request(
            server,
            "POST",
            "/api/action",
            {"action": "new_game", "mode": "versus"},
            cookie=first_cookie,
        )
        assert status == 200
        assert body["mode"] == "versus"
        assert body["seat"] == 0

        status, _, body = _web_request(
            server, "POST", "/api/join", {"passphrase": "test123"}
        )
        assert status == 200
        assert body == {"seat": 1}
    finally:
        server.shutdown()
        server.server_close()
        configure("bot", None)


def test_non_ascii_passphrase_is_rejected_without_server_error():
    configure("bot", "test123")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, body = _web_request(
            server, "POST", "/api/join", {"passphrase": "pässphrase"}
        )
        assert status == 403
        assert body == {"error": "invalid passphrase"}
    finally:
        server.shutdown()
        server.server_close()
        configure("bot", None)


def test_versus_without_passphrase_requires_authentication_but_bot_does_not():
    configure("versus", None)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        status, _, _ = _web_request(server, "GET", "/api/state")
        assert status == 403

        configure("bot", None)
        status, _, body = _web_request(server, "GET", "/api/state")
        assert status == 200
        assert body["mode"] == "bot"
        assert body["seat"] == 0
    finally:
        server.shutdown()
        server.server_close()
        configure("bot", None)
