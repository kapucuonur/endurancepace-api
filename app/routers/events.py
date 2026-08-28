"""Race events — `listEvents` / `createEvent` / `updateEvent` / `deleteEvent`."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.deps import get_current_athlete
from app.ids import new_id
from app.models import Athlete, RaceEvent, TrainingPlan
from app.schemas import EventCreate, EventOut, EventUpdate

router = APIRouter(prefix="/events", tags=["events"])


def _owned(db: Session, athlete: Athlete, event_id: str) -> RaceEvent:
    event = (
        db.query(RaceEvent)
        .filter(RaceEvent.id == event_id, RaceEvent.athlete_id == athlete.id)
        .first()
    )
    if event is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Event not found"
        )
    return event


@router.get("", response_model=list[EventOut])
def list_events(
    db: Session = Depends(get_db), athlete: Athlete = Depends(get_current_athlete)
) -> list[RaceEvent]:
    return (
        db.query(RaceEvent)
        .filter(RaceEvent.athlete_id == athlete.id)
        .order_by(RaceEvent.date)
        .all()
    )


@router.post("", response_model=EventOut, status_code=status.HTTP_201_CREATED)
def create_event(
    body: EventCreate,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> RaceEvent:
    ts = now_iso()
    event = RaceEvent(
        id=new_id("evt"),
        athlete_id=athlete.id,
        name=body.name,
        date=body.date,
        sport=body.sport,
        priority=body.priority,
        distance=body.distance,
        location=body.location,
        created_at=ts,
        updated_at=ts,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    return event


@router.patch("/{event_id}", response_model=EventOut)
def update_event(
    event_id: str,
    patch: EventUpdate,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> RaceEvent:
    event = _owned(db, athlete, event_id)
    data = patch.model_dump(exclude_unset=True, by_alias=False)
    for field in ("name", "date", "sport", "priority", "distance", "location"):
        if field in data:
            setattr(event, field, data[field])
    event.updated_at = now_iso()
    db.commit()
    db.refresh(event)
    return event


@router.delete("/{event_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_event(
    event_id: str,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Response:
    event = _owned(db, athlete, event_id)
    # Null out any plan pointing at this event (mirrors MockApi.deleteEvent).
    db.query(TrainingPlan).filter(
        TrainingPlan.athlete_id == athlete.id, TrainingPlan.goal_event_id == event_id
    ).update({TrainingPlan.goal_event_id: None})
    db.delete(event)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
