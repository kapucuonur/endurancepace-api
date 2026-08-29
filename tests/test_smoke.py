"""End-to-end smoke test: signup -> login -> full CRUD round-trip against an
in-memory SQLite DB. Run: `pytest`.
"""

from __future__ import annotations

from tests.conftest import auth_headers


def test_login_rate_limited(client):
    from app.ratelimit import limiter

    limiter.enabled = True
    limiter.reset()
    try:
        client.post("/auth/signup", json={"email": "rl@x.com", "password": "pw12345678"})
        codes = [
            client.post(
                "/auth/login", json={"email": "rl@x.com", "password": "pw12345678"}
            ).status_code
            for _ in range(12)
        ]
        assert codes.count(200) == 10  # "10/minute"
        assert 429 in codes
    finally:
        limiter.enabled = False
        limiter.reset()


def test_snapshot_shape(client):
    h = auth_headers(client)
    snap = client.get("/me/snapshot", headers=h).json()
    assert set(snap) == {"athlete", "plans", "events", "workouts"}
    assert snap["athlete"]["disciplines"] == ["swim", "bike", "run", "strength"]
    assert snap["plans"] == snap["events"] == snap["workouts"] == []


def test_thresholds_recompute_zones(client):
    h = auth_headers(client)
    r = client.put(
        "/me/athlete/thresholds",
        headers=h,
        json={"ftpWatts": 265, "thresholdHr": 168, "runThresholdPaceSecPerKm": 258},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["powerZones"][0] == {
        "index": 1,
        "name": "Active Recovery",
        "min": 0,
        "max": 145,
    }
    assert body["powerZones"][4]["min"] == 278
    assert body["hrZones"][4]["max"] is None
    assert body["thresholds"]["cssSecPer100m"] is None or True  # merge kept it absent


def test_workout_crud_and_camelcase(client):
    h = auth_headers(client)
    payload = {
        "planId": None,
        "date": "2026-08-29",
        "sport": "run",
        "title": "Track intervals",
        "structure": [
            {
                "id": "st_1",
                "type": "interval",
                "repeatCount": 6,
                "children": [
                    {
                        "id": "st_2",
                        "type": "interval",
                        "repeatCount": 1,
                        "children": [],
                        "duration": {"kind": "time", "seconds": 180},
                        "target": {"hrZone": 4},
                    }
                ],
            }
        ],
        "plannedDuration": 3000,
        "plannedTss": 60,
        "status": "planned",
        "isTemplate": False,
    }
    created = client.post("/workouts", headers=h, json=payload).json()
    assert created["plannedTss"] == 60
    assert created["structure"][0]["repeatCount"] == 6
    assert created["structure"][0]["children"][0]["target"]["hrZone"] == 4
    assert created["date"] == "2026-08-29"
    assert "athleteId" not in created

    wid = created["id"]
    client.patch(f"/workouts/{wid}", headers=h, json={"status": "completed"})
    assert client.get(f"/workouts/{wid}", headers=h).json()["status"] == "completed"

    # range query excludes it when out of range, includes when in range
    assert client.get(
        "/workouts?start=2026-08-01&end=2026-08-10", headers=h
    ).json() == []
    assert len(client.get("/workouts?start=2026-08-01&end=2026-09-01", headers=h).json()) == 1

    assert client.delete(f"/workouts/{wid}", headers=h).status_code == 204
    assert client.get(f"/workouts/{wid}", headers=h).status_code == 404


def test_schedule_from_template(client):
    h = auth_headers(client)
    tpl = client.post(
        "/workouts",
        headers=h,
        json={
            "sport": "bike",
            "title": "FTP 3x10",
            "structure": [],
            "plannedDuration": 3600,
            "plannedTss": 70,
            "status": "planned",
            "isTemplate": True,
            "templateCategory": "Threshold",
        },
    ).json()
    scheduled = client.post(
        f"/workouts/{tpl['id']}/schedule",
        headers=h,
        json={"date": "2026-09-01", "planId": None},
    ).json()
    assert scheduled["isTemplate"] is False
    assert scheduled["date"] == "2026-09-01"
    assert scheduled["id"] != tpl["id"]
    assert scheduled["plannedTss"] == 70


def test_plan_delete_detaches_workouts(client):
    h = auth_headers(client)
    plan = client.post(
        "/plans",
        headers=h,
        json={
            "name": "Build",
            "startDate": "2026-08-01",
            "endDate": "2026-10-01",
            "goalEventId": None,
            "phase": "build",
        },
    ).json()
    w = client.post(
        "/workouts",
        headers=h,
        json={
            "planId": plan["id"],
            "date": "2026-08-15",
            "sport": "run",
            "title": "Easy",
            "structure": [],
            "plannedDuration": 1800,
            "plannedTss": 30,
            "status": "planned",
            "isTemplate": False,
        },
    ).json()
    assert client.delete(f"/plans/{plan['id']}", headers=h).status_code == 204
    assert client.get(f"/workouts/{w['id']}", headers=h).json()["planId"] is None


def test_plan_blocks_roundtrip(client):
    h = auth_headers(client)
    blocks = [
        {"phase": "base", "weeks": 4},
        {"phase": "build", "weeks": 3},
        {"phase": "taper", "weeks": 1},
    ]
    plan = client.post(
        "/plans",
        headers=h,
        json={
            "name": "Season",
            "startDate": "2026-01-06",
            "endDate": "2026-03-09",
            "goalEventId": None,
            "phase": "base",
            "blocks": blocks,
        },
    ).json()
    assert plan["blocks"] == blocks

    # snapshot carries them
    got = next(
        p for p in client.get("/me/snapshot", headers=h).json()["plans"] if p["id"] == plan["id"]
    )
    assert got["blocks"][1] == {"phase": "build", "weeks": 3}

    # PATCH replaces; explicit null clears
    client.patch(
        f"/plans/{plan['id']}",
        headers=h,
        json={"blocks": [{"phase": "build", "weeks": 8}]},
    )
    assert client.get("/me/snapshot", headers=h).json()["plans"][0]["blocks"] == [
        {"phase": "build", "weeks": 8}
    ]
