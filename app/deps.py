"""Shared FastAPI dependencies."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Athlete, User
from app.security import get_current_user


def get_current_athlete(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Athlete:
    athlete = db.query(Athlete).filter(Athlete.user_id == user.id).first()
    if athlete is None:
        # Every user gets an athlete at signup; this should not happen.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="No athlete for this user"
        )
    return athlete
