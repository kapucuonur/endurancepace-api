"""Garmin sync tests — GarminClient is mocked, no real network calls."""

from __future__ import annotations

import math

import pytest

from app.garmin import ingest
from app.garmin.client import LoginOutcome
from app.garmin.mapper import (
    actuals_from_activity,
    map_sport,
    pick_match,
    resolve_actual_tss,
)
from app.garmin.profile import athlete_metrics
from app.sanitize import sanitize_for_json
from tests.conftest import auth_headers

RUN = {
    "activityId": 111,
    "activityName": "Morning Run",
    "startTimeLocal": "2026-08-28 07:00:00",
    "startTimeGMT": "2026-08-28 05:00:00",
    "duration": 2400.0,
    "distance": 8000.0,
    "averageSpeed": 3.333,
    "averageHR": 150,
    "maxHR": 172,
    "elevationGain": 96.0,
    "averageRunningCadenceInStepsPerMinute": 168,
    "calories": 620,
    "trainingStressScore": 55,
    "activityType": {"typeKey": "running"},
}
WALK = {
    "activityId": 222,
    "activityName": "Evening Walk",
    "startTimeLocal": "2026-08-28 18:00:00",
    "duration": 1800.0,
    "activityType": {"typeKey": "walking"},
}
BIKE_NO_TSS = {
    "activityId": 333,
    "activityName": "Zwift",
    "startTimeLocal": "2026-08-27 19:00:00",
    "startTimeGMT": "2026-08-27 17:00:00",
    "duration": 3600.0,
    "averageHR": 140,
    "activityType": {"typeKey": "indoor_cycling"},
}


class FakeClient:
    def __init__(self, activities):
        self._activities = activities

    def get_activities(self, limit):
        return list(self._activities)[:limit]


def _mock_authed(monkeypatch, activities):
    async def _fake(db, athlete):
        return FakeClient(activities)

    monkeypatch.setattr(ingest, "get_authed_client", _fake)


# --- unit: mapper / sanitize ------------------------------------------------


def test_map_sport():
    assert map_sport({"activityType": {"typeKey": "trail_running"}}) == "run"
    assert map_sport({"activityType": {"typeKey": "virtual_ride"}}) == "bike"
    assert map_sport({"activityType": {"typeKey": "lap_swimming"}}) == "swim"
    assert map_sport({"activityType": {"typeKey": "walking"}}) is None


def test_resolve_actual_tss_priority():
    # Garmin's own number wins
    assert resolve_actual_tss(RUN, {"thresholdHr": 170}) == 55
    # HR fallback: 1h * (140/150)^2 * 100
    assert resolve_actual_tss(BIKE_NO_TSS, {"thresholdHr": 150}) == 87
    # nothing usable
    assert resolve_actual_tss(BIKE_NO_TSS, {}) is None


def test_actuals_from_activity():
    a = actuals_from_activity(RUN)
    assert a["distanceMeters"] == 8000
    assert a["avgSpeedMps"] == 3.333
    assert a["avgHr"] == 150 and a["maxHr"] == 172
    assert a["elevationGainM"] == 96
    assert a["avgCadence"] == 168
    assert a["calories"] == 620
    # nothing measured -> empty, and zero / missing values are dropped
    assert actuals_from_activity({"distance": 0, "averageHR": None}) == {}


def test_pick_match_closest_duration():
    class W:
        def __init__(self, d, c):
            self.planned_duration = d
            self.created_at = c

    a, b = W(1800, "1"), W(3600, "2")
    assert pick_match([a, b], {"duration": 3400}) is b
    assert pick_match([], {"duration": 100}) is None


def test_sanitize_for_json():
    out = sanitize_for_json({"a": float("nan"), "b": [float("inf"), 1], "c": "x"})
    assert out == {"a": None, "b": [None, 1], "c": "x"}


# --- api: connect / status / mfa ------------------------------------------


def test_status_not_connected(client):
    h = auth_headers(client)
    body = client.get("/me/garmin/status", headers=h).json()
    assert body == {
        "connected": False,
        "garminEmail": None,
        "state": "not_connected",
        "displayName": None,
        "lastSyncAt": None,
        "lastVerifiedAt": None,
        "cooldownRemaining": 0,
        "lastError": None,
    }


