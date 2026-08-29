"""Best-effort import of training metrics from a connected Garmin account.

Garmin exposes different data per account and watch model, so every value is
optional. Two come back clean; the run threshold pace is derived from the 10K
race prediction because Garmin's `lactateThresholdSpeed` field is unreliable
(stale firstbeat units on many accounts).

Split from `client.py` so the raw garminconnect surface stays in one module.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, TypeVar

from app.garmin.client import GarminClient

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _safe(fn: Callable[[], T]) -> T | None:
    try:
        return fn()
    except Exception as exc:  # noqa: BLE001 — every Garmin call is best-effort
        logger.info("garmin metrics: %s failed: %s", getattr(fn, "__name__", fn), exc)
        return None


def athlete_metrics(client: GarminClient) -> dict[str, Any]:
    """Returns `{"thresholds": {...}, "insights": {...}}`.

    `thresholds` keys line up with the app's ThresholdValues (only the fields
    Garmin could supply). `insights` is display-only passthrough — never fed
    into a calculation.
    """
    profile = _safe(client.get_profile) or {}
    user = profile.get("userData", {}) if isinstance(profile, dict) else {}
    ftp = _safe(client.get_cycling_ftp) or {}
    races = _safe(client.get_race_predictions) or {}

    thresholds: dict[str, float] = {}
    if ftp.get("functionalThresholdPower"):
        thresholds["ftpWatts"] = round(ftp["functionalThresholdPower"])
    if user.get("lactateThresholdHeartRate"):
        thresholds["thresholdHr"] = round(user["lactateThresholdHeartRate"])
    if races.get("time10K"):
        # 10K race pace is a good proxy for run threshold pace.
        thresholds["runThresholdPaceSecPerKm"] = round(races["time10K"] / 10)

    insights: dict[str, Any] = {}
    if user.get("vo2MaxRunning"):
        insights["vo2MaxRunning"] = user["vo2MaxRunning"]
    if user.get("vo2MaxCycling"):
        insights["vo2MaxCycling"] = user["vo2MaxCycling"]
    predictions = {
        k: races[k]
        for k in ("time5K", "time10K", "timeHalfMarathon", "timeMarathon")
        if isinstance(races, dict) and races.get(k)
    }
    if predictions:
        insights["racePredictions"] = predictions

    return {"thresholds": thresholds, "insights": insights}
