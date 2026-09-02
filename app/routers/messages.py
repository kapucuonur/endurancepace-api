"""Direct messages — coach ↔ athlete 1:1 chat.

- GET  /messages/threads              -> one row per conversation partner
- GET  /messages/with/{partner_id}    -> the conversation (marks incoming read)
- POST /messages/with/{partner_id}    -> send a message
- GET  /messages/unread-count         -> total unread, for the app's tab badge

Any athlete may call these (not coach-gated). Who you're allowed to message:
  * a coach may message any athlete;
  * an athlete may message a coach who has assigned them a workout;
  * either party may always reply to someone who has already messaged them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.deps import get_current_athlete
from app.ids import new_id
from app.models import Athlete, Message, Workout
from app.schemas import (
    MessageCreate,
    MessageOut,
    MessagePartner,
    MessagesPage,
    MessageThreadOut,
    UnreadCountOut,
)

router = APIRouter(prefix="/messages", tags=["messages"])


def _partner(db: Session, me: Athlete, partner_id: str) -> Athlete:
    other = db.query(Athlete).filter(Athlete.id == partner_id).first()
    if other is None or other.id == me.id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Athlete not found"
        )
    return other


def _already_talking(db: Session, me: Athlete, other: Athlete) -> bool:
    return (
        db.query(Message.id)
        .filter(Message.sender_id == other.id, Message.recipient_id == me.id)
        .first()
        is not None
    )


def _assert_can_message(db: Session, me: Athlete, other: Athlete) -> None:
    if me.role == "coach":
        return
    if other.role == "coach":
        assigned = (
            db.query(Workout.id)
            .filter(
                Workout.athlete_id == me.id,
                Workout.source == "coach",
                Workout.assigned_by_id == other.id,
            )
            .first()
        )
        if assigned is not None:
            return
    if _already_talking(db, me, other):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You can't message this person",
    )


def _partner_payload(other: Athlete) -> MessagePartner:
    return MessagePartner(
        id=other.id, name=other.name, email=other.email or "", role=other.role
    )


@router.get("/threads", response_model=list[MessageThreadOut])
def list_threads(
    db: Session = Depends(get_db),
    me: Athlete = Depends(get_current_athlete),
) -> list[MessageThreadOut]:
    rows = (
        db.query(Message)
        .filter(or_(Message.sender_id == me.id, Message.recipient_id == me.id))
        .order_by(Message.created_at.desc())
        .all()
    )

    threads: dict[str, dict] = {}
    for m in rows:
        other_id = m.recipient_id if m.sender_id == me.id else m.sender_id
        t = threads.setdefault(
            other_id, {"last": m, "unread": 0}
        )
        if m.recipient_id == me.id and m.read_at is None:
            t["unread"] += 1

    if not threads:
        return []

    others = {
        a.id: a
        for a in db.query(Athlete).filter(Athlete.id.in_(threads.keys())).all()
    }

    out: list[MessageThreadOut] = []
    for other_id, t in threads.items():
        other = others.get(other_id)
        if other is None:
            continue
        out.append(
            MessageThreadOut(
                partner=_partner_payload(other),
                last_message=MessageOut.model_validate(t["last"]),
                unread_count=t["unread"],
            )
        )
    out.sort(key=lambda x: x.last_message.created_at, reverse=True)
    return out


@router.get("/unread-count", response_model=UnreadCountOut)
def unread_count(
    db: Session = Depends(get_db),
    me: Athlete = Depends(get_current_athlete),
) -> UnreadCountOut:
    n = (
        db.query(Message.id)
        .filter(Message.recipient_id == me.id, Message.read_at.is_(None))
        .count()
    )
    return UnreadCountOut(count=n)


@router.get("/with/{partner_id}", response_model=MessagesPage)
def conversation(
    partner_id: str,
    before: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    me: Athlete = Depends(get_current_athlete),
) -> MessagesPage:
    other = _partner(db, me, partner_id)

    q = db.query(Message).filter(
        or_(
            (Message.sender_id == me.id) & (Message.recipient_id == other.id),
            (Message.sender_id == other.id) & (Message.recipient_id == me.id),
        )
    )
    if before:
        q = q.filter(Message.created_at < before)
    # newest `limit`, returned oldest-first
    rows = q.order_by(Message.created_at.desc()).limit(limit).all()
    rows.reverse()

    # Mark everything they sent me as read.
    db.query(Message).filter(
        Message.sender_id == other.id,
        Message.recipient_id == me.id,
        Message.read_at.is_(None),
    ).update({Message.read_at: now_iso()})
    db.commit()

    return MessagesPage(
        partner=_partner_payload(other),
        messages=[MessageOut.model_validate(m) for m in rows],
    )


@router.post(
    "/with/{partner_id}",
    response_model=MessageOut,
    status_code=status.HTTP_201_CREATED,
)
def send_message(
    partner_id: str,
    body: MessageCreate,
    db: Session = Depends(get_db),
    me: Athlete = Depends(get_current_athlete),
) -> Message:
    other = _partner(db, me, partner_id)
    _assert_can_message(db, me, other)

    text = body.body.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Message is empty",
        )

    message = Message(
        id=new_id("msg"),
        sender_id=me.id,
        recipient_id=other.id,
        body=text,
        created_at=now_iso(),
        read_at=None,
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message