def test_connect_direct(client, monkeypatch):
    h = auth_headers(client)
    monkeypatch.setattr(
        "app.garmin.client.GarminClient.login_fresh",
        lambda self: LoginOutcome("ok", tokens_blob="B" * 600, display_name="Alex R"),
    )
    monkeypatch.setattr("app.garmin.client.GarminClient.dump_to_disk", lambda self: None)

    r = client.post(
        "/me/garmin/connect",
        headers=h,
        json={"garminEmail": "g@x.com", "garminPassword": "secret"},
    )
    assert r.json() == {"status": "connected"}
    st = client.get("/me/garmin/status", headers=h).json()
    assert st["connected"] and st["state"] == "active" and st["garminEmail"] == "g@x.com"


def test_connect_mfa_flow(client, monkeypatch):
    h = auth_headers(client)
    monkeypatch.setattr(
        "app.garmin.client.GarminClient.login_fresh",
        lambda self: LoginOutcome("mfa_required", mfa_client_state={"csrf": "abc"}),
    )
    r1 = client.post(
        "/me/garmin/connect",
        headers=h,
        json={"garminEmail": "g@x.com", "garminPassword": "secret"},
    )
    assert r1.json() == {"status": "mfa_required"}
    assert client.get("/me/garmin/status", headers=h).json()["state"] == "mfa_pending"

    monkeypatch.setattr(
        "app.garmin.client.GarminClient.complete_mfa",
        classmethod(
            lambda cls, email, pw, state, code: LoginOutcome(
                "ok", tokens_blob="B" * 600, display_name="Alex R"
            )
        ),
    )
    monkeypatch.setattr("app.garmin.client.GarminClient.dump_to_disk", lambda self: None)
    r2 = client.post("/me/garmin/connect/mfa", headers=h, json={"mfaCode": "123456"})
    assert r2.json() == {"status": "connected"}
    assert client.get("/me/garmin/status", headers=h).json()["state"] == "active"


def test_mfa_expired(client, monkeypatch):
    h = auth_headers(client)
    monkeypatch.setattr(
        "app.garmin.client.GarminClient.login_fresh",
        lambda self: LoginOutcome("mfa_required", mfa_client_state={"csrf": "abc"}),
    )
    client.post(
        "/me/garmin/connect",
        headers=h,
        json={"garminEmail": "g@x.com", "garminPassword": "secret"},
    )
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "garmin_mfa_ttl_seconds", -1)
    r = client.post("/me/garmin/connect/mfa", headers=h, json={"mfaCode": "123456"})
    assert r.status_code == 400 and "expired" in r.json()["detail"].lower()


# --- api: sync ------------------------------------------------------------


def _connect(client, h, monkeypatch):
    monkeypatch.setattr(
        "app.garmin.client.GarminClient.login_fresh",
        lambda self: LoginOutcome("ok", tokens_blob="B" * 600, display_name="Alex R"),
    )
    monkeypatch.setattr("app.garmin.client.GarminClient.dump_to_disk", lambda self: None)
    client.post(
        "/me/garmin/connect",
        headers=h,
        json={"garminEmail": "g@x.com", "garminPassword": "secret"},
    )


def test_sync_imports_and_dedups(client, monkeypatch):
    h = auth_headers(client)
    _connect(client, h, monkeypatch)
    _mock_authed(monkeypatch, [RUN, WALK])

    r1 = client.post("/me/garmin/sync?days=60", headers=h).json()
    assert r1["imported"] == 1 and r1["skipped"] == 1

    workouts = client.get("/me/snapshot", headers=h).json()["workouts"]
    w = next(x for x in workouts if x["date"] == "2026-08-28")
    assert w["sport"] == "run" and w["status"] == "completed"
    assert w["completed"]["actualTss"] == 55
    assert w["completed"]["durationSeconds"] == 2400
    assert w["completed"]["distanceMeters"] == 8000
    assert w["completed"]["avgHr"] == 150
    assert w["completed"]["maxHr"] == 172
    assert w["completed"]["elevationGainM"] == 96
    assert w["completed"]["avgCadence"] == 168
    assert w["completed"]["calories"] == 620
    assert w["plannedTss"] == 55
    assert w["source"] == "garmin"

    # bump the min-interval so the 2nd sync isn't debounced
    import app.config as cfg

    monkeypatch.setattr(cfg.settings, "garmin_sync_min_interval_seconds", 0)
    r2 = client.post("/me/garmin/sync?days=60", headers=h).json()
    assert r2["imported"] == 0 and r2["updated"] == 1


