import http.client
import json
import pickle
import threading

from http.server import ThreadingHTTPServer

import pytest

from dragonisles.bot import Decision
from dragonisles.persistence import load, save
from dragonisles.web import Handler, WebSession, configure


def _request(server, method, path, body=None, cookie=None):
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
    headers = response.getheaders()
    connection.close()
    return response.status, headers, json.loads(data or b"{}")


def _serve():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def _card_snapshot(value):
    return value.suit, value.rank, value.wild


def _snapshot(game):
    return {
        "hands": [
            [_card_snapshot(value) for value in player.hand]
            for player in game.state.players
        ],
        "deck": [_card_snapshot(value) for value in game.state.deck.draw_pile],
        "encounters": [value.id for value in game.state.encounters],
        "market": [_card_snapshot(value) for value in game.state.market],
        "coins": [player.coins for player in game.state.players],
        "skills": [dict(player.skill_levels) for player in game.state.players],
        "current_player": game.state.current_player,
        "turn_number": game.state.turn_number,
    }


def test_save_load_round_trip_preserves_game_state(tmp_path):
    source = WebSession("versus")
    source.game.state.players[0].coins = 7
    source.game.state.players[1].skill_levels["hand_limit"] = 1
    source.game.state.current_player = 1
    source.game.state.turn_number = 4
    expected = _snapshot(source.game)
    path = tmp_path / "game.pkl"

    source.set_seat_name(0, "Alice")
    source.set_seat_name(1, "Bob")
    save(
        path,
        source.mode,
        source.game,
        {"first": 0, "second": 1},
        source.seat_names,
    )
    loaded = load(path)

    assert loaded is not None
    mode, game, auth, names, boat, metadata = loaded
    assert metadata == {}
    assert mode == "versus"
    assert auth == {"first": 0, "second": 1}
    assert names == {0: "Alice", 1: "Bob"}
    assert boat == {
        "choices": {},
        "stage": "choice",
        "result": None,
        "decided": True,
    }
    assert _snapshot(game) == expected
    assert game.interaction is None

    restored = WebSession("bot")
    restored.restore(mode, game, names, boat)
    assert _snapshot(restored.game) == expected
    assert restored.game.interaction is not None
    assert restored.state(0)["seat_name"] == "Alice"
    assert restored.state(0)["opponent_name"] == "Bob"


def test_solo_save_load_preserves_single_player_state(tmp_path):
    path = tmp_path / "solo.pkl"
    source = WebSession("solo")
    source.game.state.turn_number = 4
    source.game.state.players[0].coins = 3

    save(path, source.mode, source.game, {}, source.seat_names)
    loaded = load(path)

    assert loaded is not None
    mode, game, auth, names, boat, metadata = loaded
    assert metadata == {}
    assert mode == "solo"
    assert auth == {}
    assert names == {}
    assert len(game.state.players) == 1
    assert game.state.turn_number == 4
    restored = WebSession("solo")
    restored.restore(mode, game, names, boat)
    assert restored.state()["opponent_name"] is None
    assert restored.state()["players"][0]["coins"] == 3


def test_restart_keeps_authenticated_seats(tmp_path):
    path = tmp_path / "game.pkl"
    configure("versus", "test123", state_path=path)
    server = _serve()
    try:
        status, headers, body = _request(
            server,
            "POST",
            "/api/join",
            {"passphrase": "test123", "name": "Alice"},
        )
        assert status == 200
        assert body == {"seat": 0}
        cookie_zero = next(value for key, value in headers if key == "Set-Cookie")
        cookie_zero = cookie_zero.split(";", 1)[0]
        status, headers, body = _request(
            server,
            "POST",
            "/api/join",
            {"passphrase": "test123", "name": "Bob"},
        )
        assert status == 200
        assert body == {"seat": 1}
        cookie_one = next(value for key, value in headers if key == "Set-Cookie")
        cookie_one = cookie_one.split(";", 1)[0]
    finally:
        server.shutdown()
        server.server_close()

    configure("versus", "test123", state_path=path)
    server = _serve()
    try:
        status, _, body = _request(server, "GET", "/api/state", cookie=cookie_zero)
        assert status == 200
        assert body["seat"] == 0
        assert body["seat_name"] == "Alice"
        status, _, body = _request(server, "GET", "/api/state", cookie=cookie_one)
        assert status == 200
        assert body["seat"] == 1
        assert body["seat_name"] == "Bob"
    finally:
        server.shutdown()
        server.server_close()
        configure("bot", None)


def test_pending_prompt_is_saved_with_the_game(tmp_path):
    path = tmp_path / "game.pkl"
    session = WebSession("versus", state_path=path)
    session.action({"action": "boat_choice", "choice": 0}, seat=0)
    session.action({"action": "boat_choice", "choice": 0}, seat=1)
    session.game.state.current_player = 0
    session._save()
    before = load(path)
    assert before is not None
    before_snapshot = _snapshot(before[1])

    session.action({"action": "prepare_start"}, seat=0)

    after = load(path)
    assert after is not None
    assert _snapshot(after[1]) == before_snapshot
    pending = after[5].get("pending", {})
    prepare = pending.get("prepare")
    assert prepare is not None
    assert prepare["player"] is after[1].state.players[0]
    assert prepare["remaining"] > 0

    restored = WebSession("versus")
    restored.restore(
        after[0],
        after[1],
        after[3],
        after[4],
        pending=after[5].get("pending"),
        events=after[5].get("events"),
    )
    assert restored.pending_prepare is not None
    assert restored.state(0)["prepare"]["remaining"] == prepare["remaining"]


