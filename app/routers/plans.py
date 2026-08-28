"""Training plans — `listPlans` / `createPlan` / `updatePlan` / `deletePlan`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.deps import get_current_athlete
from app.ids import new_id
from app.models import Athlete, TrainingPlan, Workout
from app.schemas import PlanCreate, PlanOut, PlanUpdate

router = APIRouter(prefix="/plans", tags=["plans"])


def _owned(db: Session, athlete: Athlete, plan_id: str) -> TrainingPlan:
    plan = (
        db.query(TrainingPlan)
        .filter(TrainingPlan.id == plan_id, TrainingPlan.athlete_id == athlete.id)
        .first()
    )
    if plan is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Plan not found")
    return plan


@router.get("", response_model=list[PlanOut])
def list_plans(
    db: Session = Depends(get_db), athlete: Athlete = Depends(get_current_athlete)
) -> list[TrainingPlan]:
    return (
        db.query(TrainingPlan)
        .filter(TrainingPlan.athlete_id == athlete.id)
        .order_by(TrainingPlan.created_at)
        .all()
    )


@router.post("", response_model=PlanOut, status_code=status.HTTP_201_CREATED)
def create_plan(
    body: PlanCreate,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> TrainingPlan:
    ts = now_iso()
    plan = TrainingPlan(
        id=new_id("pln"),
        athlete_id=athlete.id,  # scoped to caller; body.athlete_id is ignored
        name=body.name,
        start_date=body.start_date,
        end_date=body.end_date,
        goal_event_id=body.goal_event_id,
        phase=body.phase,
        blocks=(
            [b.model_dump(by_alias=True) for b in body.blocks] if body.blocks else None
        ),
        notes=body.notes,
        created_at=ts,
        updated_at=ts,
    )
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return plan


@router.patch("/{plan_id}", response_model=PlanOut)
def update_plan(
    plan_id: str,
    patch: PlanUpdate,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> TrainingPlan:
    plan = _owned(db, athlete, plan_id)
    data = patch.model_dump(exclude_unset=True, by_alias=False)
    for field in ("name", "start_date", "end_date", "goal_event_id", "phase", "notes"):
        if field in data:
            setattr(plan, field, data[field])
    if "blocks" in data:
        plan.blocks = (
            [b.model_dump(by_alias=True) for b in patch.blocks] if patch.blocks else None
        )
    plan.updated_at = now_iso()
    db.commit()
    db.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_plan(
    plan_id: str,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Response:
    plan = _owned(db, athlete, plan_id)
    # Detach workouts rather than delete them (mirrors MockApi.deletePlan).
    db.query(Workout).filter(
        Workout.athlete_id == athlete.id, Workout.plan_id == plan_id
    ).update({Workout.plan_id: None})
    db.delete(plan)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