def test_sync_matches_planned_workout(client, monkeypatch):
    h = auth_headers(client)
    _connect(client, h, monkeypatch)

    planned = client.post(
        "/workouts",
        headers=h,
        json={
            "planId": None,
            "date": "2026-08-28",
            "sport": "run",
            "title": "Planned easy run",
            "structure": [],
            "plannedDuration": 2400,
            "plannedTss": 40,
            "status": "planned",
            "isTemplate": False,
        },
    ).json()

    _mock_authed(monkeypatch, [RUN])
    res = client.post("/me/garmin/sync?days=60", headers=h).json()
    assert res["matched"] == 1 and res["imported"] == 0

    got = client.get(f"/workouts/{planned['id']}", headers=h).json()
    assert got["status"] == "completed"
    assert got["plannedTss"] == 40  # structured estimate preserved
    assert got["completed"]["actualTss"] == 55  # Garmin actual attached


def test_sync_debounced(client, monkeypatch):
    h = auth_headers(client)
    _connect(client, h, monkeypatch)
    _mock_authed(monkeypatch, [RUN])
    assert client.post("/me/garmin/sync?days=60", headers=h).json()["status"] == "ok"
    r2 = client.post("/me/garmin/sync?days=60", headers=h).json()
    assert r2["status"] == "skipped" and r2["reason"] == "too_soon"


def test_disconnect(client, monkeypatch):
    h = auth_headers(client)
    _connect(client, h, monkeypatch)
    assert client.delete("/me/garmin/connect", headers=h).status_code == 204
    assert client.get("/me/garmin/status", headers=h).json()["connected"] is False


# --- threshold import ------------------------------------------------------


class MetricsClient:
    def get_profile(self):
        return {
            "userData": {
                "lactateThresholdHeartRate": 177,
                "lactateThresholdSpeed": 0.364,  # deliberately ignored
                "vo2MaxRunning": 57.0,
                "vo2MaxCycling": 56.0,
            }
        }

    def get_cycling_ftp(self):
        return {"functionalThresholdPower": 259}

    def get_race_predictions(self):
        return {"time5K": 1050, "time10K": 2200, "timeHalfMarathon": 4892}


def test_athlete_metrics_maps_and_derives():
    out = athlete_metrics(MetricsClient())
    assert out["thresholds"] == {
        "ftpWatts": 259,
        "thresholdHr": 177,
        "runThresholdPaceSecPerKm": 220,  # 2200 / 10, not from lactateThresholdSpeed
    }
    assert out["insights"]["vo2MaxRunning"] == 57.0
    assert out["insights"]["racePredictions"]["time10K"] == 2200


def test_athlete_metrics_tolerates_missing_data():
    class Empty:
        def get_profile(self):
            return None

        def get_cycling_ftp(self):
            raise RuntimeError("garmin 500")

        def get_race_predictions(self):
            return {}

    out = athlete_metrics(Empty())
    assert out == {"thresholds": {}, "insights": {}}


def test_garmin_thresholds_endpoint(client, monkeypatch):
    h = auth_headers(client)
    _connect(client, h, monkeypatch)

    async def _fake(db, athlete):
        return MetricsClient()

    monkeypatch.setattr("app.routers.garmin.garmin_auth.get_authed_client", _fake)
    body = client.get("/me/garmin/thresholds", headers=h).json()
    assert body["thresholds"] == {
        "ftpWatts": 259,
        "thresholdHr": 177,
        "runThresholdPaceSecPerKm": 220,
    }
    assert body["insights"]["vo2MaxCycling"] == 56.0