def test_pending_boat_question_round_trips(tmp_path):
    path = tmp_path / "boat.pkl"
    source = WebSession("versus", state_path=path)
    source.action({"action": "boat_choice", "choice": 1}, seat=0)

    loaded = load(path)

    assert loaded is not None
    assert loaded[4] == {
        "choices": {0: 1},
        "stage": "choice",
        "result": None,
        "decided": False,
    }
    restored = WebSession("bot")
    restored.restore(loaded[0], loaded[1], loaded[3], loaded[4])
    assert restored.state(0)["boat"] == {
        "stage": "choice",
        "answered": True,
        "choice": 1,
        "waiting": True,
        "message": None,
        "choices": [
            {"value": 0, "label": "I did"},
            {"value": 1, "label": restored.game.state.players[1].name},
        ],
    }
    assert restored.state(1)["boat"] == {
        "stage": "choice",
        "answered": False,
        "choice": None,
        "waiting": False,
        "message": None,
        "choices": [
            {"value": 1, "label": "I did"},
            {"value": 0, "label": restored.game.state.players[0].name},
        ],
    }


def test_resolved_boat_choice_round_trips(tmp_path):
    path = tmp_path / "boat-choice.pkl"
    source = WebSession("versus", state_path=path)
    source.action({"action": "boat_choice", "choice": 1}, seat=0)
    source.action({"action": "boat_choice", "choice": 1}, seat=1)

    loaded = load(path)

    assert loaded is not None
    assert loaded[4]["choices"] == {0: 1, 1: 1}
    assert loaded[4]["stage"] == "choice"
    assert loaded[4]["decided"] is True
    restored = WebSession("bot")
    restored.restore(loaded[0], loaded[1], loaded[3], loaded[4])
    assert restored.state(0)["boat"] is None
    assert restored.state(1)["boat"] is None
    assert restored.first_turn_decided is True


def test_legacy_boat_save_loads_as_fresh_choice_stage(tmp_path):
    source = WebSession("versus")
    path = tmp_path / "legacy-boat.pkl"
    save(
        path,
        source.mode,
        source.game,
        {},
        boat={"answers": {0: "last week"}, "result": None, "decided": False},
    )

    loaded = load(path)

    assert loaded is not None
    assert loaded[4]["stage"] == "choice"
    restored = WebSession("bot")
    restored.restore(loaded[0], loaded[1], loaded[3], loaded[4])
    assert restored.state(0)["boat"]["stage"] == "choice"


def test_corrupt_state_file_starts_fresh_game(tmp_path):
    path = tmp_path / "game.pkl"
    path.write_bytes(b"not a pickle")

    configure("bot", None, state_path=path)
    server = _serve()
    try:
        status, _, body = _request(server, "GET", "/api/state")
        assert status == 200
        assert body["mode"] == "bot"
    finally:
        server.shutdown()
        server.server_close()

    path.write_bytes(b"not a pickle")
    configure("versus", "test123", state_path=path)
    server = _serve()
    try:
        status, _, _ = _request(server, "GET", "/api/state")
        assert status == 403
        status, _, body = _request(
            server, "POST", "/api/join", {"passphrase": "test123"}
        )
        assert status == 200
        assert body == {"seat": 0}
    finally:
        server.shutdown()
        server.server_close()
        configure("bot", None)


def test_persistence_disabled_without_state_path(tmp_path):
    session = WebSession("bot")
    session.new_game()
    assert list(tmp_path.iterdir()) == []


def test_turn_continues_after_restore_in_both_modes(tmp_path):
    for mode in ("bot", "versus"):
        path = tmp_path / f"{mode}.pkl"
        session = WebSession(mode, state_path=path)
        session.pending = {}
        session.pending_challenge = None
        session.pending_skill_tracks = None
        session.pending_prepare = None
        session.pending_bot_prepare = None
        session.pending_free_action_discard = None
        session.game.pending_discard = None
        session.game.pending_treasure_draw = None
        session.game.pending_trader_draw = None
        if mode == "versus":
                session.action({"action": "boat_choice", "choice": 0}, seat=0)
                session.action({"action": "boat_choice", "choice": 0}, seat=1)
        session.game.state.current_player = 0
        session._save()
        loaded = load(path)
        assert loaded is not None
        session.restore(loaded[0], loaded[1], loaded[3], loaded[4])
        session.action({"action": "prepare_start"}, seat=0)
        while session.pending_prepare is not None:
            session.action({"action": "prepare_source", "source": "deck"}, seat=0)
            while session.game.pending_discard is not None:
                session.action(
                    {"action": "discard", "cards": [len(session.human.hand) - 1]},
                    seat=0,
                )
        assert session.game.state.turn_number >= 2


