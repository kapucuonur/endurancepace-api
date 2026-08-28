"""Planned duration + TSS estimate — a port of src/domain/workout.ts.

Only used by the seed script, so the seeded `plannedTss` / `plannedDuration`
match what the app computes. At runtime these values are computed client-side
and the API just persists them (see models.py).
"""

from __future__ import annotations

import math
from typing import Optional

ZONE_IF = [0.55, 0.7, 0.83, 0.95, 1.1]
PACE_FALLBACK_IF = 0.8
WATTS_FALLBACK_IF = 0.85
BIKE_IF_RANGE = (0.3, 1.5)
ENDURANCE_IF_RANGE = (0.3, 1.3)
DEFAULT_SPEED_MPS = {"swim": 1.1, "bike": 8.3, "run": 3.3, "strength": 0}


def _round(n: float) -> int:
    return math.floor(n + 0.5)


def _clamp(n: float, lo_hi: tuple[float, float]) -> float:
    lo, hi = lo_hi
    return min(hi, max(lo, n))


def _midpoint(rng: dict) -> float:
    return (rng["min"] + rng["max"]) / 2


def _if_from_target(target: Optional[dict], sport: str, thresholds: dict) -> float:
    if not target:
        return 0.6
    if target.get("hrZone"):
        return ZONE_IF[target["hrZone"] - 1]
    if target.get("powerZone"):
        return ZONE_IF[target["powerZone"] - 1]
    if target.get("powerWatts"):
        ftp = thresholds.get("ftpWatts")
        if not ftp:
            return WATTS_FALLBACK_IF
        return _clamp(_midpoint(target["powerWatts"]) / ftp, BIKE_IF_RANGE)
    if target.get("paceTarget"):
        pace = target["paceTarget"]
        mid = _midpoint(pace)
        if mid <= 0:
            return PACE_FALLBACK_IF
        threshold = (
            thresholds.get("cssSecPer100m")
            if pace.get("unit") == "sec_per_100m"
            else thresholds.get("runThresholdPaceSecPerKm")
        )
        if not threshold:
            return PACE_FALLBACK_IF
        return _clamp(threshold / mid, ENDURANCE_IF_RANGE)
    if isinstance(target.get("rpe"), (int, float)):
        return min(1.15, target["rpe"] / 10)
    return 0.6


def _step_seconds(step: dict, sport: str) -> float:
    duration = step.get("duration")
    if not duration:
        return 0
    if duration["kind"] == "time":
        return duration["seconds"]
    pace = (step.get("target") or {}).get("paceTarget")
    meters = duration["meters"]
    if pace:
        mid = _midpoint(pace)
        return (meters / 100) * mid if pace.get("unit") == "sec_per_100m" else (meters / 1000) * mid
    speed = DEFAULT_SPEED_MPS.get(sport) or 3
    return meters / speed


def _flatten(structure: list[dict], sport: str, thresholds: dict) -> list[dict]:
    out: list[dict] = []

    def visit(step: dict) -> None:
        reps = max(1, step.get("repeatCount", 1))
        children = step.get("children") or []
        for _ in range(reps):
            if children:
                for child in children:
                    visit(child)
            else:
                out.append(
                    {
                        "seconds": _round(_step_seconds(step, sport)),
                        "intensityFactor": _if_from_target(
                            step.get("target"), sport, thresholds
                        ),
                    }
                )

    for s in structure:
        visit(s)
    return out


def compute_workout_metrics(
    structure: list[dict], sport: str, thresholds: Optional[dict] = None
) -> dict:
    blocks = _flatten(structure, sport, thresholds or {})
    duration_seconds = sum(b["seconds"] for b in blocks)
    tss = sum(
        (b["seconds"] / 3600) * b["intensityFactor"] ** 2 * 100 for b in blocks
    )
    return {"durationSeconds": duration_seconds, "tss": _round(tss)}
