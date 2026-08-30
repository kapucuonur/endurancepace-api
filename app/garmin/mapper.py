"""Garmin activity JSON -> EndurancePace Workout fields.

TSS policy (see README / earlier discussion):
  completed.actualTss = Garmin trainingStressScore   (power/HR-derived, best)
                      | HR-ratio estimate            (hours * (avgHR/LTHR)^2 * 100)
                      | null
`workout_metrics.compute_workout_metrics` is NOT used here — imported activities
have no `structure`, so it would return 0.
"""

from __future__ import annotations

from typing import Any, Optional

from app.config import settings

_SPORTS = {"swim", "bike", "run", "strength"}


def map_sport(activity: dict) -> Optional[str]:
    at = activity.get("activityType") or {}
    type_key = (at.get("typeKey") if isinstance(at, dict) else str(at)) or ""
    type_key = type_key.lower()
    for needle, sport in settings.garmin_sport_rules:
        if needle in type_key and sport in _SPORTS:
            return sport
    return None


def _num(*values: Any) -> Optional[float]:
    for v in values:
        if isinstance(v, (int, float)) and v == v:  # not NaN
            return float(v)
    return None


def _iso_z(garmin_ts: Optional[str]) -> Optional[str]:
    """'2026-04-03 12:02:40' (GMT) -> '2026-04-03T12:02:40.000Z'."""
    if not garmin_ts:
        return None
    s = garmin_ts.strip().replace("T", " ")[:19]
    if len(s) < 10:
        return None
    day, _, clock = s.partition(" ")
    clock = clock or "00:00:00"
    return f"{day}T{clock}.000Z"


def tss_source(activity: dict) -> str:
    """Diagnostic: which branch of resolve_actual_tss would fire."""
    if _num(activity.get("trainingStressScore")):
        return "garmin"
    if _num(activity.get("averageHR"), activity.get("averageHeartRate")):
        return "hr_estimate"
    return "none"


def resolve_actual_tss(activity: dict, thresholds: dict) -> Optional[int]:
    garmin_tss = _num(activity.get("trainingStressScore"))
    if garmin_tss and garmin_tss > 0:
        return round(garmin_tss)

    avg_hr = _num(activity.get("averageHR"), activity.get("averageHeartRate"))
    lthr = _num((thresholds or {}).get("thresholdHr"))
    duration = _num(activity.get("duration"), activity.get("elapsedDuration"))
    if avg_hr and lthr and lthr > 0 and duration:
        intensity = avg_hr / lthr
        return round((duration / 3600) * intensity * intensity * 100)
    return None


def actuals_from_activity(activity: dict) -> dict:
    """The measured numbers Garmin reports for an activity. Only keys with a
    real, positive value come back, so `completed` stays as lean as the
    manual-log shape (date / durationSeconds / actualTss / rpe / notes)."""
    out: dict[str, float] = {}

    pairs = (
        ("distanceMeters", _num(activity.get("distance"))),
        ("avgSpeedMps", _num(activity.get("averageSpeed"), activity.get("avgSpeed"))),
        ("avgHr", _num(activity.get("averageHR"), activity.get("averageHeartRate"))),
        ("maxHr", _num(activity.get("maxHR"), activity.get("maxHeartRate"))),
        (
            "elevationGainM",
            _num(activity.get("elevationGain"), activity.get("totalElevationGain")),
        ),
        (
            "avgCadence",
            _num(
                activity.get("averageRunningCadenceInStepsPerMinute"),
                activity.get("averageBikingCadenceInRevPerMinute"),
                activity.get("averageCadence"),
            ),
        ),
        ("avgPower", _num(activity.get("avgPower"), activity.get("averagePower"))),
        ("calories", _num(activity.get("calories"))),
    )
    for key, value in pairs:
        if value and value > 0:
            # sub-integer precision only matters for speed and cadence
            out[key] = round(value, 3) if key in ("avgSpeedMps", "avgCadence") else round(value)
    return out


def activity_to_workout_fields(activity: dict, athlete) -> Optional[dict]:
    """Returns the persist-ready field dict, or None if the sport is unmapped."""
    sport = map_sport(activity)
    if sport is None:
        return None

    duration = _num(activity.get("duration"), activity.get("elapsedDuration")) or 0
    start_local = activity.get("startTimeLocal") or activity.get("startTimeGMT")
    day = (start_local or "")[:10] or None
    actual_tss = resolve_actual_tss(activity, athlete.thresholds or {})

    completed = {"date": _iso_z(activity.get("startTimeGMT") or start_local) or day}
    if duration:
        completed["durationSeconds"] = round(duration)
    if actual_tss is not None:
        completed["actualTss"] = actual_tss
    completed.update(actuals_from_activity(activity))

    return {
        "external_id": str(activity.get("activityId")),
        "sport": sport,
        "title": activity.get("activityName") or f"{sport.title()} — Garmin",
        "date": day,
        "planned_duration": round(duration),
        # new imports: planned == actual so week totals aren't zero; when matched
        # to an existing planned workout the caller keeps that plannedTss.
        "planned_tss": actual_tss if actual_tss is not None else 0,
        "status": "completed",
        "completed": completed,
        "source": "garmin",
    }


def pick_match(candidates: list, activity: dict):
    """Tie-break when several planned workouts share date+sport: closest by
    duration, else the earliest-created. Returns the chosen row or None."""
    if not candidates:
        return None
    if len(candidates) == 1:
        return candidates[0]
    target = _num(activity.get("duration"), activity.get("elapsedDuration")) or 0
    if target:
        return min(candidates, key=lambda w: abs((w.planned_duration or 0) - target))
    return min(candidates, key=lambda w: w.created_at or "")
