"""Small standard-library browser front end for DragonIsles."""

from __future__ import annotations

import json
import hmac
import os
import random
import secrets
import threading
from argparse import ArgumentParser
from collections.abc import Sequence
from datetime import date
from http.cookies import SimpleCookie
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .boat import (
    BoatAnswer,
    BoatTime,
    TIME_FOLLOWUP,
    parse_boat_answer,
    parse_boat_time,
    resolve_first_seat,
)
from .bot import Decision
from .cards import Card
from .cli import _encounter_mechanics
from .combos import is_legal, is_legal_reason
from .characters import ABILITIES, CHARACTERS, SKILL_TRACKS, TrackStep, available_tracks
from .encounters import Encounter, load_encounters
from .engine import ChallengeProgress, Game, GameInteraction, Player
from .persistence import load as load_state
from .persistence import save as save_state
from .potions import PLUS_TWO
from .scoring import trophy_holders
from .treasures import Treasure


ROOT = Path(__file__).parent.parent


class WebSession:
    """Owns one browser game's mutable state and serializes its requests."""

    def __init__(
        self, mode: str = "bot", state_path: Path | None = None
    ) -> None:
        if mode not in {"bot", "versus"}:
            raise ValueError("mode must be bot or versus")
        self.lock = threading.RLock()
        self.mode = mode
        self.state_path = state_path
        self.seat_names: dict[int, str] = {}
        self.boat_answers: dict[int, BoatAnswer] = {}
        self.boat_times: dict[int, BoatTime] = {}
        self.boat_time_open = False
        self.boat_time_followups: dict[int, str] = {}
        self._first_turn_result: str | None = None
        self.first_turn_decided = False
        self._reset()

    @property
    def boat_result(self) -> str | None:
        return self._first_turn_result if self.mode == "versus" else None

    @boat_result.setter
    def boat_result(self, value: str | None) -> None:
        self._first_turn_result = value

    def _interaction(self) -> GameInteraction:
        return GameInteraction(
            choose_discards=self._choose_discards,
            choose_treasure=self._defer_treasure,
            choose_treasure_card=self._defer_treasure_card,
            choose_track=self._choose_track,
            choose_plus_two=self._choose_plus_two,
            choose_rerolls=self._choose_rerolls,
            stage_bot_discards=True,
            show_roll=self._show_roll,
            show_challenge_result=self._show_result,
            announce=self.events.append,
        )

    def _reset(self) -> None:
        """Deal a new game whose engine callbacks belong to this session."""
        self.events: list[str] = []
        encounters = load_encounters(ROOT / "data" / "encounters.json")
        interaction = self._interaction()
        if self.mode == "versus":
            rng = random.Random()
            characters = rng.sample(list(CHARACTERS.values()), 2)
            players = [
                Player("Player 1", characters[0]),
                Player("Player 2", characters[1]),
            ]
            self.game = Game(encounters, rng=rng, players=players, interaction=interaction)
        else:
            self.game = Game(encounters, interaction=interaction)
        self._apply_seat_names()
        self.boat_answers = {}
        self.boat_times = {}
        self.boat_time_open = False
        self.boat_time_followups = {}
        self._first_turn_result = None
        self.first_turn_decided = False
        self.pending: dict[str, Any] = {}
        self.pending_challenge: ChallengeProgress | None = None
        self.pending_skill_tracks: tuple[str, ...] | None = None
        self.pending_prepare: dict[str, Any] | None = None
        self.pending_bot_prepare: dict[str, Any] | None = None
        self.pending_free_action_discard: Player | None = None
        self.revision = 0
        self._run_bots()

    def new_game(self, mode: str | None = None) -> None:
        with self.lock:
            if mode is not None:
                if mode not in {"bot", "versus"}:
                    raise ValueError("mode must be bot or versus")
                self.mode = mode
            self._reset()
            self._save()

    def restore(
        self,
        mode: str,
        game: Game,
        seat_names: dict[int, str] | None = None,
        boat: dict[str, Any] | None = None,
    ) -> None:
        """Adopt a clean persisted game and reconnect browser callbacks."""
        if mode not in {"bot", "versus"}:
            raise ValueError("mode must be bot or versus")
        with self.lock:
            self.mode = mode
            self.seat_names = dict(seat_names or {})
            self.events = []
            self.game = game
            self.game.interaction = self._interaction()
            boat = boat or {
                "answers": {},
                "times": {},
                "stage": "date",
                "result": None,
                "decided": True,
            }
            self.boat_answers = {
                seat: answer
                for seat, raw in boat["answers"].items()
                if (
                    answer := parse_boat_answer(raw, date.today())
                ).tier > 0
            }
            self.boat_times = {
                seat: parsed
                for seat, raw in boat.get("times", {}).items()
                if (parsed := parse_boat_time(raw)) is not None
            }
            if self.mode == "versus":
                self._first_turn_result = boat["result"]
                self.first_turn_decided = boat["decided"]
                self.boat_time_open = (
                    boat.get("stage", "date") == "time"
                    and not self.first_turn_decided
                )
            else:
                first_turn = boat.get(
                    "first_turn", {"result": None, "decided": True}
                )
                self._first_turn_result = first_turn["result"]
                self.first_turn_decided = first_turn["decided"]
                self.boat_time_open = False
            self.boat_time_followups = {}
            self._apply_seat_names()
            self.pending = {}
            self.pending_challenge = None
            self.pending_skill_tracks = None
            self.pending_prepare = None
            self.pending_bot_prepare = None
            self.pending_free_action_discard = None
            self.revision += 1
            self._run_bots()

    def _save(self) -> None:
        if self.state_path is None:
            return
        if (
            self.pending_challenge is not None
            or self.pending_skill_tracks is not None
            or self.pending_prepare is not None
            or self.pending_bot_prepare is not None
            or self.pending_free_action_discard is not None
            or self.game.pending_discard is not None
            or self.game.pending_treasure_draw is not None
            or self.game.pending_trader_draw is not None
        ):
            return
        boat = {
            "answers": {
                seat: answer.raw for seat, answer in self.boat_answers.items()
            },
            "result": self.boat_result if self.mode == "versus" else None,
            "decided": self.first_turn_decided if self.mode == "versus" else True,
            "times": {
                seat: answer.raw for seat, answer in self.boat_times.items()
            },
            "stage": (
                "time"
                if self.mode == "versus" and self.boat_time_open
                else "date"
            ),
        }
        first_turn = (
            None
            if self.mode == "versus"
            else {
                "result": self._first_turn_result,
                "decided": self.first_turn_decided,
            }
        )
        save_state(
            self.state_path,
            self.mode,
            self.game,
            AUTH_SESSIONS,
            self.seat_names,
            boat,
            first_turn,
        )

    def _apply_seat_names(self) -> None:
        if self.mode != "versus":
            return
        for seat, player in enumerate(self.game.state.players):
            player.name = self.seat_names.get(seat, f"Player {seat + 1}")

    def set_seat_name(self, seat: int, name: str) -> None:
        with self.lock:
            if self.mode != "versus":
                return
            player = self.player_for_seat(seat)
            self.seat_names[seat] = name
            player.name = name
            self.revision += 1
            self._save()

    @property
    def human(self) -> Player:
        return self.game.state.players[0]

    def player_for_seat(self, seat: int) -> Player:
        if seat not in (0, 1):
            raise ValueError("seat must be 0 or 1")
        return self.game.state.players[seat]

    def _choose_discards(self, player: Player, count: int) -> None:
        """Stage the hand-limit choice for the browser."""
        return None

    def _defer_treasure_card(self, player: Player, cards: Sequence[Card]) -> None:
        """Let the engine stage the Trader's keep choice for a later request."""
        return None

    def _defer_treasure(self, player: Player, treasures: Sequence[Treasure]) -> None:
        """Let the engine stage the reward keep choice for a later request."""
        return None

    def _choose_track(self, player: Player, tracks: tuple[str, ...]) -> str:
        selected = self.pending.get("track")
        if selected not in tracks:
            raise ValueError("invalid skill track selection")
        return selected

    def _choose_plus_two(self, player: Player, rolled: int, target: int) -> bool:
        return bool(self.pending.get("plus_two"))

    def _choose_rerolls(
        self, player: Player, rolls: tuple[int, ...], limit: int
    ) -> tuple[int, ...]:
        selected = self.pending.get("rerolls", ())
        return tuple(int(index) for index in selected[:limit])

    def _show_roll(
        self, player: Player, rolls: tuple[int, ...], bonus: int, total: int
    ) -> None:
        self.events.append(f"Roll: {rolls}; skill bonus +{bonus}; total {total}.")

    def _show_result(self, player: Player, success: bool) -> None:
        self.events.append("Success!" if success else "Failure; you gained a potion.")

    def _continue_bot_prepare(self) -> None:
        pending = self.pending_bot_prepare
        if pending is None:
            return
        player = pending["player"]
        while pending["remaining"] > 0:
            self.game.bot_prepare_one(player)
            pending["remaining"] -= 1
            if self.game.pending_discard is not None:
                return
        self.game.finish_prepare(player)
        self.pending_bot_prepare = None

    def _run_bots(self) -> None:
        if not self.first_turn_decided:
            return
        while (
            not self.game.state.game_over
            and self.game.state.players[self.game.state.current_player].is_bot
        ):
            bot = self.game.state.players[self.game.state.current_player]
            decision = self.game.bot_policy.choose(self.game.decision_context(bot))
            if decision.action == "use_potion":
                self.game.use_potion(bot, decision.potion)
            elif decision.action == "prepare":
                self.pending_bot_prepare = {
                    "player": bot,
                    "remaining": self.game.prepare_draw_count(bot),
                }
                self._continue_bot_prepare()
                if self.pending_bot_prepare is not None:
                    return
            else:
                self.pending = {"track": None, "plus_two": False, "rerolls": ()}
                self.pending_skill_tracks = None
                self.pending_challenge = self.game.begin_attempt(
                    bot, decision.encounter, decision
                )
                return
            if self.game.pending_discard is not None:
                return
            self._finish_turn()

    def _finish_turn(self) -> None:
        if self.game.state.game_over:
            return
        self.game.state.current_player = 1 - self.game.state.current_player
        self.game.state.turn_number += 1

    def _advance(self) -> None:
        """End the human's turn once no staged choice is still outstanding."""
        if self.pending_challenge is not None:
            return
        if self.pending_prepare is not None:
            return
        if self.game.pending_treasure_draw is not None:
            return
        if self.game.pending_trader_draw is not None:
            return
        if self.game.pending_discard is not None:
            return
        self._finish_turn()
        self._run_bots()

    def action(self, payload: dict[str, Any], seat: int = 0) -> None:
        with self.lock:
            self._action(payload, seat)
            self._save()

    def _action(self, payload: dict[str, Any], seat: int = 0) -> None:
        with self.lock:
            player = self.player_for_seat(seat)
            action = payload.get("action")
            if action == "new_game":
                self.new_game()
                return
            if action == "boat_time" and self.mode != "versus":
                raise ValueError("time question is unavailable in bot mode")
            if action == "boat_answer" and self.boat_time_open:
                raise ValueError("the boat date answer is no longer open")
            if not self.first_turn_decided:
                allowed = (
                    "boat_time"
                    if self.mode == "versus" and self.boat_time_open
                    else "boat_answer"
                    if self.mode == "versus"
                    else "first_turn"
                )
                if action != allowed:
                    message = (
                        "answer the boat question first"
                        if self.mode == "versus"
                        else "choose who goes first first"
                    )
                    raise ValueError(message)
            if action == "first_turn":
                if self.mode != "bot":
                    raise ValueError("first-turn choice is unavailable in versus mode")
                choice = payload.get("choice")
                if choice not in {"me", "bot"}:
                    raise ValueError("invalid first-turn choice")
                winner = 0 if choice == "me" else 1
                self.game.state.current_player = winner
                self._first_turn_result = (
                    "You chose to go first."
                    if choice == "me"
                    else "You gave the Bot the first turn."
                )
                self.first_turn_decided = True
                self.events.append(self._first_turn_result)
                self.revision += 1
                self._run_bots()
                return
            if action == "boat_answer":
                if self.mode != "versus":
                    raise ValueError("boat question is unavailable in bot mode")
                if self.first_turn_decided:
                    raise ValueError("the boat question has already been answered")
                text = _clean_text(payload.get("text"), 60)
                answer = parse_boat_answer(text, date.today())
                if answer.tier == 0:
                    raise ValueError(
                        answer.followup
                        or (
                            'I could not read that. Try a date like "6 Aug", '
                            '"two weeks ago", or "never".'
                        )
                    )
                self.boat_answers[seat] = answer
                if len(self.boat_answers) == 2:
                    first, second = (
                        self.boat_answers[0],
                        self.boat_answers[1],
                    )
                    if (
                        first.tier == 3
                        and second.tier == 3
                        and first.date == second.date
                    ):
                        self.boat_time_open = True
                    else:
                        winner, result = resolve_first_seat(
                            self.boat_answers,
                            self.game.rng,
                            {
                                index: self.game.state.players[index].name
                                for index in (0, 1)
                            },
                        )
                        self.game.state.current_player = winner
                        self.boat_result = result
                        self.first_turn_decided = True
                        self.events.append(result)
                self.revision += 1
                return
            if action == "boat_time":
                if self.first_turn_decided or not self.boat_time_open:
                    raise ValueError("the time question is not open")
                if seat in self.boat_times and seat not in self.boat_time_followups:
                    raise ValueError("you have already answered the time question")
                text = _clean_text(payload.get("text"), 60)
                parsed = parse_boat_time(text)
                if parsed is None:
                    raise ValueError(
                        'I could not read that time. Try "9am", "2:30pm", '
                        '"14:00", or "17:00 et".'
                    )
                self.boat_time_followups.pop(seat, None)
                self.boat_times[seat] = parsed
                if len(self.boat_times) == 2:
                    names = {
                        index: self.game.state.players[index].name
                        for index in (0, 1)
                    }
                    result = resolve_first_seat(
                        self.boat_answers,
                        self.game.rng,
                        names,
                        times=self.boat_times,
                    )
                    if result is None:
                        vague_seats = [
                            index
                            for index, answer in self.boat_times.items()
                            if answer.start != answer.end
                        ]
                        for index in vague_seats:
                            del self.boat_times[index]
                            self.boat_time_followups[index] = TIME_FOLLOWUP
                        self.revision += 1
                        if seat in vague_seats:
                            self._save()
                            raise ValueError(TIME_FOLLOWUP)
                        return
                    winner, explanation = result
                    self.game.state.current_player = winner
                    self.boat_result = explanation
                    self.first_turn_decided = True
                    self.boat_time_open = False
                    self.boat_time_followups = {}
                    self.events.append(explanation)
                self.revision += 1
                return
            if self.game.state.game_over:
                raise ValueError("the game is over")
            if action == "continue_bot":
                if self.mode != "bot":
                    raise ValueError("bot actions are unavailable in versus mode")
                if "revision" in payload and payload["revision"] != self.revision:
                    raise ValueError("stale bot action")
                self._resolve_bot_challenge()
                return
            if action == "continue_bot_discard":
                if self.mode != "bot":
                    raise ValueError("bot actions are unavailable in versus mode")
                if (
                    "revision" in payload
                    and payload["revision"] != self.revision
                ):
                    raise ValueError("stale bot discard action")
                self._resolve_bot_discard()
                return
            if (
                self.game.state.players[self.game.state.current_player]
                is not player
            ):
                raise ValueError("it is not your turn")
            if action in ("attempt", "prepare_start", "potion"):
                self.events.clear()
            if action == "prepare_start":
                self.pending_prepare = {
                    "player": player,
                    "remaining": self.game.prepare_draw_count(player),
                    "drawn": [],
                }
                return
            if action == "prepare_cancel":
                if self.pending_prepare is None:
                    raise ValueError("prepare has not started")
                if self.pending_prepare["player"] is not player:
                    raise ValueError("prepare belongs to the other player")
                if self.pending_prepare["drawn"]:
                    raise ValueError("prepare cannot be cancelled after a draw")
                self.pending_prepare = None
                return
            if action == "prepare_source":
                self._prepare_source(player, str(payload["source"]))
                return
            if action == "reroll":
                if self.pending_challenge is None:
                    raise ValueError("no challenge is waiting for rerolls")
                if self.pending_challenge.player is not player:
                    raise ValueError("challenge belongs to the other player")
                self.game.reroll_attempt(
                    self.pending_challenge,
                    [int(index) for index in payload.get("indices", ())],
                )
                return
            if action == "resolve":
                if (
                    self.pending_challenge is None
                    or self.pending_challenge.player is not player
                ):
                    raise ValueError("challenge belongs to the other player")
                self._resolve_challenge(player, bool(payload.get("plus_two", False)))
                return
            if action == "use_plus_two":
                if self.pending_challenge is None:
                    raise ValueError("no challenge is waiting to resolve")
                if self.pending_challenge.player is not player:
                    raise ValueError("challenge belongs to the other player")
                self.game.apply_plus_two(self.pending_challenge)
                return
            if action == "skill":
                if self.pending_challenge is None:
                    raise ValueError("no challenge is waiting for a skill choice")
                if self.pending_challenge.player is not player:
                    raise ValueError("skill choice has expired")
                if (
                    "revision" in payload
                    and payload["revision"] != self.revision
                ):
                    raise ValueError("skill choice has expired")
                if (
                    self.game.pending_treasure_draw is not None
                    or self.game.pending_trader_draw is not None
                ):
                    raise ValueError("resolve the pending treasure choice first")
                track = payload.get("track")
                known_tracks = SKILL_TRACKS.get(player.character.name, {})
                if not isinstance(track, str):
                    raise ValueError("invalid skill track selection")
                tracks = self.pending_skill_tracks
                if tracks is None:
                    if track not in known_tracks:
                        raise ValueError("invalid skill track selection")
                    tracks = tuple(
                        available_tracks(
                            player.character, player.skill_levels
                        )
                    )
                if track not in tracks:
                    if track not in known_tracks:
                        raise ValueError("invalid skill track selection")
                    raise ValueError("skill track is maxed")
                self.pending["track"] = track
                try:
                    self.game.complete_experience(player)
                finally:
                    self.pending["track"] = None
                self.pending_challenge = None
                self.pending_skill_tracks = None
                self._advance()
                return
            if action == "trader_keep":
                pending = self.game.pending_trader_draw
                if pending is None:
                    raise ValueError("no Trader draw is waiting for a card")
                if pending.player is not player:
                    raise ValueError("treasure choice belongs to the other player")
                self.game.resolve_trader_draw(pending.cards[int(payload["card"])])
                self._advance()
                return
            if action == "treasure_keep":
                pending = self.game.pending_treasure_draw
                if pending is None:
                    raise ValueError("no treasure choice is waiting")
                if pending.player is not player:
                    raise ValueError("treasure choice belongs to the other player")
                self.game.resolve_treasure_draw(
                    pending.treasures[int(payload["treasure"])]
                )
                self._advance()
                return
            if action == "discard":
                pending = self.game.pending_discard
                if pending is None:
                    raise ValueError("no discard choice is waiting")
                if pending.player is not player:
                    raise ValueError("discard belongs to the other player")
                indexes = [int(index) for index in payload.get("cards", ())]
                if len(indexes) != 1:
                    raise ValueError("select exactly one card")
                self.game.resolve_discard([pending.player.hand[indexes[0]]])
                if self.game.pending_discard is None:
                    if self.pending_prepare is not None:
                        if self.pending_prepare["remaining"] == 0:
                            self.game.finish_prepare(player)
                            self.pending_prepare = None
                            self._advance()
                    elif self.pending_free_action_discard is player:
                        self.pending_free_action_discard = None
                    else:
                        self._advance()
                return
            if action == "prepare":
                raise ValueError("prepare_source is required for each draw")
            elif action == "potion":
                potion_index = int(payload["potion"])
                self.game.use_potion(player, player.potions[potion_index])
                self.pending_free_action_discard = (
                    player if self.game.pending_discard is not None else None
                )
                return
            elif action == "attempt":
                encounter = self._encounter(payload["encounter"])
                method = str(payload["method"])
                indexes = [int(index) for index in payload.get("cards", ())]
                combo = tuple(player.hand[index] for index in indexes)
                if not is_legal(combo, method):
                    raise ValueError("selected cards do not form a legal combination")
                self.pending_skill_tracks = None
                self.pending_challenge = self.game.begin_attempt(
                    player,
                    encounter,
                    Decision("attempt", encounter, combo, method),
                )
                return
            else:
                raise ValueError("unknown action")

    def _prepare_source(self, player: Player, source: str) -> None:
        if self.pending_prepare is None:
            raise ValueError("prepare has not started")
        if self.pending_prepare["player"] is not player:
            raise ValueError("prepare belongs to the other player")
        if self.game.pending_discard is not None:
            raise ValueError("discard choice is waiting")
        if source == "deck":
            card = self.game.prepare_one(player, "deck")
        elif source.startswith("market:"):
            index = int(source.split(":", 1)[1])
            card = self.game.prepare_one(player, self.game.state.market[index])
        else:
            raise ValueError("source must be deck or market:<index>")
        self.pending_prepare["drawn"].append(serialize_card(card, -1))
        self.pending_prepare["remaining"] -= 1
        if self.game.pending_discard is not None:
            return
        if self.pending_prepare["remaining"] == 0:
            self.game.finish_prepare(player)
            self.pending_prepare = None
            self._advance()

    def _resolve_challenge(self, player: Player, use_plus_two: bool) -> None:
        if self.pending_challenge is None:
            raise ValueError("no challenge is waiting to resolve")
        if self.pending_challenge.player is not player:
            raise ValueError("challenge belongs to the other player")
        success = self.game.resolve_attempt(
            self.pending_challenge,
            use_plus_two=use_plus_two,
            advance_experience=False,
        )
        ending = success and len(player.encounters) >= 8
        if (
            success
            and available_tracks(player.character, player.skill_levels)
            and not ending
        ):
            self.pending_skill_tracks = tuple(
                available_tracks(player.character, player.skill_levels)
            )
            return
        self.pending_challenge = None
        self.pending_skill_tracks = None
        try:
            if success:
                self.game.complete_experience(player)
        finally:
            self._advance()

    def _resolve_bot_challenge(self) -> None:
        progress = self.pending_challenge
        if progress is None or not progress.player.is_bot:
            raise ValueError("no bot challenge is waiting")
        if progress.reroll_limit and not progress.rerolls_used:
            indices = self.game.bot_policy.choose_reroll_indices(
                self.game.decision_context(progress.player),
                progress.encounter,
                progress.decision.method,
                progress.rolls,
            )
            self.game.reroll_attempt(progress, indices)
        while progress.target > progress.rolled_total and any(
            potion.kind == PLUS_TWO for potion in progress.player.potions
        ):
            use_plus_two = self.game.bot_policy.choose_plus_two_after_roll(
                self.game.decision_context(progress.player),
                progress.encounter,
                progress.decision.method,
                progress.rolled_total,
            )
            if not use_plus_two:
                break
            self.game.apply_plus_two(progress)
        self.game.resolve_attempt(progress)
        self.pending_challenge = None
        if self.game.pending_discard is not None:
            return
        self._finish_turn()
        self._run_bots()

    def _resolve_bot_discard(self) -> None:
        pending = self.game.pending_discard
        if pending is None or not pending.player.is_bot:
            raise ValueError("no bot discard is waiting")
        card = self.game.bot_policy.choose_discards(
            self.game.decision_context(pending.player), 1
        )[0]
        self.game.resolve_discard([card])
        if self.game.pending_discard is not None:
            return
        if self.pending_bot_prepare is not None:
            self._continue_bot_prepare()
            if self.pending_bot_prepare is not None:
                return
        self._finish_turn()
        self._run_bots()

    def options(
        self, payload: dict[str, Any], seat: int = 0
    ) -> dict[str, dict[str, Any]]:
        with self.lock:
            player = self.player_for_seat(seat)
            encounter = self._encounter(payload["encounter"])
            indexes = [int(index) for index in payload.get("cards", ())]
            for index in indexes:
                if not 0 <= index < len(player.hand):
                    raise ValueError(f"card index {index} is out of range")
            combo = tuple(player.hand[index] for index in indexes)
            result: dict[str, dict[str, Any]] = {}
            for method in ("sneak", "steal", "strike"):
                if method == encounter.blocked_method:
                    result[method] = {"enabled": False, "reason": "blocked method"}
                elif not is_legal(combo, method):
                    result[method] = {
                        "enabled": False,
                        "reason": is_legal_reason(combo, method),
                    }
                else:
                    result[method] = {"enabled": True, "reason": ""}
            return result

    def _encounter(self, encounter_id: str) -> Encounter:
        return next(
            encounter
            for encounter in self.game.state.encounters
            if encounter.id == encounter_id
        )

    def state(self, seat: int = 0) -> dict[str, Any]:
        with self.lock:
            player = self.player_for_seat(seat)
            opponent = self.game.state.players[1 - seat]
            players = []
            for listed_player in self.game.state.players:
                serialized = serialize_player(
                    listed_player, reveal_potions=listed_player is player
                )
                serialized["score"] = self.game.score(listed_player).total
                serialized["coin_points"] = self.game.score(listed_player).coin_points
                players.append(serialized)
            holders, all_holders = trophy_holders(
                self.game.state.trophy_events,
                player_count=len(self.game.state.players),
            )
            challenge = self.pending_challenge
            if (
                challenge is not None
                and self.mode == "versus"
                and challenge.player is not player
            ):
                challenge = None
            prepare = self.pending_prepare
            if (
                prepare is not None
                and self.mode == "versus"
                and prepare["player"] is not player
            ):
                prepare = None
            trader = self.game.pending_trader_draw
            if (
                trader is not None
                and self.mode == "versus"
                and trader.player is not player
            ):
                trader = None
            treasure = self.game.pending_treasure_draw
            if (
                treasure is not None
                and self.mode == "versus"
                and treasure.player is not player
            ):
                treasure = None
            discard = self.game.pending_discard
            if (
                discard is not None
                and self.mode == "versus"
                and discard.player is not player
            ):
                discard = None
            state = {
                "turn": self.game.state.turn_number,
                "revision": self.revision,
                "mode": self.mode,
                "seat": seat,
                "seat_name": player.name,
                "opponent_name": opponent.name,
                "human_turn": self.game.state.players[self.game.state.current_player]
                is player,
                "die_faces": list(self.game.rules.die_faces),
                "game_over": self.game.state.game_over,
                "events": self.events[-12:],
                "prepare": (
                    None
                    if prepare is None
                    else {
                        "remaining": prepare["remaining"],
                        "drawn": list(prepare["drawn"]),
                    }
                ),
                "challenge": serialize_challenge(challenge),
                "discard_top": (
                    serialize_card(self.game.state.deck.discard_pile[-1], -1)
                    if self.game.state.deck.discard_pile
                    else None
                ),
                "trader": (
                    None
                    if trader is None
                    else {
                        "cards": [
                            serialize_card(card, index)
                            for index, card in enumerate(
                                trader.cards
                            )
                        ]
                    }
                ),
                "treasure": (
                    None
                    if treasure is None
                    else {
                        "treasures": [
                            serialize_treasure(treasure)
                            for treasure in treasure.treasures
                        ]
                    }
                ),
                "discard": (
                    None
                    if discard is None
                    else {"count": discard.count}
                    | {
                        "player": discard.player.name,
                        "player_is_bot": discard.player.is_bot,
                    }
                ),
                "tokens": {
                    "potions": self.game.potion_supply_count,
                    "coins": sorted(self.game.coin_supply_counts.items()),
                },
                "encounters": [
                    serialize_encounter(card) for card in self.game.state.encounters
                ],
                "hand": [
                    serialize_card(card, index)
                    for index, card in enumerate(player.hand)
                ],
                "players": players,
                "market": [
                    serialize_card(card, index)
                    for index, card in enumerate(self.game.state.market)
                ],
                "tracks": list(
                    available_tracks(player.character, player.skill_levels)
                ),
                "ladders": serialize_ladders(player),
                "trophies": {
                    kind: (
                        self.game.state.players[index].name
                        if index is not None
                        else None
                    )
                    for kind, index in holders.items()
                }
                | {
                    "all": [
                        self.game.state.players[index].name
                        for index in sorted(all_holders)
                    ]
                },
            }
            if self.mode == "versus":
                if self.first_turn_decided:
                    state["boat"] = None
                elif self.boat_time_open:
                    answer = self.boat_times.get(seat)
                    state["boat"] = {
                        "stage": "time",
                        "answered": answer is not None,
                        "mine": answer.raw if answer is not None else None,
                        "waiting": (
                            answer is not None and 1 - seat not in self.boat_times
                        ),
                        "message": self.boat_time_followups.get(seat),
                    }
                else:
                    answer = self.boat_answers.get(seat)
                    state["boat"] = {
                        "stage": "date",
                        "answered": answer is not None,
                        "mine": answer.raw if answer is not None else None,
                        "waiting": (
                            answer is not None and 1 - seat not in self.boat_answers
                        ),
                    }
                state["boat_result"] = self.boat_result
            else:
                state["first_turn"] = (
                    None
                    if self.first_turn_decided
                    else {"pending": True}
                )
                state["first_turn_result"] = self._first_turn_result
            return state


