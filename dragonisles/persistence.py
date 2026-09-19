"""Atomic persistence for a DragonIsles game and its web sessions."""

from __future__ import annotations

import os
import pickle
import json
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .engine import Game


FORMAT_VERSION = 1
BLOB_API_URL = "https://vercel.com/api/blob"
BLOB_PATH = "dragonisles/state.pkl"


def _payload(
    mode: str,
    game: Game,
    auth: dict[str, int],
    names: dict[int, str] | None,
    boat: dict[str, Any] | None,
    first_turn: dict[str, Any] | None,
    metadata: dict[str, Any] | None,
) -> bytes:
    interaction = game.interaction
    try:
        game.interaction = None
        payload: dict[str, Any] = {
            "version": FORMAT_VERSION,
            "mode": mode,
            "game": game,
            "auth": dict(auth),
            "names": dict(names or {}),
            "boat": boat
            if boat is not None
            else {
                "choices": {},
                "stage": "choice",
                "result": None,
                "decided": True,
            },
        }
        if first_turn is not None:
            payload["first_turn"] = first_turn
        if metadata is not None:
            payload["metadata"] = metadata
        return pickle.dumps(payload, protocol=5)
    finally:
        game.interaction = interaction


def _blob_token() -> str | None:
    return os.environ.get("BLOB_READ_WRITE_TOKEN") or os.environ.get(
        "VERCEL_BLOB_READ_WRITE_TOKEN"
    )


def blob_enabled() -> bool:
    return _blob_token() is not None


def _blob_store_id(token: str) -> str:
    parts = token.split("_")
    if len(parts) < 4 or parts[0:3] != ["vercel", "blob", "rw"]:
        raise ValueError("invalid Vercel Blob token")
    return parts[3]


