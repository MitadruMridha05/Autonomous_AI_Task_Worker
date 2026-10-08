import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.seed import reset_db


@pytest.fixture
def db_path(tmp_path, monkeypatch):
    """A fresh, seeded SQLite file for every test, so tests never see each other's state."""
    path = str(tmp_path / "test.db")
    monkeypatch.setenv("OPSPILOT_DB", path)
    reset_db(path)
    return path


@pytest.fixture
def http(db_path):
    from app.main import app

    with TestClient(app) as client:  # TestClient is an httpx.Client, so the agent's API client can use it directly
        yield client


@pytest.fixture
def query(db_path):
    """Run SQL straight against the test DB: ground truth that bypasses the app and the agent."""
    def _query(sql, params=()):
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in conn.execute(sql, params)]
        finally:
            conn.close()
    return _query


@pytest.fixture
def live_server(db_path):
    from .helpers import LiveServer

    with LiveServer() as server:
        yield server