def serialize_card(card: Card, index: int) -> dict[str, Any]:
    return {
        "index": index,
        "label": "Wild" if card.wild else str(card.rank),
        "suit": card.suit,
        "rank": card.rank,
        "wild": card.wild,
    }


def serialize_treasure(treasure: Treasure) -> dict[str, str]:
    prefix = f"{treasure.color.lower()} "
    label = treasure.display_name.removeprefix(prefix)
    return {
        "label": label,
        "color": treasure.color.lower(),
        "description": treasure.description,
    }


def serialize_challenge(progress: ChallengeProgress | None) -> dict[str, Any] | None:
    if progress is None:
        return None
    if progress.resolved:
        phase = "skill" if progress.success else "done"
    elif progress.reroll_limit and not progress.rerolls_used:
        phase = "reroll"
    else:
        phase = "resolve"
    return {
        "player": progress.player.name,
        "player_is_bot": progress.player.is_bot,
        "cards": [
            serialize_card(card, index)
            for index, card in enumerate(progress.decision.combo)
        ],
        "encounter": progress.encounter.name,
        "method": progress.decision.method,
        "rolls": list(progress.rolls),
        "skill_bonus": progress.skill_bonus,
        "total": progress.rolled_total,
        "target": progress.target,
        "shortfall": max(0, progress.target - progress.rolled_total),
        "reroll_limit": progress.reroll_limit,
        "rerolls_used": progress.rerolls_used,
        "phase": phase,
        "plus_two": progress.target > progress.rolled_total
        and any(potion.kind == PLUS_TWO for potion in progress.player.potions),
        "tracks": list(
            available_tracks(progress.player.character, progress.player.skill_levels)
        ),
        "result": progress.success,
    }


