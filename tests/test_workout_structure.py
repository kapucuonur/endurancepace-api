"""Step fields added for the builder: strength exercises and bike speed."""

from __future__ import annotations

from tests.conftest import auth_headers


def _workout(structure):
    return {
        "planId": None,
        "date": "2026-11-01",
        "sport": "strength",
        "title": "Leg day",
        "structure": structure,
        "plannedDuration": 1800,
        "plannedTss": 30,
        "status": "planned",
    }


def test_exercise_and_speed_survive_round_trip(client):
    h = auth_headers(client)
    structure = [
        {
            "id": "st_1",
            "type": "steady",
            "repeatCount": 1,
            "children": [],
            "target": {"rpe": 7},
            "exercise": {"key": "back_squat", "sets": 4, "reps": 8, "weightKg": 60, "restSec": 120},
        },
        {
            "id": "st_2",
            "type": "steady",
            "repeatCount": 1,
            "children": [],
            "duration": {"kind": "distance", "meters": 40000, "speedKmh": 30},
            "target": {"hrZone": 2},
        },
    ]
    created = client.post("/workouts", headers=h, json=_workout(structure))
    assert created.status_code == 201
    wid = created.json()["id"]

    got = next(w for w in client.get("/me/snapshot", headers=h).json()["workouts"] if w["id"] == wid)
    assert got["structure"][0]["exercise"] == {
        "key": "back_squat",
        "sets": 4,
        "reps": 8,
        "weightKg": 60,
        "restSec": 120,
    }
    assert got["structure"][1]["duration"]["speedKmh"] == 30


def test_bad_exercise_rejected(client):
    h = auth_headers(client)
    bad = [
        {
            "id": "st_1",
            "type": "steady",
            "repeatCount": 1,
            "children": [],
            "exercise": {"key": "<script>", "sets": 99, "reps": 8},
        }
    ]
    assert client.post("/workouts", headers=h, json=_workout(bad)).status_code == 422


def test_old_steps_without_new_fields_still_valid(client):
    h = auth_headers(client)
    old = [
        {
            "id": "st_1",
            "type": "steady",
            "repeatCount": 1,
            "children": [],
            "duration": {"kind": "time", "seconds": 600},
            "target": {"hrZone": 2},
        }
    ]
    created = client.post("/workouts", headers=h, json=_workout(old))
    assert created.status_code == 201
    step = created.json()["structure"][0]
    assert step["exercise"] is None
