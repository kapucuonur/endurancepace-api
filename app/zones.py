"""Training-zone calculators — a direct port of the frontend's
src/domain/zones.ts. Kept byte-for-byte equivalent so a threshold update on the
server yields the exact same zones the app's mock layer would compute.
"""

from __future__ import annotations

from typing import Optional

HR_ZONE_NAMES = ["Recovery", "Aerobic", "Tempo", "Threshold", "VO2 Max"]
POWER_ZONE_NAMES = [
    "Active Recovery",
    "Endurance",
    "Tempo",
    "Threshold",
    "VO2 / Anaerobic",
]
PACE_ZONE_NAMES = ["Easy", "Endurance", "Tempo", "Threshold", "Interval"]

HR_LOWER_PCT = [0, 0.82, 0.89, 0.94, 1.0]
POWER_LOWER_PCT = [0, 0.55, 0.75, 0.9, 1.05]
PACE_SLOW_MULT = [1.5, 1.28, 1.13, 1.05, 1.0]

Zone = dict  # {"index": int, "name": str, "min": int, "max": int | None}


def _round(n: float) -> int:
    # JS Math.round: half rounds toward +Infinity. Python's round() is banker's.
    import math

    return math.floor(n + 0.5)


def _build_ascending_zones(
    threshold: float, lower_pct: list[float], names: list[str]
) -> list[Zone]:
    zones: list[Zone] = []
    for i, pct in enumerate(lower_pct):
        minimum = 0 if i == 0 else _round(threshold * pct)
        maximum = (
            None
            if i == len(lower_pct) - 1
            else _round(threshold * lower_pct[i + 1]) - 1
        )
        zones.append({"index": i + 1, "name": names[i], "min": minimum, "max": maximum})
    return zones


def calc_hr_zones(thresholds: dict) -> Optional[list[Zone]]:
    lthr = thresholds.get("thresholdHr")
    if not lthr or lthr <= 0:
        return None
    return _build_ascending_zones(lthr, HR_LOWER_PCT, HR_ZONE_NAMES)


def calc_power_zones(thresholds: dict) -> Optional[list[Zone]]:
    ftp = thresholds.get("ftpWatts")
    if not ftp or ftp <= 0:
        return None
    return _build_ascending_zones(ftp, POWER_LOWER_PCT, POWER_ZONE_NAMES)


def calc_pace_zones(threshold_pace: Optional[float]) -> Optional[list[Zone]]:
    if not threshold_pace or threshold_pace <= 0:
        return None
    zones: list[Zone] = []
    for i, slow_mult in enumerate(PACE_SLOW_MULT):
        fast_mult = 0.85 if i == len(PACE_SLOW_MULT) - 1 else PACE_SLOW_MULT[i + 1]
        zones.append(
            {
                "index": i + 1,
                "name": PACE_ZONE_NAMES[i],
                "min": _round(threshold_pace * fast_mult),
                "max": None if i == 0 else _round(threshold_pace * slow_mult),
            }
        )
    return zones


def calc_run_pace_zones(thresholds: dict) -> Optional[list[Zone]]:
    return calc_pace_zones(thresholds.get("runThresholdPaceSecPerKm"))


def calc_swim_pace_zones(thresholds: dict) -> Optional[list[Zone]]:
    return calc_pace_zones(thresholds.get("cssSecPer100m"))


def derive_zones(thresholds: dict) -> dict:
    """Mirror of deriveZones() — HR, power, run-pace (not swim)."""
    return {
        "hrZones": calc_hr_zones(thresholds),
        "powerZones": calc_power_zones(thresholds),
        "runPaceZones": calc_run_pace_zones(thresholds),
    }