def serialize_encounter(encounter: Encounter) -> dict[str, Any]:
    return {
        "id": encounter.id,
        "name": encounter.name,
        "type": encounter.encounter_type,
        "vp": encounter.victory_points,
        "icons": encounter.icons,
        "sea": encounter.is_sea,
        "mechanics": _encounter_mechanics(encounter),
        "targets": {
            method: encounter.target_for(method)
            for method in ("sneak", "steal", "strike")
        },
        "blocked": encounter.blocked_method,
    }


def serialize_player(player: Player, *, reveal_potions: bool = False) -> dict[str, Any]:
    return {
        "name": player.name,
        "character": player.character.name,
        "ability": ABILITIES.get(player.character.name, ""),
        "is_bot": player.is_bot,
        "encounters": [
            {"name": card.name, "vp": card.victory_points, "icons": card.icons}
            for card in player.encounters
        ],
        "coins": player.coins,
        "hand_count": len(player.hand),
        "hand_limit": player.hand_limit,
        "potions": (
            [potion.kind for potion in player.potions]
            if reveal_potions
            else len(player.potions)
        ),
        "treasures": [serialize_treasure(treasure) for treasure in player.treasures],
        "skills": dict(player.skill_levels),
    }


def serialize_ladders(player: Player) -> dict[str, dict[str, Any]]:
    """Describe each track as numbered steps with their bonus, reward and state."""
    ladders: dict[str, dict[str, Any]] = {}
    for track, steps in SKILL_TRACKS.get(player.character.name, {}).items():
        level = player.skill_levels.get(track, 0)
        cumulative = 0
        serialized_steps = []
        for index, step in enumerate(steps, 1):
            cumulative += step.value if isinstance(step, TrackStep) else step
            serialized_steps.append(
                {
                    "bonus": cumulative,
                    "reward": step.reward if isinstance(step, TrackStep) else None,
                    "reached": index <= level,
                }
            )
        ladders[track] = {
            "level": level,
            "steps": serialized_steps,
        }
    return ladders


