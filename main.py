"""Hosted application entrypoint."""

from fastapi import FastAPI

from app import app as _app

app = FastAPI(title="DragonIsles")
app.mount("/", _app)

__all__ = ["app"]
