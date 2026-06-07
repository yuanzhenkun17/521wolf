"""Uvicorn entrypoint for the UI backend."""

from ui.backend.app import app, create_app

__all__ = ["app", "create_app"]