HTML = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>DragonIsles</title>
<style>
:root{--bg:#101827;--text:#e8eef7;--card:#1d2a3b;--border:#40536b;--panel:#172335;--control:#26364a;--muted:#aebdd0;--tooltip:#08101d}
:root[data-theme="light"]{--bg:#f4f7fb;--text:#172335;--card:#fff;--border:#b7c4d4;--panel:#e7edf5;--control:#dbe5f0;--muted:#536579;--tooltip:#fff}
body{font:16px system-ui;margin:0;background:var(--bg);color:var(--text);transition:background .2s,color .2s}
main{max-width:1250px;margin:auto;padding:20px}.grid{display:grid;grid-template-columns:2fr 1fr;gap:18px}
.encounters{display:grid;grid-template-columns:repeat(2,1fr);gap:12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:10px;padding:14px}
.card:hover{border-color:#f5c451}.card.selected{outline:3px solid #f5c451}
.encounter{cursor:pointer}.muted{color:var(--muted)}.sea{color:#7bd3ff}.land{color:#a8e6a3}
button{background:var(--control);color:var(--text);border:1px solid var(--border);border-radius:6px;padding:8px 12px;margin:4px;cursor:pointer}button:disabled{opacity:.35;cursor:not-allowed}
.hand{display:flex;flex-wrap:wrap;gap:8px}.hand label{padding:8px;background:var(--control);border-radius:6px}.adventure-card{font-weight:700}.suit-red{color:#ef6b73}.suit-yellow{color:#e5c84b}.suit-green{color:#62c174}.suit-blue{color:#62a7ef}.suit-purple{color:#c08af2}.treasure-card{font-weight:700;cursor:help;text-decoration:underline dotted;text-underline-offset:3px}.treasure-orange{color:#f0a34b}.treasure-green{color:#62c174}.panel{background:var(--panel);padding:14px;border-radius:10px;margin-bottom:14px}
:root[data-theme="light"] .suit-red{color:#b4232d}:root[data-theme="light"] .suit-yellow{color:#8a6500}:root[data-theme="light"] .suit-green{color:#287a35}:root[data-theme="light"] .suit-blue{color:#1f5f9e}:root[data-theme="light"] .suit-purple{color:#7b3fa3}:root[data-theme="light"] .treasure-orange{color:#a85d00}:root[data-theme="light"] .treasure-green{color:#287a35}
.die{display:inline-block;min-width:34px;text-align:center;padding:6px 8px;margin:3px;background:var(--control);border-radius:6px}
.die.picked{background:#e7b94f;color:#101827;font-weight:700}
.ladder{margin:6px 0}.step{display:inline-block;padding:3px 8px;margin:3px;border-radius:6px;background:var(--control);font-size:14px}
.step.reached{background:#2f6b4f}
button.secondary{background:#4d6180;color:#e8eef7}.gap{display:inline-block;width:34px}
pre{white-space:pre-wrap}.events{max-height:180px;overflow:auto}
@media(max-width:800px){.grid{grid-template-columns:1fr}.encounters{grid-template-columns:1fr}}
</style></head>
<body><main><h1>DragonIsles <button class=secondary id=theme-toggle onclick="toggleTheme()">Use light mode</button> <button class=secondary type=button onclick="newGame()">New game</button></h1><div id="app">Loading…</div></main>
<script>
let S=null, selected=null, method=null, cards=[], rerollPicks=[], discardPicks=[], boatDraft=null, botTimer=null, requestInFlight=false, stateRevision=0, stateRequest=0;
document.addEventListener('click',e=>{
 let target=e.target.closest('button,[type="checkbox"],.card,.die');
 if(target)console.log('[DragonIsles click]',JSON.stringify({
  tag:target.tagName,
  text:(target.innerText||target.value||'').trim(),
  id:target.id||null
 }))
});
function setTheme(theme){document.documentElement.dataset.theme=theme;localStorage.setItem('dragonisles-theme',theme);document.getElementById('theme-toggle').textContent=theme==='dark'?'Use light mode':'Use dark mode'}
function toggleTheme(){setTheme(document.documentElement.dataset.theme==='dark'?'light':'dark')}
function newGame(){post('/api/action',{action:'new_game'})}
async function get(){let request=++stateRequest;let next=await (await fetch('/api/state')).json();if(request!==stateRequest)return;S=next;stateRevision++;render()}
async function post(path,body){if(body.action==='skill'&&S)body.revision=S.revision;console.log('[DragonIsles action]',JSON.stringify({path:path,body:body,stateRevision:stateRevision,turn:S&&S.turn,humanTurn:S&&S.human_turn,challenge:S&&S.challenge}));if(S&&S.game_over&&body.action!=='new_game')return;if(requestInFlight)return;requestInFlight=true;try{if(body.action==='new_game'||body.action==='skill'){clearTimeout(botTimer);botTimer=null}let r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});let d=await r.json();console.log('[DragonIsles response]',JSON.stringify({action:body.action,ok:r.ok,status:r.status,error:r.ok?null:d.error}));if(!r.ok){let boatText=body.action==='boat_answer'||body.action==='boat_time'?body.text:null;await get();if(boatText!==null){boatDraft=boatText;let input=document.getElementById('boat-answer');if(input)input.value=boatText}alert(d.error);return}if(body.action==='boat_answer'||body.action==='boat_time'||body.action==='new_game')boatDraft=null;if(body.action==='discard')discardPicks=[];selected=null;method=null;cards=[];rerollPicks=[];discardPicks=[];S=d;stateRevision++;render()}finally{requestInFlight=false}}
function esc(t){return String(t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}

function encounterHtml(){return S.encounters.map((c,i)=>`<div class="card encounter ${selected===c.id?'selected':''}"${S.game_over?'':` onclick="pick('${c.id}')"`}><b>${i+1}. ${esc(c.name)}</b> <span class="${c.sea?'sea':'land'}">${c.sea?'SEA':'LAND'}</span><br>${esc(c.type)} · ${c.vp} VP · ${c.icons} icon(s)<br><span class="muted">${esc(c.mechanics)}</span></div>`).join('')}

function cardHtml(c){return `<span class="adventure-card ${c.suit?'suit-'+c.suit:''}">${esc(c.label)}</span>`}
function treasureHtml(t){return `<span class="treasure-card treasure-${esc(t.color)}" title="${esc(t.description)}">${esc(t.label)}</span>`}
function handHtml(){let disabled=S.game_over||S.boat||S.first_turn||(!S.human_turn&&S.mode==='versus')?'disabled':'';return S.hand.map(c=>`<label><input type=checkbox ${cards.includes(c.index)?'checked':''} ${disabled} value=${c.index} onchange="toggleCard(${c.index})"> ${cardHtml(c)}</label>`).join('')}

function boatHtml(){if(S.mode!=='versus'||!S.boat)return '';
 let prompt=S.boat.stage==='time'?'You both last travelled by boat on the same day. Roughly what time of day was that? Pacific unless you add a zone — e.g. "9am", "2:30pm", "14:00", "17:00 et".':'When did you last travel by boat? The more recent answer takes the first turn.';
 if(S.boat.waiting)return `<div class=panel><b>${prompt}</b><br>Your answer: ${esc(S.boat.mine)}<br><span class=muted>Waiting for ${esc(S.opponent_name)}'s answer…</span></div>`;
 return `<div class=panel><b>${prompt}</b>${S.boat.message?`<br><span class=muted>${esc(S.boat.message)}</span>`:''}<br><input id=boat-answer type=text maxlength=60 value="${esc(boatDraft!==null?boatDraft:(S.boat.mine||''))}" oninput="boatDraft=this.value"><button onclick="submitBoat()">Submit</button></div>`}
function submitBoat(){let input=document.getElementById('boat-answer');post('/api/action',{action:S.boat.stage==='time'?'boat_time':'boat_answer',text:input.value})}
function firstTurnHtml(){if(S.mode!=='bot'||!S.first_turn)return '';
 return `<div class=panel><b>Who goes first?</b><br><button onclick="post('/api/action',{action:'first_turn',choice:'me'})">I go first</button><button onclick="post('/api/action',{action:'first_turn',choice:'bot'})">Bot goes first</button></div>`}

function challengeHtml(){let c=S.challenge;if(S.game_over||!c)return '';
 let dice=c.rolls.map((r,i)=>`<span class="die ${rerollPicks.includes(i)?'picked':''}" onclick="toggleDie(${i})">${r}</span>`).join('');
 let shownCards=c.cards.map(cardHtml).join(', ');
 let head=`<b>${esc(c.player)}'s Challenge</b>: ${shownCards}<br><b>${esc(c.encounter)}</b> by ${esc(c.method)} — target ${c.target}<br>Dice: ${dice}<br>Skill bonus +${c.skill_bonus} · total <b>${c.total}</b>${c.shortfall?` · short by ${c.shortfall}`:' · meets target'}`;
 if(c.player_is_bot)return `<div class=panel>${head}<br><span class=muted>The bot is resolving this Challenge…</span></div>`;
 if(c.phase==='reroll')return `<div class=panel>${head}<br><span class=muted>Pick up to ${c.reroll_limit} die/dice to reroll, then continue.</span><br><button onclick="post('/api/action',{action:'reroll',indices:rerollPicks})">Reroll selected</button><button onclick="rerollPicks=[];post('/api/action',{action:'reroll',indices:[]})">Keep this roll</button></div>`;
 if(c.phase==='resolve'){let plus=c.plus_two?`<button onclick="post('/api/action',{action:'use_plus_two'})">Use +2 potion</button>`:'';
  return `<div class=panel>${head}<br>${c.plus_two?'<span class=muted>A +2 potion is available; use it repeatedly if needed.</span><br>':''}${plus}<button onclick="post('/api/action',{action:'resolve',plus_two:false})">Resolve roll</button></div>`}
 if(c.phase==='skill'){let t=c.tracks.map(t=>`<button onclick="post('/api/action',{action:'skill',track:'${t}'})">${esc(t)}</button>`).join('');
  return `<div class=panel><b>Success!</b> Choose a skill track to advance:<br>${t}</div>`}
 return ''}

function prepareHtml(){let p=S.prepare;if(S.game_over||!p)return '';
 let drew=p.drawn.length?`; drew ${p.drawn.map(cardHtml).join(', ')}`:'';
 if(S.discard)return `<div class=panel><b>Prepare</b> — ${p.remaining} draw(s) left${drew}<br>Discard down to your hand limit before the next draw.</div>`;
 let market=S.market.map((m,i)=>`<button onclick="post('/api/action',{action:'prepare_source',source:'market:${i}'})">Tavern: ${cardHtml(m)}</button>`).join('');
 let cancel=p.drawn.length?'':`<button class=secondary onclick="post('/api/action',{action:'prepare_cancel'})">Cancel Prepare</button>`;
 return `<div class=panel><b>Prepare</b> — ${p.remaining} draw(s) left${p.drawn.length?`; drew ${p.drawn.map(cardHtml).join(', ')}`:''}<br><button onclick="post('/api/action',{action:'prepare_source',source:'deck'})">Draw from deck</button>${market}${cancel}</div>`}

function traderHtml(){let t=S.trader;if(S.game_over||!t)return '';
 let cards=t.cards.map((c,i)=>`<button onclick="post('/api/action',{action:'trader_keep',card:${i}})">Keep ${cardHtml(c)}</button>`).join('');
 return `<div class=panel><b>Trader treasure</b> — keep one of the three drawn cards:<br>${cards}</div>`}
function treasureChoiceHtml(){let t=S.treasure;if(S.game_over||!t)return '';
 let choices=t.treasures.map((x,i)=>`<button title="${esc(x.description)}" onclick="post('/api/action',{action:'treasure_keep',treasure:${i}})">${treasureHtml(x)}<br>Keep this</button>`).join('');
 return `<div class=panel><b>Treasure reward</b> — keep one of the two drawn treasures:<br>${choices}</div>`}

function discardHtml(){let d=S.discard;if(S.game_over||!d)return '';
 if(d.player_is_bot)return `<div class=panel><b>${esc(d.player)} is discarding</b> — ${d.count} card(s) remaining.</div>`;
 let picks=S.hand.map(c=>`<label><input type=checkbox ${discardPicks.includes(c.index)?'checked':''} onchange="toggleDiscard(${c.index})"> ${cardHtml(c)}</label>`).join('');
 return `<div class=panel><b>Choose discard</b> — select one card (${d.count} remaining):<br><div class=hand>${picks}</div><button onclick="post('/api/action',{action:'discard',cards:discardPicks})" ${discardPicks.length!==1?'disabled':''}>Discard selected</button></div>`}

function potionStatusHtml(){let me=S.players[S.seat];let kinds=me.potions.length?me.potions.join(', '):'none';
 return `<span class=muted>Potions: ${esc(kinds)}. +2 available: ${me.potions.includes('+2')?'yes':'no'}.</span>`}
function potionHtml(){let me=S.players[S.seat];if(S.game_over||S.boat||S.first_turn||!S.human_turn||!me.potions.length)return '';
 let buttons=me.potions.map((k,i)=>k==='+2'?'':`<button onclick="post('/api/action',{action:'potion',potion:${i}})">Use ${esc(k)}</button>`).join('');
 return `<div class=panel><b>Potion effects</b><br><span class=muted>+2 — during a Challenge, adds 2 to your total; usable again if you hold more than one.<br>Draw 2 — draw two cards immediately.<br>Purge — draw one card, then discard the whole Encounter row and deal a new one.</span><br>${buttons}</div>`}

function render(){
 let busy=S.challenge||S.prepare||S.treasure||S.trader||S.discard;
 let boatFocused=document.activeElement&&document.activeElement.id==='boat-answer';
 let actionDisabled=S.game_over?' disabled':'';
 if(S.boat||S.first_turn)actionDisabled=' disabled';
 if(S.mode==='versus'&&!S.human_turn)actionDisabled=' disabled';
 if(selected&&!S.encounters.some(c=>c.id===selected)){selected=null;method=null}
 let validCards=cards.filter(i=>Number.isInteger(i)&&i>=0&&i<S.hand.length);
 if(validCards.length!==cards.length){cards=validCards;method=null}
 let methods=S.game_over?'Game over':selected?['sneak','steal','strike'].map(m=>`<button id="method-${m}"${actionDisabled} onclick="chooseMethod('${m}')" disabled>${m}</button>`).join(''):'Select an encounter first';
 let players=S.players.filter(p=>!(S.mode==='bot'&&S.first_turn&&p.is_bot)).map(p=>{let potions=Array.isArray(p.potions)?esc(p.potions.join(', ')||'none'):p.potions;return `<div class=panel><b>${esc(p.name)} (${esc(p.character)})</b><br><span class=muted>${esc(p.ability)}</span>${p.score===undefined?'':`<br>Score: ${p.score} VP`}<br>Hand: ${p.hand_count} · Hand limit: ${p.hand_limit} · Coins: ${p.coins} · Potions: ${potions}<br>Skills: ${esc(JSON.stringify(p.skills))}<br>Completed: ${esc(completedText(p)||'none')}<br>Treasures: ${p.treasures.length?p.treasures.map(treasureHtml).join(', '):'none'}</div>`}).join('');
 let discardTop=S.discard_top?cardHtml(S.discard_top):'none';
 let market=S.market.map(cardHtml).join(', ');
 let tokens=S.tokens?`<div class=panel><b>Token supply</b><br>Potions left: ${S.tokens.potions} · Coins left: ${S.tokens.coins.map(c=>c[1]+'×'+c[0]).join(', ')}</div>`:'';
 document.getElementById('app').innerHTML=`<div class=grid><section>
 <div class=panel>${S.first_turn?'':`<b>Turn ${S.turn}</b>${S.boat?'':` — ${S.game_over?'Game over':(S.human_turn?'Your turn':(S.mode==='versus'?`Waiting for ${esc(S.opponent_name)}…`:'Bot turn'))}`}<br>`}<span class=muted>Playing as ${esc(S.seat_name)} · ${S.mode==='versus'?'vs Friend':'vs Bot'}</span>${S.mode==='versus'?'<br><span class=muted>This private game is for whoever has the link and passphrase.</span>':''}${S.boat_result||S.first_turn_result?`<br><span class=muted>${esc(S.boat_result||S.first_turn_result)}</span>`:''}<br>Trophies: ${esc(Object.entries(S.trophies).map(x=>x[0]+': '+(x[1]||'none')).join(' · '))}<br><span class=muted>Die faces: ${S.die_faces.join(', ')}</span></div>
 ${firstTurnHtml()}
 ${boatHtml()}
 ${S.mode==='versus'&&!S.boat&&!S.human_turn?`<div class=panel>Waiting for ${esc(S.opponent_name)}…</div>`:''}
 ${gameOverHtml()}
 <h2>Encounters</h2><div class=encounters>${encounterHtml()}</div>
 ${challengeHtml()}${treasureChoiceHtml()}${traderHtml()}${discardHtml()}${prepareHtml()}
 <h2>Your hand</h2><div class=hand>${handHtml()}</div>
 <div class=panel>${potionStatusHtml()}<br><b>Method:</b> ${methods}<br> <button id=challenge${actionDisabled} onclick="attempt()" ${!selected||!method||busy?'disabled':''}>Challenge</button>
 <span class=gap></span><button class=secondary${actionDisabled} onclick="post('/api/action',{action:'prepare_start'})" ${busy?'disabled':''}>Prepare instead</button>${potionHtml()}</div>
 <div class=panel><b>Skill ladders</b><br>${ladderHtml()}</div>
 <div class=panel><b>Events</b><pre class=events>${esc(S.events.join('\n'))}</pre></div>
 </section><aside><h2>Public state</h2>${players}<div class=panel><b>Tavern</b>: ${market}</div><div class=panel><b>Discard pile top</b>: ${discardTop}</div>${tokens}</aside></div>`;
 if(boatFocused){let input=document.getElementById('boat-answer');if(input){input.focus();input.setSelectionRange(input.value.length,input.value.length)}}
 if(S.mode==='bot'&&!S.first_turn&&S.discard&&S.discard.player_is_bot){
  let revision=stateRevision,serverRevision=S.revision;
  clearTimeout(botTimer);
  botTimer=setTimeout(()=>{if(revision===stateRevision)post('/api/action',{action:'continue_bot_discard',revision:serverRevision})},2000);
 }else if(S.mode==='bot'&&!S.first_turn&&S.challenge&&S.challenge.player_is_bot){
  let revision=stateRevision,serverRevision=S.revision;
  clearTimeout(botTimer);
  botTimer=setTimeout(()=>{if(revision===stateRevision)post('/api/action',{action:'continue_bot',revision:serverRevision})},2000);
 }else{clearTimeout(botTimer);botTimer=null}
 if(selected&&!S.boat&&!S.first_turn&&(S.mode!=='versus'||S.human_turn))refreshMethods()}

function coinPercentage(p){return p.score?p.coin_points/p.score:0}
function gameOverHtml(){if(!S.game_over)return '';
 let high=Math.max(...S.players.map(p=>p.score));
 let highCoin=Math.max(...S.players.filter(p=>p.score===high).map(coinPercentage));
 let results=S.players.map(p=>`<div>${esc(p.name)}: <b>${p.score} VP</b>${p.score===high&&coinPercentage(p)===highCoin?' — winner':''}</div>`).join('');
 return `<div class=panel><b>Final scores</b>${results}</div>`}

function ladderHtml(){return Object.entries(S.ladders).map(([track,l])=>{
 let steps=l.steps.map((s,i)=>`<span class="step ${s.reached?'reached':''}">${i+1}. +${s.bonus}${s.reward?' &rarr; '+esc(s.reward):''}</span>`).join('');
 return `<div class=ladder><b>${esc(track)}</b> <span class=muted>level ${l.level}/${l.steps.length}</span><br>${steps}</div>`}).join('')}
function completedText(p){return p.encounters.map(c=>c.name).join(', ')}
function pick(id){if(S.boat||S.first_turn||S.mode==='versus'&&!S.human_turn)return;selected=id;method=null;render()}
function chooseMethod(m){if(S.boat||S.first_turn||S.mode==='versus'&&!S.human_turn)return;method=m;refreshMethods()}
function syncChallengeButton(enabled){let b=document.getElementById('challenge');if(b)b.disabled=!enabled||!!(S.challenge||S.prepare)||(!S.human_turn&&S.mode==='versus')}
function toggleCard(i){if(S.boat||S.first_turn)return;cards=cards.includes(i)?cards.filter(x=>x!==i):cards.concat([i]);refreshMethods()}
function toggleDiscard(i){discardPicks=discardPicks.includes(i)?discardPicks.filter(x=>x!==i):discardPicks.concat([i]);render()}
function toggleDie(i){let c=S.challenge;if(!c||c.phase!=='reroll')return;
 if(rerollPicks.includes(i))rerollPicks=rerollPicks.filter(x=>x!==i);
 else if(rerollPicks.length<c.reroll_limit)rerollPicks=rerollPicks.concat([i]);
 render()}
async function refreshMethods(){if(S.boat||S.first_turn||!selected||(!S.human_turn&&S.mode==='versus'))return;
 let response,o;
 try{response=await fetch('/api/options',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({encounter:selected,cards})});o=await response.json()}catch{}
 let methods=['sneak','steal','strike'];
 if(!response||!response.ok||!o||!methods.every(m=>o[m]&&typeof o[m].enabled==='boolean')){
  for(let m of methods){let b=document.getElementById('method-'+m);if(b){b.disabled=true;b.title=''}}
  method=null;syncChallengeButton(false);return
 }
 for(let m of methods){let b=document.getElementById('method-'+m);if(b){b.disabled=!o[m].enabled;b.title=o[m].reason}}
 if(method&&!o[method].enabled)method=null;
 syncChallengeButton(!!method)}
function attempt(){if(S.boat||S.first_turn)return;rerollPicks=[];let payload={action:'attempt',encounter:selected,method,cards};cards=[];post('/api/action',payload)}
setTheme(localStorage.getItem('dragonisles-theme')||'dark');get();
setInterval(()=>{if(S&&S.mode==='versus'&&!S.human_turn)get()},2000);
setInterval(()=>{if(S&&(!S.mode||S.mode==='bot'||S.human_turn)&&!S.challenge&&!S.prepare&&!S.discard&&!S.treasure&&!S.trader)get()},3000);
</script></body></html>"""


SESSION = WebSession()
PASSPHRASE: str | None = None
AUTH_SESSIONS: dict[str, int] = {}
SECURE_COOKIE = False


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = " ".join(value.strip().split())
    return "".join(character for character in cleaned if character.isprintable())[:limit]


def _clean_name(value: Any) -> str | None:
    cleaned = _clean_text(value, 20)
    return cleaned or None


LOGIN_HTML = """<!doctype html>
<html><head><meta charset="utf-8"><title>DragonIsles</title></head>
<body><main><h1>DragonIsles</h1>
<p>This private game is for whoever has the link and passphrase.</p>
<form onsubmit="join(event)">
<label>Your name <input name="name" type="text" maxlength="20"></label>
<label>Passphrase <input name="passphrase" type="password" autofocus></label>
<button type="submit">Join game</button>
</form><p id="error"></p></main>
<script>
async function join(event){event.preventDefault();let name=event.target.elements.name.value,passphrase=event.target.elements.passphrase.value;
 let response=await fetch('/api/join',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name,passphrase})});
 if(response.ok)location.href='/';else{let message='Unable to join game.';try{let body=await response.json();if(body.error==='both seats are taken')message='This game already has two players.';else if(body.error==='invalid passphrase')message='That passphrase is not correct.'}catch{}document.getElementById('error').textContent=message}
}
</script></body></html>"""


def configure(
    mode: str,
    passphrase: str | None,
    secure_cookie: bool = False,
    state_path: Path | None = None,
) -> None:
    global PASSPHRASE, SECURE_COOKIE
    with SESSION.lock:
        loaded = load_state(state_path) if state_path is not None else None
        SESSION.state_path = None
        AUTH_SESSIONS.clear()
        if loaded is not None and loaded[0] == mode:
            SESSION.state_path = state_path
            SESSION.restore(mode, loaded[1], loaded[3], loaded[4])
            AUTH_SESSIONS.update(loaded[2])
        else:
            SESSION.seat_names = {}
            SESSION.new_game(mode)
            SESSION.state_path = state_path
            SESSION._save()
        PASSPHRASE = passphrase
        SECURE_COOKIE = secure_cookie


class Handler(BaseHTTPRequestHandler):
    def _cookie_token(self) -> str | None:
        cookies = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookies.get("dragonisles_session")
        return morsel.value if morsel is not None else None

    def _seat(self) -> int | None:
        if PASSPHRASE is None:
            return 0
        token = self._cookie_token()
        if token is None:
            return None
        with SESSION.lock:
            return AUTH_SESSIONS.get(token)

    def _require_seat(self) -> int | None:
        seat = self._seat()
        if seat is None:
            self.send_json({"error": "authentication required"}, HTTPStatus.FORBIDDEN)
        return seat

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/" and self._seat() is None:
            self.send_html(LOGIN_HTML)
            return
        if path.startswith("/api/"):
            seat = self._require_seat()
            if seat is None:
                return
            if path == "/api/state":
                self.send_json(SESSION.state(seat))
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_html(HTML)

    def send_html(self, body: str) -> None:
        data = body.encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length) or "{}")
            path = urlparse(self.path).path
            if path == "/api/join":
                self._join(payload)
                return
            seat = self._require_seat()
            if seat is None:
                return
            if path == "/api/options":
                body = SESSION.options(payload, seat)
            elif path == "/api/action":
                with SESSION.lock:
                    SESSION.action(payload, seat)
                SESSION.revision += 1
                body = SESSION.state(seat)
            else:
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            self.send_json(body)
        except (KeyError, ValueError, IndexError, StopIteration) as exc:
            self.send_json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)

    def _join(self, payload: dict[str, Any]) -> None:
        if PASSPHRASE is None:
            self.send_json({"seat": 0})
            return
        supplied = payload.get("passphrase", "")
        if not isinstance(supplied, str) or not hmac.compare_digest(
            supplied.encode(), PASSPHRASE.encode()
        ):
            self.send_json({"error": "invalid passphrase"}, HTTPStatus.FORBIDDEN)
            return
        token = self._cookie_token()
        name = _clean_name(payload.get("name"))
        with SESSION.lock:
            seat = AUTH_SESSIONS.get(token) if token is not None else None
            if seat is None:
                if SESSION.mode == "versus":
                    assigned = set(AUTH_SESSIONS.values())
                    available = next(
                        (candidate for candidate in (0, 1) if candidate not in assigned),
                        None,
                    )
                    if available is None:
                        self.send_json(
                            {"error": "both seats are taken"},
                            HTTPStatus.FORBIDDEN,
                        )
                        return
                    seat = available
                else:
                    seat = 0
                token = secrets.token_urlsafe(32)
                AUTH_SESSIONS[token] = seat
            if SESSION.mode == "versus" and name is not None:
                SESSION.set_seat_name(seat, name)
            else:
                SESSION._save()
        self.send_json(
            {"seat": seat},
            cookie=(
                "dragonisles_session="
                f"{token}; HttpOnly; SameSite=Lax; Path=/"
                + ("; Secure" if SECURE_COOKIE else "")
            ),
        )

    def send_json(
        self,
        body: dict[str, Any],
        status: HTTPStatus = HTTPStatus.OK,
        *,
        cookie: str | None = None,
    ) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: object) -> None:
        return


def main(argv: Sequence[str] | None = None) -> None:
    parser = ArgumentParser(description="Play DragonIsles in a web browser.")
    parser.add_argument(
        "--port", type=int, default=int(os.environ.get("PORT", "8000"))
    )
    parser.add_argument(
        "--passphrase", default=os.environ.get("DRAGONISLES_PASSPHRASE")
    )
    parser.add_argument("--mode", choices=("bot", "versus"), default="bot")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--secure-cookie",
        action="store_true",
        default=bool(os.environ.get("DRAGONISLES_SECURE_COOKIE")),
    )
    parser.add_argument("--state-file", default=os.environ.get("DRAGONISLES_STATE_FILE"))
    args = parser.parse_args(argv)
    if args.mode == "versus" and args.passphrase is None:
        args.passphrase = secrets.token_urlsafe(24)
        print(f"Passphrase: {args.passphrase}", flush=True)
    configure(
        args.mode,
        args.passphrase,
        args.secure_cookie,
        Path(args.state_file) if args.state_file else None,
    )
    try:
        server = ThreadingHTTPServer((args.host, args.port), Handler)
    except OSError as exc:
        raise SystemExit(
            f"Port {args.port} is unavailable ({exc}). "
            f"Try: python3 -m dragonisles.web --port {args.port + 1}"
        ) from exc
    print(f"DragonIsles web UI: http://{args.host}:{args.port}", flush=True)
    if args.mode == "versus":
        print(
            f"Share this link and passphrase: "
            f"http://{args.host}:{args.port}/",
            flush=True,
        )
    server.serve_forever()


if __name__ == "__main__":
    main()
