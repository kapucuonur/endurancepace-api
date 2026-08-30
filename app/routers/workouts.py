"""Workouts.

- GET  /workouts                       -> listWorkouts()            (all, incl. templates)
- GET  /workouts?start=&end=           -> listWorkoutsInRange()     (scheduled, non-template)
- GET  /workouts?template=true         -> listLibraryWorkouts()
- GET  /workouts/{id}                  -> getWorkout()              (404 -> undefined)
- POST /workouts                       -> createWorkout()
- PATCH /workouts/{id}                 -> updateWorkout()
- DELETE /workouts/{id}                -> deleteWorkout()
- POST /workouts/{templateId}/schedule -> scheduleFromTemplate()
"""

from __future__ import annotations

import copy
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.deps import get_current_athlete
from app.ids import new_id
from app.models import Athlete, Workout
from app.schemas import (
    ScheduleFromTemplateBody,
    WorkoutCreate,
    WorkoutOut,
    WorkoutUpdate,
)
from app.serialize import dump, dump_list

router = APIRouter(prefix="/workouts", tags=["workouts"])


def apply_workout_patch(workout: Workout, patch: WorkoutUpdate) -> None:
    """Mutate `workout` in place from a `WorkoutUpdate` (shared with the coach
    router). Does not commit."""
    data = patch.model_dump(exclude_unset=True, by_alias=False)

    for field in (
        "plan_id",
        "date",
        "sport",
        "title",
        "description",
        "status",
        "is_template",
        "template_category",
    ):
        if field in data:
            setattr(workout, field, data[field])

    if "planned_duration" in data and data["planned_duration"] is not None:
        workout.planned_duration = int(round(data["planned_duration"]))
    if "planned_tss" in data and data["planned_tss"] is not None:
        workout.planned_tss = int(round(data["planned_tss"]))
    if "structure" in data:
        workout.structure = dump_list(patch.structure) or []
    if "completed" in data:
        workout.completed = dump(patch.completed)

    workout.updated_at = now_iso()


def _owned(db: Session, athlete: Athlete, workout_id: str) -> Workout:
    workout = (
        db.query(Workout)
        .filter(Workout.id == workout_id, Workout.athlete_id == athlete.id)
        .first()
    )
    if workout is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Workout not found"
        )
    return workout


@router.get("", response_model=list[WorkoutOut])
def list_workouts(
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
    start: Optional[str] = Query(default=None),
    end: Optional[str] = Query(default=None),
    template: Optional[bool] = Query(default=None),
) -> list[Workout]:
    q = db.query(Workout).filter(Workout.athlete_id == athlete.id)

    if template is not None:
        q = q.filter(Workout.is_template.is_(template))

    if start is not None and end is not None:
        q = q.filter(
            Workout.is_template.is_(False),
            Workout.date.isnot(None),
            Workout.date >= start,
            Workout.date <= end,
        )

    return q.order_by(Workout.date.is_(None), Workout.date, Workout.created_at).all()


@router.get("/{workout_id}", response_model=WorkoutOut)
def get_workout(
    workout_id: str,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Workout:
    return _owned(db, athlete, workout_id)


@router.post("", response_model=WorkoutOut, status_code=status.HTTP_201_CREATED)
def create_workout(
    body: WorkoutCreate,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Workout:
    ts = now_iso()
    workout = Workout(
        id=new_id("wko"),
        athlete_id=athlete.id,
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
        is_template=body.is_template,
        template_category=body.template_category,
        created_at=ts,
        updated_at=ts,
    )
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return workout


@router.patch("/{workout_id}", response_model=WorkoutOut)
def update_workout(
    workout_id: str,
    patch: WorkoutUpdate,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Workout:
    workout = _owned(db, athlete, workout_id)
    apply_workout_patch(workout, patch)
    db.commit()
    db.refresh(workout)
    return workout


@router.delete("/{workout_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workout(
    workout_id: str,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Response:
    workout = _owned(db, athlete, workout_id)
    db.delete(workout)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{template_id}/schedule",
    response_model=WorkoutOut,
    status_code=status.HTTP_201_CREATED,
)
def schedule_from_template(
    template_id: str,
    body: ScheduleFromTemplateBody,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Workout:
    template = _owned(db, athlete, template_id)
    if not template.is_template:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Not a library template"
        )
    ts = now_iso()
    workout = Workout(
        id=new_id("wko"),
        athlete_id=athlete.id,
        plan_id=body.plan_id,
        date=body.date,
        sport=template.sport,
        title=template.title,
        description=template.description,
        structure=copy.deepcopy(template.structure),
        planned_duration=template.planned_duration,
        planned_tss=template.planned_tss,
        status="planned",
        completed=None,
        is_template=False,
        template_category=None,
        created_at=ts,
        updated_at=ts,
    )
    db.add(workout)
    db.commit()
    db.refresh(workout)
    return workout
