"""FastAPI entrypoint for the hosted multiplayer game."""

from __future__ import annotations

import hmac
import json
import os
import secrets
from http import HTTPStatus
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from dragonisles import web


def _cookie_token(request: Request) -> str | None:
    cookies = SimpleCookie(request.headers.get("cookie", ""))
    morsel = cookies.get("dragonisles_session")
    return morsel.value if morsel is not None else None


def _seat(request: Request) -> int | None:
    if web.PASSPHRASE is None:
        return 0
    token = _cookie_token(request)
    if token is None:
        return None
    with web.SESSION.lock:
        return web.AUTH_SESSIONS.get(token)


def _cookie_header(token: str) -> str:
    return f"dragonisles_session={token}; HttpOnly; SameSite=Lax; Path=/; Secure"


def _join(payload: dict[str, Any], request: Request) -> JSONResponse:
    if web.PASSPHRASE is None:
        return JSONResponse({"seat": 0})
    supplied = payload.get("passphrase", "")
    if not isinstance(supplied, str) or not hmac.compare_digest(
        supplied.encode(), web.PASSPHRASE.encode()
    ):
        return JSONResponse(
            {"error": "invalid passphrase"}, status_code=HTTPStatus.FORBIDDEN
        )
    token = _cookie_token(request)
    name = web._clean_name(payload.get("name"))
    with web.SESSION.lock:
        seat = web.AUTH_SESSIONS.get(token) if token is not None else None
        if seat is None:
            assigned = set(web.AUTH_SESSIONS.values())
            seat = next(
                (candidate for candidate in (0, 1) if candidate not in assigned),
                None,
            )
            if seat is None:
                return JSONResponse(
                    {"error": "both seats are taken"},
                    status_code=HTTPStatus.FORBIDDEN,
                )
            token = secrets.token_urlsafe(32)
            web.AUTH_SESSIONS[token] = seat
        if name is not None:
            web.SESSION.set_seat_name(seat, name)
        else:
            web.SESSION._save()
    response = JSONResponse({"seat": seat})
    response.headers["Set-Cookie"] = _cookie_header(token)
    return response


def _error(message: str, status: int = HTTPStatus.FORBIDDEN) -> JSONResponse:
    return JSONResponse({"error": message}, status_code=status)


def _configure() -> None:
    mode = os.environ.get("DRAGONISLES_MODE", "versus")
    passphrase = os.environ.get("DRAGONISLES_PASSPHRASE")
    if mode != "versus":
        passphrase = None
    if mode == "versus" and passphrase is None:
        raise RuntimeError(
            "DRAGONISLES_PASSPHRASE must be configured for versus mode"
        )
    state_file = os.environ.get("DRAGONISLES_STATE_FILE")
    if state_file is None and Path("/data").is_dir():
        state_file = "/data/dragonisles-state.json"
    web.configure(
        mode,
        passphrase,
        secure_cookie=True,
        state_path=Path(state_file) if state_file else None,
    )


_configure()
app = FastAPI(title="DragonIsles")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    if _seat(request) is None:
        return HTMLResponse(web.LOGIN_HTML)
    return HTMLResponse(web.HTML)


@app.get("/api/state")
async def state(request: Request) -> JSONResponse:
    seat = _seat(request)
    if seat is None:
        return _error("authentication required")
    return JSONResponse(web.SESSION.state(seat))


@app.post("/api/join")
async def join(request: Request) -> JSONResponse:
    try:
        payload = json.loads(await request.body() or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        return _join(payload, request)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        return _error(str(exc), HTTPStatus.BAD_REQUEST)


@app.post("/api/options")
async def options(request: Request) -> JSONResponse:
    return await _action_request(request, "options")


@app.post("/api/action")
async def action(request: Request) -> JSONResponse:
    return await _action_request(request, "action")


async def _action_request(request: Request, action_name: str) -> JSONResponse:
    seat = _seat(request)
    if seat is None:
        return _error("authentication required")
    try:
        payload = json.loads(await request.body() or b"{}")
        if not isinstance(payload, dict):
            raise ValueError("request body must be an object")
        if action_name == "options":
            body = web.SESSION.options(payload, seat)
        else:
            with web.SESSION.lock:
                web.SESSION.action(payload, seat)
            web.SESSION.revision += 1
            body = web.SESSION.state(seat)
        return JSONResponse(body)
    except (
        KeyError,
        ValueError,
        IndexError,
        StopIteration,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        return _error(str(exc), HTTPStatus.BAD_REQUEST)
