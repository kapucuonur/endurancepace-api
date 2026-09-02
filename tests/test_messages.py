"""Direct messages — permission rules, threads, unread count, read-on-open."""

from __future__ import annotations

import pytest

from tests.conftest import auth_headers

COACH_EMAIL = "coach@x.com"


@pytest.fixture()
def as_coach(monkeypatch):
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "coach_emails", COACH_EMAIL)


def _athlete_id(client, headers) -> str:
    return client.get("/me/snapshot", headers=headers).json()["athlete"]["id"]


def test_coach_messages_athlete_and_athlete_replies(client, as_coach):
    ch = auth_headers(client, email=COACH_EMAIL)
    ah = auth_headers(client, email="athlete@x.com")
    coach_id = _athlete_id(client, ch)
    athlete_id = _athlete_id(client, ah)

    sent = client.post(
        f"/messages/with/{athlete_id}", headers=ch, json={"body": "How did the run feel?"}
    )
    assert sent.status_code == 201
    assert sent.json()["senderId"] == coach_id
    assert sent.json()["recipientId"] == athlete_id
    assert sent.json()["readAt"] is None

    # Athlete sees one unread and one thread.
    assert client.get("/messages/unread-count", headers=ah).json()["count"] == 1
    threads = client.get("/messages/threads", headers=ah).json()
    assert len(threads) == 1
    assert threads[0]["partner"]["id"] == coach_id
    assert threads[0]["partner"]["role"] == "coach"
    assert threads[0]["unreadCount"] == 1
    assert threads[0]["lastMessage"]["body"] == "How did the run feel?"

    # Opening the conversation marks incoming messages read.
    convo = client.get(f"/messages/with/{coach_id}", headers=ah).json()
    assert [m["body"] for m in convo["messages"]] == ["How did the run feel?"]
    assert client.get("/messages/unread-count", headers=ah).json()["count"] == 0

    # Athlete can now reply (already talking).
    reply = client.post(
        f"/messages/with/{coach_id}", headers=ah, json={"body": "Legs were heavy"}
    )
    assert reply.status_code == 201

    coach_convo = client.get(f"/messages/with/{athlete_id}", headers=ch).json()
    assert [m["body"] for m in coach_convo["messages"]] == [
        "How did the run feel?",
        "Legs were heavy",
    ]


def test_athlete_cannot_cold_message_a_coach(client, as_coach):
    ch = auth_headers(client, email=COACH_EMAIL)
    ah = auth_headers(client, email="athlete@x.com")
    coach_id = _athlete_id(client, ch)

    r = client.post(
        f"/messages/with/{coach_id}", headers=ah, json={"body": "hi coach"}
    )
    assert r.status_code == 403


def test_athlete_may_message_coach_who_assigned_a_workout(client, as_coach):
    ch = auth_headers(client, email=COACH_EMAIL)
    ah = auth_headers(client, email="athlete@x.com")
    coach_id = _athlete_id(client, ch)
    athlete_id = _athlete_id(client, ah)

    client.post(
        f"/coach/athletes/{athlete_id}/workouts",
        headers=ch,
        json={
            "planId": None,
            "date": "2026-09-05",
            "sport": "run",
            "title": "Coach — easy",
            "structure": [],
            "plannedDuration": 1800,
            "plannedTss": 25,
            "status": "planned",
        },
    )

    r = client.post(
        f"/messages/with/{coach_id}", headers=ah, json={"body": "thanks!"}
    )
    assert r.status_code == 201


def test_empty_and_oversized_bodies_rejected(client, as_coach):
    ch = auth_headers(client, email=COACH_EMAIL)
    ah = auth_headers(client, email="athlete@x.com")
    athlete_id = _athlete_id(client, ah)

    assert (
        client.post(
            f"/messages/with/{athlete_id}", headers=ch, json={"body": "   "}
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/messages/with/{athlete_id}", headers=ch, json={"body": "x" * 4001}
        ).status_code
        == 422
    )


def test_messaging_requires_auth(client):
    assert client.get("/messages/threads").status_code in (401, 403)
