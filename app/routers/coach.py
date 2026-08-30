"""Coaching — a coach (login listed in ``COACH_EMAILS``) can see every
athlete's data and assign workouts to them.

- GET    /coach/athletes                              -> roster (everyone but me)
- GET    /coach/athletes/{id}/snapshot                -> that athlete's full snapshot
- POST   /coach/athletes/{id}/workouts                -> assign a workout (source="coach")
- PATCH  /coach/athletes/{id}/workouts/{workout_id}   -> edit one of my assignments
- DELETE /coach/athletes/{id}/workouts/{workout_id}   -> withdraw one of my assignments

Access model is "open": a coach may assign to any registered athlete. Edits and
deletes are still restricted to the coach's own `source == "coach"` rows.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.deps import get_current_coach
from app.ids import new_id
from app.models import Athlete, Workout
from app.routers.snapshot import _snapshot
from app.routers.workouts import apply_workout_patch
from app.schemas import (
    AppSnapshot,
    CoachAthleteOut,
    WorkoutCreate,
    WorkoutOut,
    WorkoutUpdate,
)
from app.serialize import dump, dump_list

router = APIRouter(prefix="/coach", tags=["coach"])


def _athlete(db: Session, coach: Athlete, athlete_id: str) -> Athlete:
    target = db.query(Athlete).filter(Athlete.id == athlete_id).first()
    if target is None or target.id == coach.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found"
        )
    return target


def _assignment(
    db: Session, coach: Athlete, athlete_id: str, workout_id: str
) -> Workout:
    workout = (
        db.query(Workout)
        .filter(Workout.id == workout_id, Workout.athlete_id == athlete_id)
        .first()
    )
    if workout is None or workout.source != "coach" or workout.assigned_by_id != coach.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Assignment not found"
        )
    return workout


@router.get("/athletes", response_model=list[CoachAthleteOut])
def list_athletes(
    db: Session = Depends(get_db),
    coach: Athlete = Depends(get_current_coach),
) -> list[dict]:
    rows = (
        db.query(Athlete)
        .filter(Athlete.id != coach.id)
        .order_by(Athlete.name)
        .all()
    )
    return [{"id": a.id, "name": a.name, "email": a.email or ""} for a in rows]


@router.get("/athletes/{athlete_id}/snapshot", response_model=AppSnapshot)
def athlete_snapshot(
    athlete_id: str,
    db: Session = Depends(get_db),
    coach: Athlete = Depends(get_current_coach),
) -> dict:
    return _snapshot(db, _athlete(db, coach, athlete_id))


@router.post(
    "/athletes/{athlete_id}/workouts",
    response_model=WorkoutOut,
    status_code=status.HTTP_201_CREATED,
)
def assign_workout(
    athlete_id: str,
    body: WorkoutCreate,
    db: Session = Depends(get_db),
    coach: Athlete = Depends(get_current_coach),
) -> Workout:
    target = _athlete(db, coach, athlete_id)
    ts = now_iso()
    workout = Workout(
        id=new_id("wko"),
        athlete_id=target.id,
        plan_id=body.plan_id,
        date=body.date,
        sport=body.sport,
        title=body.title,
        description=body.description,
        structure=dump_list(body.structure) or [],
        planned_duration=int(round(body.planned_duration)),
        planned_tss=int(round(body.planned_tss)),
        status=body.status,
        completed=dump(body.completed),
        is_template=False,
        template_category=None,
        source="coach",
        assigned_by_id=coach.id,
        created_at=ts,
        updated_at=ts,
    )
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return workout


@router.patch(
    "/athletes/{athlete_id}/workouts/{workout_id}", response_model=WorkoutOut
)
def edit_assignment(
    athlete_id: str,
    workout_id: str,
    patch: WorkoutUpdate,
    db: Session = Depends(get_db),
    coach: Athlete = Depends(get_current_coach),
) -> Workout:
    workout = _assignment(db, coach, athlete_id, workout_id)
    apply_workout_patch(workout, patch)
    db.commit()
    db.refresh(workout)
    return workout


@router.delete(
    "/athletes/{athlete_id}/workouts/{workout_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def withdraw_assignment(
    athlete_id: str,
    workout_id: str,
    db: Session = Depends(get_db),
    coach: Athlete = Depends(get_current_coach),
) -> Response:
    db.delete(_assignment(db, coach, athlete_id, workout_id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
