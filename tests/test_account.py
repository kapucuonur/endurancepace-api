"""Account deletion — password gate, full data removal, coach/message cleanup."""

from __future__ import annotations

import pytest

from app.models import Athlete, Message, User, Workout
from tests.conftest import auth_headers

COACH_EMAIL = "coach@x.com"
PASSWORD = "pw12345678"


@pytest.fixture()
def as_coach(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "coach_emails", COACH_EMAIL)


def _delete(client, headers, password=PASSWORD):
    return client.request(
        "DELETE", "/auth/account", headers=headers, json={"password": password}
    )


def _athlete_id(client, headers) -> str:
    return client.get("/me/snapshot", headers=headers).json()["athlete"]["id"]


def test_wrong_password_keeps_account(client):
    h = auth_headers(client)
    assert _delete(client, h, password="nope").status_code == 403
    assert client.get("/me/snapshot", headers=h).status_code == 200


def test_requires_auth(client):
    r = client.request("DELETE", "/auth/account", json={"password": PASSWORD})
    assert r.status_code in (401, 403)


def test_delete_removes_user_and_data(client, db_sessionmaker):
    h = auth_headers(client)
    created = client.post(
        "/workouts",
        headers=h,
        json={
            "planId": None,
            "date": "2026-09-01",
            "sport": "run",
            "title": "Easy run",
            "structure": [],
            "plannedDuration": 1800,
            "plannedTss": 25,
            "status": "planned",
        },
    )
    assert created.status_code == 201

    assert _delete(client, h).status_code == 204

    # Old token is dead and the email can't log in any more.
    assert client.get("/me/snapshot", headers=h).status_code == 401
    login = client.post("/auth/login", json={"email": "a@b.com", "password": PASSWORD})
    assert login.status_code == 401

    db = db_sessionmaker()
    try:
        assert db.query(User).count() == 0
        assert db.query(Athlete).count() == 0
        assert db.query(Workout).count() == 0
    finally:
        db.close()


def test_deleting_coach_keeps_athletes_workouts_and_drops_messages(
    client, db_sessionmaker, as_coach
):
    ch = auth_headers(client, email=COACH_EMAIL)
    ah = auth_headers(client, email="athlete@x.com")
    athlete_id = _athlete_id(client, ah)

    client.post(
        f"/coach/athletes/{athlete_id}/workouts",
        headers=ch,
        json={
            "planId": None,
            "date": "2026-09-01",
            "sport": "run",
            "title": "Coach — tempo",
            "structure": [],
            "plannedDuration": 2700,
            "plannedTss": 60,
            "status": "planned",
        },
    )
    client.post(f"/messages/with/{athlete_id}", headers=ch, json={"body": "Hi"})

    assert _delete(client, ch).status_code == 204

    mine = client.get("/me/snapshot", headers=ah).json()["workouts"]
    assigned = next(w for w in mine if w["title"] == "Coach — tempo")
    assert assigned["assignedById"] is None
    assert client.get("/messages/threads", headers=ah).json() == []

    db = db_sessionmaker()
    try:
        assert db.query(Message).count() == 0
    finally:
        db.close()
