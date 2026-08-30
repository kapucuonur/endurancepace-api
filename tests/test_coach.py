"""Coaching endpoints — role gate, roster, assignment, snapshot."""

from __future__ import annotations

import pytest

from tests.conftest import auth_headers

COACH_EMAIL = "coach@x.com"


@pytest.fixture()
def as_coach(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "coach_emails", COACH_EMAIL)


def _coach_headers(client):
    return auth_headers(client, email=COACH_EMAIL)


def test_role_in_athlete_payload(client, as_coach):
    ch = _coach_headers(client)
    ah = auth_headers(client, email="athlete@x.com")

    assert client.get("/me/snapshot", headers=ch).json()["athlete"]["role"] == "coach"
    assert client.get("/me/snapshot", headers=ah).json()["athlete"]["role"] == "athlete"


def test_non_coach_is_forbidden(client, as_coach):
    ah = auth_headers(client, email="athlete@x.com")
    assert client.get("/coach/athletes", headers=ah).status_code == 403


def test_assign_and_athlete_sees_it(client, as_coach):
    ch = _coach_headers(client)
    ah = auth_headers(client, email="athlete@x.com")

    roster = client.get("/coach/athletes", headers=ch).json()
    target = next(a for a in roster if a["email"] == "athlete@x.com")

    body = {
        "planId": None,
        "date": "2026-09-01",
        "sport": "run",
        "title": "Coach — tempo 4x5",
        "structure": [],
        "plannedDuration": 2700,
        "plannedTss": 60,
        "status": "planned",
    }
    created = client.post(
        f"/coach/athletes/{target['id']}/workouts", headers=ch, json=body
    ).json()
    assert created["source"] == "coach"
    assert created["assignedById"] is not None

    mine = client.get("/me/snapshot", headers=ah).json()["workouts"]
    w = next(x for x in mine if x["title"] == "Coach — tempo 4x5")
    assert w["source"] == "coach" and w["status"] == "planned"

    # coach can read that athlete's snapshot
    seen = client.get(
        f"/coach/athletes/{target['id']}/snapshot", headers=ch
    ).json()["workouts"]
    assert any(x["id"] == created["id"] for x in seen)


def test_edit_and_withdraw_only_own_assignments(client, as_coach):
    ch = _coach_headers(client)
    ah = auth_headers(client, email="athlete@x.com")
    target_id = client.get("/coach/athletes", headers=ch).json()[0]["id"]

    assigned = client.post(
        f"/coach/athletes/{target_id}/workouts",
        headers=ch,
        json={
            "planId": None,
            "date": "2026-09-02",
            "sport": "bike",
            "title": "Coach — endurance",
            "structure": [],
            "plannedDuration": 3600,
            "plannedTss": 70,
            "status": "planned",
        },
    ).json()

    # a workout the athlete built themselves is off-limits to the coach
    own = client.post(
        "/workouts",
        headers=ah,
        json={
            "planId": None,
            "date": "2026-09-03",
            "sport": "run",
            "title": "My own run",
            "structure": [],
            "plannedDuration": 1800,
            "plannedTss": 30,
            "status": "planned",
        },
    ).json()
    assert (
        client.patch(
            f"/coach/athletes/{target_id}/workouts/{own['id']}",
            headers=ch,
            json={"title": "hijacked"},
        ).status_code
        == 404
    )

    edited = client.patch(
        f"/coach/athletes/{target_id}/workouts/{assigned['id']}",
        headers=ch,
        json={"title": "Coach — endurance v2", "plannedTss": 75},
    ).json()
    assert edited["title"] == "Coach — endurance v2" and edited["plannedTss"] == 75

    assert (
        client.delete(
            f"/coach/athletes/{target_id}/workouts/{assigned['id']}", headers=ch
        ).status_code
        == 204
    )
    remaining = client.get("/me/snapshot", headers=ah).json()["workouts"]
    assert all(x["id"] != assigned["id"] for x in remaining)
