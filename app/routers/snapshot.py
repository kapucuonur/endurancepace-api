"""Aggregate + dev reset.

- GET  /me/snapshot -> getSnapshot()   (athlete + all plans/events/workouts)
- POST /me/reset    -> resetToSeed()    (gated by ENDURANCEPACE_ALLOW_RESET)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_athlete
from app.models import Athlete, RaceEvent, TrainingPlan, Workout
from app.schemas import AppSnapshot
from app.seed_data import apply_seed

router = APIRouter(prefix="/me", tags=["snapshot"])


def _snapshot(db: Session, athlete: Athlete) -> dict:
    return {
        "athlete": athlete,
        "plans": (
            db.query(TrainingPlan)
            .filter(TrainingPlan.athlete_id == athlete.id)
            .order_by(TrainingPlan.created_at)
            .all()
        ),
        "events": (
            db.query(RaceEvent)
            .filter(RaceEvent.athlete_id == athlete.id)
            .order_by(RaceEvent.date)
            .all()
        ),
        "workouts": (
            db.query(Workout)
            .filter(Workout.athlete_id == athlete.id)
            .order_by(Workout.date.is_(None), Workout.date, Workout.created_at)
            .all()
        ),
    }


@router.get("/snapshot", response_model=AppSnapshot)
def get_snapshot(
    db: Session = Depends(get_db), athlete: Athlete = Depends(get_current_athlete)
) -> dict:
    if settings.garmin_sync_on_snapshot:
        from app.garmin.background import maybe_sync

        maybe_sync(db, athlete)
    return _snapshot(db, athlete)


@router.post("/reset", response_model=AppSnapshot)
def reset_to_seed(
    db: Session = Depends(get_db), athlete: Athlete = Depends(get_current_athlete)
) -> dict:
    if not settings.allow_reset:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Reset disabled (set ENDURANCEPACE_ALLOW_RESET=true)",
        )
    apply_seed(db, athlete)
    db.refresh(athlete)
    return _snapshot(db, athlete)
