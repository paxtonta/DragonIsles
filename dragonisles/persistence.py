"""Atomic persistence for a DragonIsles game and its web sessions."""

from __future__ import annotations

import os
import pickle
import sys
from pathlib import Path
from typing import Any

from .engine import Game


FORMAT_VERSION = 1


def save(
    path: Path,
    mode: str,
    game: Game,
    auth: dict[str, int],
    names: dict[int, str] | None = None,
    boat: dict[str, Any] | None = None,
) -> None:
    """Atomically save a game and its authentication seats."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    interaction = game.interaction
    try:
        game.interaction = None
        payload = {
            "version": FORMAT_VERSION,
            "mode": mode,
            "game": game,
            "auth": dict(auth),
            "names": dict(names or {}),
            "boat": boat
            if boat is not None
            else {"answers": {}, "result": None, "decided": True},
        }
        with temporary.open("wb") as stream:
            pickle.dump(payload, stream, protocol=5)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        game.interaction = interaction


def load(
    path: Path,
) -> tuple[str, Game, dict[str, int], dict[int, str], dict[str, Any]] | None:
    """Load a persisted game, returning None for any invalid state."""
    try:
        with path.open("rb") as stream:
            payload: Any = pickle.load(stream)
        if not isinstance(payload, dict):
            raise ValueError("state is not a mapping")
        if payload.get("version") != FORMAT_VERSION:
            raise ValueError("unsupported state version")
        mode = payload["mode"]
        game = payload["game"]
        auth = payload["auth"]
        names = payload.get("names", {})
        boat = payload.get(
            "boat", {"answers": {}, "result": None, "decided": True}
        )
        if mode not in {"bot", "versus"} or not isinstance(game, Game):
            raise ValueError("invalid state fields")
        if (
            not isinstance(auth, dict)
            or any(
                not isinstance(token, str) or seat not in (0, 1)
                for token, seat in auth.items()
            )
        ):
            raise ValueError("invalid authentication state")
        if (
            not isinstance(names, dict)
            or any(
                type(seat) is not int
                or seat not in (0, 1)
                or not isinstance(name, str)
                for seat, name in names.items()
            )
        ):
            raise ValueError("invalid player names")
        if (
            not isinstance(boat, dict)
            or not isinstance(boat.get("answers"), dict)
            or any(
                type(seat) is not int
                or seat not in (0, 1)
                or not isinstance(answer, str)
                for seat, answer in boat["answers"].items()
            )
            or not isinstance(boat.get("decided"), bool)
            or not (
                boat.get("result") is None
                or isinstance(boat.get("result"), str)
            )
        ):
            raise ValueError("invalid boat state")
        return (
            mode,
            game,
            dict(auth),
            dict(names),
            {
                "answers": dict(boat["answers"]),
                "result": boat["result"],
                "decided": boat["decided"],
            },
        )
    except Exception:
        print("DragonIsles state load failed; starting a new game.", file=sys.stderr)
        return None
