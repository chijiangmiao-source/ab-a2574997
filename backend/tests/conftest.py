"""Pytest fixtures for the audit API."""
import os
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.main import app, _STORE  # noqa: E402


@pytest.fixture()
def client():
    _STORE.clear()
    with TestClient(app) as c:
        yield c
    _STORE.clear()
