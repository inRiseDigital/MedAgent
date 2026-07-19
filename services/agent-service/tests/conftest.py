"""Test fixtures for agent-service."""

from __future__ import annotations

import pytest
from fastapi import FastAPI

from app.config import Settings
from app.main import create_app


@pytest.fixture()
def app() -> FastAPI:
    return create_app(Settings(auth_disabled=True))
