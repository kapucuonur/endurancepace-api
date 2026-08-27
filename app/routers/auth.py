"""Signup / login. Mirrors bikefit-api: email+password, JWT issued on login."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.clock import now_iso
from app.database import get_db
from app.ids import new_id
from app.models import Athlete, User
from app.ratelimit import limiter
from app.schemas import LoginBody, SignupBody, TokenResponse
from app.security import create_access_token, hash_password, verify_password

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
