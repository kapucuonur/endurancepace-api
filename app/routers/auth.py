"""Signup / login / account deletion. Mirrors bikefit-api: email+password, JWT
issued on login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.ids import new_id
from app.garmin import mfa_registry
from app.garmin.client import GarminClient
from app.models import Athlete, Message, User, Workout
from app.ratelimit import limiter
from app.schemas import DeleteAccountBody, LoginBody, SignupBody, TokenResponse
from app.security import (
    create_access_token,
    get_current_user,
    hash_password,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

DEFAULT_DISCIPLINES = ["swim", "bike", "run", "strength"]


@router.post("/signup", status_code=status.HTTP_201_CREATED)
@limiter.limit("5/hour")
def signup(request: Request, body: SignupBody, db: Session = Depends(get_db)) -> dict:
    email = body.email.strip().lower()
    if db.query(User).filter(User.email == email).first():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Email already registered"
        )

    ts = now_iso()
    user = User(email=email, hashed_password=hash_password(body.password), created_at=ts)
    db.add(user)
    db.flush()  # assign user.id

    athlete = Athlete(
        id=new_id("ath"),
        user_id=user.id,
        name=(body.name or "Athlete").strip(),
        disciplines=list(DEFAULT_DISCIPLINES),
        thresholds={},
        hr_zones=None,
        power_zones=None,
        run_pace_zones=None,
        weight_kg=None,
        birthdate=None,
        created_at=ts,
        updated_at=ts,
    )
    db.add(athlete)
    db.commit()
    return {"email": email}


@router.post("/login", response_model=TokenResponse)
@limiter.limit("10/minute")
def login(request: Request, body: LoginBody, db: Session = Depends(get_db)) -> TokenResponse:
    email = body.email.strip().lower()
    user = db.query(User).filter(User.email == email).first()
    if user is None or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid email or password"
        )
    return TokenResponse(token=create_access_token(user.email))


@router.delete("/account", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("5/hour")
def delete_account(
    request: Request,
    body: DeleteAccountBody,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> None:
    """Permanently delete the caller's account and everything it owns.

    Requires the password again so a leaked/left-open token alone can't wipe an
    account. Plans/events/workouts/Garmin session go via the Athlete cascade;
    messages and coach links aren't relationships, so they're cleared here
    (SQLite doesn't enforce the FKs, so nothing else would).
    """
    # 403, not 401: the session is fine, and clients sign out on any 401.
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Invalid password")

    athlete = user.athlete
    if athlete is not None:
        db.query(Message).filter(
            or_(Message.sender_id == athlete.id, Message.recipient_id == athlete.id)
        ).delete(synchronize_session=False)
        # Workouts this user assigned as a coach stay with their athletes.
        db.query(Workout).filter(
            Workout.assigned_by_id == athlete.id, Workout.athlete_id != athlete.id
        ).update({Workout.assigned_by_id: None}, synchronize_session=False)
        mfa_registry.take(athlete.id)

    garmin_email = user.garmin_email
    db.delete(user)
    db.commit()
    # garth also caches the Garmin session on disk; Garmin disconnect clears it, so must we.
    if garmin_email:
        GarminClient.forget_disk(garmin_email)
