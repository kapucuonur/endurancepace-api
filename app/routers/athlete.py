"""Athlete profile + thresholds.

- PATCH /me/athlete            -> `updateAthlete(patch)`  (stores as given, no zone recompute)
- PUT   /me/athlete/thresholds -> `updateThresholds(t)`   (merges, then recomputes zones)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.deps import get_current_athlete
from app.models import Athlete
from app.schemas import AthleteOut, AthleteUpdate, ThresholdValues
from app.serialize import dump, dump_list
from app.zones import derive_zones

router = APIRouter(prefix="/me/athlete", tags=["athlete"])


@router.patch("", response_model=AthleteOut)
def update_athlete(
    patch: AthleteUpdate,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Athlete:
    data = patch.model_dump(exclude_unset=True, by_alias=False)

    if "name" in data and data["name"] is not None:
        athlete.name = data["name"]
    if "disciplines" in data and data["disciplines"] is not None:
        athlete.disciplines = data["disciplines"]
    if "weight_kg" in data:
        athlete.weight_kg = data["weight_kg"]
    if "birthdate" in data:
        athlete.birthdate = data["birthdate"]
    if "thresholds" in data and data["thresholds"] is not None:
        athlete.thresholds = dump(patch.thresholds)  # stored as given, NOT recomputed
    for zone_field in ("hr_zones", "power_zones", "run_pace_zones"):
        if zone_field in data:
            setattr(athlete, zone_field, dump_list(getattr(patch, zone_field)))

    athlete.updated_at = now_iso()
    db.commit()
    db.refresh(athlete)
    return athlete


@router.put("/thresholds", response_model=AthleteOut)
def update_thresholds(
    thresholds: ThresholdValues,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Athlete:
    # Merge onto the existing thresholds (mirrors MockApi.updateThresholds).
    incoming = thresholds.model_dump(by_alias=True, exclude_unset=True, mode="json")
    merged = {**(athlete.thresholds or {}), **incoming}

    athlete.thresholds = merged
    zones = derive_zones(merged)
    athlete.hr_zones = zones["hrZones"]
    athlete.power_zones = zones["powerZones"]
    athlete.run_pace_zones = zones["runPaceZones"]
    athlete.updated_at = now_iso()

    db.commit()
    db.refresh(athlete)
    return athlete
