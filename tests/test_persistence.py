import http.client
import json
import threading

from http.server import ThreadingHTTPServer

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

    save(path, source.mode, source.game, {"first": 0, "second": 1})
    loaded = load(path)

    assert loaded is not None
    mode, game, auth = loaded
    assert mode == "versus"
    assert auth == {"first": 0, "second": 1}
    assert _snapshot(game) == expected
    assert game.interaction is None

    restored = WebSession("bot")
    restored.restore(mode, game)
    assert _snapshot(restored.game) == expected
    assert restored.game.interaction is not None


def test_restart_keeps_authenticated_seats(tmp_path):
    path = tmp_path / "game.pkl"
    configure("versus", "test123", state_path=path)
    server = _serve()
    try:
        status, headers, body = _request(
            server, "POST", "/api/join", {"passphrase": "test123"}
        )
        assert status == 200
        assert body == {"seat": 0}
        cookie_zero = next(value for key, value in headers if key == "Set-Cookie")
        cookie_zero = cookie_zero.split(";", 1)[0]
        status, headers, body = _request(
            server, "POST", "/api/join", {"passphrase": "test123"}
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
        assert body["seat_name"] == "Player 1"
        status, _, body = _request(server, "GET", "/api/state", cookie=cookie_one)
        assert status == 200
        assert body["seat"] == 1
        assert body["seat_name"] == "Player 2"
    finally:
        server.shutdown()
        server.server_close()
        configure("bot", None)


def test_pending_prompt_does_not_overwrite_last_clean_save(tmp_path):
    path = tmp_path / "game.pkl"
    session = WebSession("versus", state_path=path)
    session.game.state.current_player = 0
    session._save()
    before = load(path)
    assert before is not None
    before_snapshot = _snapshot(before[1])

    session.action({"action": "prepare_start"}, seat=0)

    after = load(path)
    assert after is not None
    assert _snapshot(after[1]) == before_snapshot
    assert after[1].state.turn_number == before[1].state.turn_number


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
        session.game.state.current_player = 0
        session._save()
        loaded = load(path)
        assert loaded is not None
        session.restore(*loaded[:2])
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
    source.game.state.current_player = 1
    bot.hand[:] = bot.hand[:1]
    source.game.bot_policy.choose = lambda _context: Decision("prepare")
    prepares = bot.prepares

    restored = WebSession("bot")
    restored.restore("bot", source.game)

    assert bot.prepares == prepares + 1
    assert restored.game.state.current_player == 0
