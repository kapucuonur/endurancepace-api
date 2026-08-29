"""Shared test fixtures: in-memory SQLite + a signed-up/logged-in client."""

from __future__ import annotations

import os

import pytest

# Must be set before app.config imports.
os.environ.setdefault(
    "ENDURANCEPACE_FIELD_ENCRYPT_KEY", "MDEyMzQ1Njc4OWFiY2RlZjAxMjM0NTY3ODlhYmNkZWY="
)
os.environ.setdefault("ENDURANCEPACE_RATELIMIT_ENABLED", "false")

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.database import Base, get_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def db_sessionmaker():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)


@pytest.fixture(autouse=True)
def _clear_mfa_registry():
    from app.garmin import mfa_registry

    mfa_registry._PENDING.clear()
    yield
    mfa_registry._PENDING.clear()


@pytest.fixture()
def client(db_sessionmaker):
    def _get_db():
        db = db_sessionmaker()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def auth_headers(client, email="a@b.com"):
    client.post("/auth/signup", json={"email": email, "password": "pw12345678"})
    token = client.post(
        "/auth/login", json={"email": email, "password": "pw12345678"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}