def _blob_request(
    method: str,
    url: str,
    token: str,
    *,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[bytes, dict[str, str]]:
    request_headers = {
        "Authorization": f"Bearer {token}",
        "x-api-version": "12",
        "x-vercel-blob-store-id": _blob_store_id(token),
    }
    request_headers.update(headers or {})
    request = urllib.request.Request(
        url, data=body, headers=request_headers, method=method
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return response.read(), dict(response.headers.items())


def load_blob() -> tuple[bytes, str] | None:
    """Load the authoritative snapshot and its ETag from Vercel Blob."""
    token = _blob_token()
    if token is None:
        return None
    blob_path = os.environ.get("DRAGONISLES_BLOB_PATH", BLOB_PATH)
    query = urllib.parse.urlencode({"limit": "1", "prefix": blob_path})
    metadata_raw, _ = _blob_request(
        "GET", f"{BLOB_API_URL}?{query}", token
    )
    metadata = json.loads(metadata_raw)
    blobs = metadata.get("blobs", [])
    if not blobs:
        return None
    blob = blobs[0]
    content, headers = _blob_request("GET", blob["downloadUrl"], token)
    return content, blob.get("etag") or headers.get("etag", "")


def save_blob(content: bytes, etag: str | None = None) -> str:
    """Atomically replace the authoritative snapshot in Vercel Blob."""
    token = _blob_token()
    if token is None:
        raise RuntimeError("Vercel Blob credentials are not configured")
    blob_path = os.environ.get("DRAGONISLES_BLOB_PATH", BLOB_PATH)
    headers = {
        "x-vercel-blob-access": "private",
        "x-allow-overwrite": "true",
        "x-content-type": "application/octet-stream",
    }
    if etag:
        headers["x-if-match"] = etag
    response_body, response_headers = _blob_request(
        "PUT",
        f"{BLOB_API_URL}/?{urllib.parse.urlencode({'pathname': blob_path})}",
        token,
        body=content,
        headers=headers,
    )
    if response_headers.get("etag"):
        return response_headers["etag"]
    try:
        return str(json.loads(response_body).get("etag", ""))
    except (TypeError, ValueError):
        return ""


def save(
    path: Path,
    mode: str,
    game: Game,
    auth: dict[str, int],
    names: dict[int, str] | None = None,
    boat: dict[str, Any] | None = None,
    first_turn: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    """Atomically save a game and its authentication seats."""
    temporary = path.with_suffix(path.suffix + ".tmp")
    payload = _payload(mode, game, auth, names, boat, first_turn, metadata)
    try:
        with temporary.open("wb") as stream:
            stream.write(payload)
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


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
            "boat",
            {
                "answers": {},
                "times": {},
                "stage": "date",
                "result": None,
                "decided": True,
            },
        )
        first_turn = payload.get(
            "first_turn", {"result": None, "decided": True}
        )
        if mode not in {"bot", "versus", "solo"} or not isinstance(game, Game):
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
        new_choices = isinstance(boat, dict) and "choices" in boat and isinstance(
            boat.get("choices"), dict
        )
        old_answers = isinstance(boat, dict) and "answers" in boat and isinstance(
            boat.get("answers"), dict
        )
        if (
            not isinstance(boat, dict)
            or not (new_choices or old_answers)
            or (
                new_choices
                and any(
                    type(seat) is not int
                    or seat not in (0, 1)
                    or type(choice) is not int
                    or choice not in (0, 1)
                    for seat, choice in boat.get("choices", {}).items()
                )
            )
            or (
                old_answers
                and any(
                    type(seat) is not int
                    or seat not in (0, 1)
                    or not isinstance(answer, str)
                    for seat, answer in boat.get("answers", {}).items()
                )
            )
            or (
                old_answers
                and (
                    not isinstance(boat.get("times", {}), dict)
                    or any(
                        type(seat) is not int
                        or seat not in (0, 1)
                        or not isinstance(raw, str)
                        for seat, raw in boat.get("times", {}).items()
                    )
                )
            )
            or (
                not new_choices
                and boat.get("stage", "date") not in {"date", "time"}
            )
            or not isinstance(boat.get("decided"), bool)
            or not (
                boat.get("result") is None
                or isinstance(boat.get("result"), str)
            )
        ):
            raise ValueError("invalid boat state")
        if (
            not isinstance(first_turn, dict)
            or not isinstance(first_turn.get("decided"), bool)
            or not (
                first_turn.get("result") is None
                or isinstance(first_turn.get("result"), str)
            )
        ):
            raise ValueError("invalid first-turn state")
        normalized_boat = {
            "choices": dict(boat.get("choices", {})) if new_choices else {},
            "stage": "choice",
            "result": boat["result"],
            "decided": boat["decided"],
        }
        if mode == "bot":
            normalized_boat["first_turn"] = {
                "result": first_turn["result"],
                "decided": first_turn["decided"],
            }
        return (
            mode,
            game,
            dict(auth),
            dict(names),
            normalized_boat,
        )
    except Exception:
        print("DragonIsles state load failed; starting a new game.", file=sys.stderr)
        return None


def load_bytes(
    content: bytes,
) -> tuple[
    str,
    Game,
    dict[str, int],
    dict[int, str],
    dict[str, Any],
    dict[str, Any],
] | None:
    """Load a snapshot from bytes, including optional session metadata."""
    try:
        payload: Any = pickle.loads(content)
        if not isinstance(payload, dict) or payload.get("version") != FORMAT_VERSION:
            raise ValueError("unsupported state")
        mode, game, auth, names, boat = _load_payload(payload)
        return mode, game, auth, names, boat, dict(payload.get("metadata", {}))
    except Exception:
        return None


def _load_payload(
    payload: dict[str, Any],
) -> tuple[str, Game, dict[str, int], dict[int, str], dict[str, Any]]:
    mode = payload["mode"]
    game = payload["game"]
    auth = payload["auth"]
    names = payload.get("names", {})
    boat = payload.get(
        "boat",
        {"choices": {}, "stage": "choice", "result": None, "decided": True},
    )
    first_turn = payload.get("first_turn", {"result": None, "decided": True})
    if mode not in {"bot", "versus", "solo"} or not isinstance(game, Game):
        raise ValueError("invalid state fields")
    if not isinstance(auth, dict) or any(
        not isinstance(token, str) or seat not in (0, 1)
        for token, seat in auth.items()
    ):
        raise ValueError("invalid authentication state")
    if not isinstance(names, dict) or any(
        type(seat) is not int
        or seat not in (0, 1)
        or not isinstance(name, str)
        for seat, name in names.items()
    ):
        raise ValueError("invalid player names")
    if not isinstance(boat, dict) or not isinstance(boat.get("choices", {}), dict):
        raise ValueError("invalid boat state")
    if not isinstance(first_turn, dict):
        raise ValueError("invalid first-turn state")
    normalized_boat = {
        "choices": dict(boat.get("choices", {})),
        "stage": "choice",
        "result": boat.get("result"),
        "decided": bool(boat.get("decided", True)),
    }
    if mode == "bot":
        normalized_boat["first_turn"] = {
            "result": first_turn.get("result"),
            "decided": bool(first_turn.get("decided", True)),
        }
    return mode, game, dict(auth), dict(names), normalized_boat
