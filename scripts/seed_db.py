"""Local dev seeding.

Creates (or reuses) a demo account and fills it with the sample dataset from
app/seed_data.py — the same data the frontend's services/seed.ts produces.

    python -m scripts.seed_db

Demo credentials: demo@endurancepace.app / demo-endurance-2026

NOTE: the demo account has a known password and is publicly reachable. Delete it
before onboarding real users (or override DEMO_* via env for a private one).
"""

from __future__ import annotations

import os

from app.clock import now_iso
from app.database import Base, SessionLocal, engine
from app.ids import new_id
from app.models import Athlete, User
from app.security import hash_password
from app.seed_data import apply_seed

DEMO_EMAIL = os.getenv("ENDURANCEPACE_DEMO_EMAIL", "demo@endurancepace.app")
DEMO_PASSWORD = os.getenv("ENDURANCEPACE_DEMO_PASSWORD", "demo-endurance-2026")


def main() -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == DEMO_EMAIL).first()
        if user is None:
            ts = now_iso()
            user = User(
                email=DEMO_EMAIL,
                hashed_password=hash_password(DEMO_PASSWORD),
                created_at=ts,
            )
            db.add(user)
            db.flush()
            athlete = Athlete(
                id=new_id("ath"),
                user_id=user.id,
                name="Alex Rivera",
                disciplines=["swim", "bike", "run", "strength"],
                thresholds={},
                created_at=ts,
                updated_at=ts,
            )
            db.add(athlete)
            db.commit()
            print(f"created demo user {DEMO_EMAIL} / {DEMO_PASSWORD}")
        else:
            athlete = db.query(Athlete).filter(Athlete.user_id == user.id).first()
            print(f"reusing demo user {DEMO_EMAIL}")

        apply_seed(db, athlete)
        from app.models import RaceEvent, TrainingPlan, Workout

        plans = db.query(TrainingPlan).filter_by(athlete_id=athlete.id).count()
        events = db.query(RaceEvent).filter_by(athlete_id=athlete.id).count()
        workouts = db.query(Workout).filter_by(athlete_id=athlete.id).count()
        print(f"seeded: {plans} plan(s), {events} event(s), {workouts} workout(s)")
    finally:
        db.close()


if __name__ == "__main__":
    main()
