"""SQLAlchemy models mirroring the frontend domain types (types/domain.ts).

Design note — the Step tree is stored as a single JSON column on `workouts`
(`structure`), not normalised into rows. Interval structures are read and
written whole by the app and never queried into; normalising them would buy
nothing and make the 1:1 contract mapping lossy. `planned_duration` /
`planned_tss` are computed client-side and simply persisted here, exactly as
the app's mock layer does today.

Relationship to the domain types:
  User            -> (no domain equivalent; auth only)
  Athlete         -> Athlete            (1 per user)
  TrainingPlan    -> TrainingPlan
  RaceEvent       -> RaceEvent
  Workout         -> Workout            (adds athlete_id for ownership scoping;
                                         not serialised back to the client)
"""

from __future__ import annotations

from sqlalchemy import (
    JSON,
    Boolean,
    Column,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship

from app.database import Base


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    created_at = Column(String, nullable=False)

    # Linked Garmin.com account (garminconnect/garth login). The password is
    # Fernet-encrypted, NOT hashed — the Garmin API needs it raw.
    garmin_email = Column(String, nullable=True)
    garmin_password = Column(String, nullable=True)

    athlete = relationship(
        "Athlete",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class Athlete(Base):
    __tablename__ = "athletes"

    id = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), unique=True, nullable=False)

    name = Column(String, nullable=False)
    disciplines = Column(JSON, nullable=False, default=list)
    thresholds = Column(JSON, nullable=False, default=dict)
    hr_zones = Column(JSON, nullable=True)
    power_zones = Column(JSON, nullable=True)
    run_pace_zones = Column(JSON, nullable=True)
    weight_kg = Column(Float, nullable=True)
    birthdate = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    user = relationship("User", back_populates="athlete")
    # Deleting an athlete (or its user) removes everything it owns — no orphans.
    plans = relationship("TrainingPlan", cascade="all, delete-orphan")
    events = relationship("RaceEvent", cascade="all, delete-orphan")
    workouts = relationship(
        "Workout",
        cascade="all, delete-orphan",
        foreign_keys="Workout.athlete_id",
    )
    garmin_session = relationship(
        "GarminSession", cascade="all, delete-orphan", uselist=False
    )

    @property
    def email(self) -> str | None:
        return self.user.email if self.user else None

    @property
    def role(self) -> str:
        """`"coach"` when this athlete's login is in ``COACH_EMAILS``, else
        `"athlete"`. Not stored — derived from config on every read."""
        from app.config import settings

        addr = (self.email or "").lower()
        return "coach" if addr and addr in settings.coach_email_list else "athlete"


class TrainingPlan(Base):
    __tablename__ = "training_plans"

    id = Column(String, primary_key=True)
    athlete_id = Column(String, ForeignKey("athletes.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    start_date = Column(String, nullable=False)
    end_date = Column(String, nullable=False)
    goal_event_id = Column(String, nullable=True)
    phase = Column(String, nullable=False)
    # Periodization breakdown: [{"phase": ..., "weeks": N}] sequential from
    # start_date. Optional — plans created before this feature have none.
    blocks = Column(JSON, nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class RaceEvent(Base):
    __tablename__ = "race_events"

    id = Column(String, primary_key=True)
    athlete_id = Column(String, ForeignKey("athletes.id"), nullable=False, index=True)

    name = Column(String, nullable=False)
    date = Column(String, nullable=False)
    sport = Column(String, nullable=False)
    priority = Column(String, nullable=False)
    distance = Column(String, nullable=False)
    location = Column(String, nullable=True)
    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)


class Workout(Base):
    __tablename__ = "workouts"

    id = Column(String, primary_key=True)
    athlete_id = Column(String, ForeignKey("athletes.id"), nullable=False, index=True)

    plan_id = Column(String, nullable=True, index=True)
    date = Column(String, nullable=True, index=True)
    sport = Column(String, nullable=False)
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    structure = Column(JSON, nullable=False, default=list)
    planned_duration = Column(Integer, nullable=False, default=0)
    planned_tss = Column(Integer, nullable=False, default=0)
    status = Column(String, nullable=False, default="planned")
    completed = Column(JSON, nullable=True)
    is_template = Column(Boolean, nullable=False, default=False)
    template_category = Column(String, nullable=True)

    # Provenance. `source` is "manual" (app-built) or "garmin" (imported).
    # `external_id` is the Garmin activityId; unique per athlete for dedup.
    # `garmin_raw` keeps the sanitized payload for re-processing / debugging.
    # "manual" (app-built) | "garmin" (imported) | "coach" (assigned by a coach).
    source = Column(String, nullable=False, default="manual")
    external_id = Column(String, nullable=True)
    garmin_raw = Column(JSON, nullable=True)
    # The coach who assigned this workout, when `source == "coach"`.
    assigned_by_id = Column(String, ForeignKey("athletes.id"), nullable=True)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)

    __table_args__ = (
        UniqueConstraint("athlete_id", "external_id", name="uq_workouts_athlete_external"),
    )


class GarminSession(Base):
    """Per-athlete Garmin auth state. Replaces ai-coach's in-memory module
    globals (GLOBAL_CLIENTS / SESSION_LAST_VERIFIED / FAILED_LOGIN_COOLDOWN /
    PENDING_SESSIONS) with durable, multi-worker-safe rows.
    """

    __tablename__ = "garmin_sessions"

    id = Column(Integer, primary_key=True, index=True)
    athlete_id = Column(String, ForeignKey("athletes.id"), unique=True, nullable=False)

    # Fernet-encrypted JSON of the garth token dump ({filename: contents}).
    token_blob = Column(Text, nullable=True)
    display_name = Column(String, nullable=True)
    # active | expired | mfa_pending | error
    status = Column(String, nullable=False, default="error")

    # When a `return_on_mfa` login is awaiting its code. The resumable state
    # itself (a live HTTP client) is held in app.garmin.mfa_registry, not here.
    mfa_initiated_at = Column(String, nullable=True)

    last_verified_at = Column(String, nullable=True)
    cooldown_until = Column(String, nullable=True)
    last_sync_at = Column(String, nullable=True)
    sync_in_progress = Column(Boolean, nullable=False, default=False)
    last_error = Column(Text, nullable=True)

    created_at = Column(String, nullable=False)
    updated_at = Column(String, nullable=False)