def test_restore_resumes_a_bot_turn():
    source = WebSession("bot")
    bot = source.game.state.players[1]
    source.pending = {}
    source.pending_challenge = None
    source.pending_skill_tracks = None
    source.pending_prepare = None
    source.pending_bot_prepare = None
    source.pending_free_action_discard = None
    source.game.pending_discard = None
    source.game.pending_treasure_draw = None
    source.game.pending_trader_draw = None
    source.first_turn_decided = True
    source._first_turn_result = "Human goes first."
    source.game.state.current_player = 1
    bot.hand[:] = bot.hand[:1]
    source.game.bot_policy.choose = lambda _context: Decision("prepare")
    prepares = bot.prepares

    restored = WebSession("bot")
    restored.restore("bot", source.game)

    assert bot.prepares == prepares + 1
    assert restored.game.state.current_player == 0


def test_bot_first_turn_round_trips_as_human_first(tmp_path):
    path = tmp_path / "bot.pkl"
    source = WebSession("bot", state_path=path)
    source._save()

    loaded = load(path)
    assert loaded is not None
    assert loaded[4]["first_turn"] == {"result": "Human goes first.", "decided": True}
    bot = loaded[1].state.players[1]
    bot_snapshot = (bot.attempts, bot.prepares, list(bot.encounters))

    restored = WebSession("bot")
    restored.restore(loaded[0], loaded[1], loaded[3], loaded[4])

    assert restored.state()["first_turn"] is None
    assert restored.game.state.current_player == loaded[1].state.current_player
    assert (bot.attempts, bot.prepares, bot.encounters) == bot_snapshot


def test_legacy_bot_save_without_first_turn_loads_as_decided(tmp_path):
    path = tmp_path / "legacy-bot.pkl"
    source = WebSession("bot")
    save(path, "bot", source.game, {})

    loaded = load(path)
    assert loaded is not None
    assert loaded[4]["first_turn"] == {"result": None, "decided": True}

    restored = WebSession("bot")
    restored.restore(loaded[0], loaded[1], loaded[3], loaded[4])

    assert restored.state()["first_turn"] is None


def test_legacy_pending_bot_first_turn_is_normalized_to_human_first(tmp_path):
    path = tmp_path / "pending-bot.pkl"
    source = WebSession("bot")
    source.game.state.current_player = 1
    save(
        path,
        "bot",
        source.game,
        {},
        first_turn={"result": None, "decided": False},
    )

    loaded = load(path)
    assert loaded is not None
    restored = WebSession("bot")
    restored.restore(loaded[0], loaded[1], loaded[3], loaded[4])

    assert restored.state()["first_turn"] is None
    assert restored.state()["first_turn_result"] == "Human goes first."
    assert restored.game.state.current_player == 0


def test_legacy_state_without_names_loads_with_empty_mapping(tmp_path):
    source = WebSession("versus")
    path = tmp_path / "legacy.pkl"
    save(path, source.mode, source.game, {})
    with path.open("rb") as stream:
        payload = pickle.load(stream)
    payload.pop("names")
    with path.open("wb") as stream:
        pickle.dump(payload, stream, protocol=5)

    loaded = load(path)

    assert loaded is not None
    assert loaded[3] == {}
    assert loaded[4] == {
        "choices": {},
        "stage": "choice",
        "result": None,
        "decided": True,
    }


@pytest.mark.parametrize(
    "names",
    ({0: 1}, {2: "Invalid seat"}, [("0", "Invalid shape")]),
)
def test_invalid_persisted_names_are_rejected(tmp_path, names):
    source = WebSession("versus")
    path = tmp_path / "invalid.pkl"
    save(path, source.mode, source.game, {})
    with path.open("rb") as stream:
        payload = pickle.load(stream)
    payload["names"] = names
    with path.open("wb") as stream:
        pickle.dump(payload, stream, protocol=5)

    assert load(path) is None


@pytest.mark.parametrize(
    "boat",
    (
        {"answers": {0: 1}, "result": None, "decided": False},
        {"answers": {2: "today"}, "result": None, "decided": False},
        {
            "answers": {},
            "times": {0: 1},
            "stage": "time",
            "result": None,
            "decided": False,
        },
        {
            "answers": {},
            "times": {2: "9am"},
            "stage": "time",
            "result": None,
            "decided": False,
        },
        {
            "answers": {},
            "times": {},
            "stage": "invalid",
            "result": None,
            "decided": False,
        },
        {"answers": {}, "result": 1, "decided": False},
        {"answers": {}, "result": None, "decided": "no"},
    ),
)
def test_invalid_persisted_boat_state_is_rejected(tmp_path, boat):
    source = WebSession("versus")
    path = tmp_path / "invalid-boat.pkl"
    save(path, source.mode, source.game, {}, boat=boat)
    with path.open("rb") as stream:
        payload = pickle.load(stream)
    payload["boat"] = boat
    with path.open("wb") as stream:
        pickle.dump(payload, stream, protocol=5)

    assert load(path) is None
