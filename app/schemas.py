"""Pydantic schemas — a field-for-field mirror of the frontend's types/domain.ts.

Wire format is camelCase (``alias_generator=to_camel``); Python stays snake_case.
``populate_by_name=True`` lets loaders accept either form.

Serialization policy: reads emit **every** field. Frontend-optional (`?`) fields
come back as ``null`` rather than being omitted — deterministic shape, and safe
for the TS optional types. Writes (`*Update`) use ``exclude_unset=True`` so a
missing key is "don't touch" while an explicit ``null`` clears the value.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

# --- enums (mirror the `as const` arrays in domain.ts) ----------------------

Sport = Literal["swim", "bike", "run", "strength"]
PeriodizationPhase = Literal["base", "build", "peak", "taper", "race", "recovery"]
WorkoutStatus = Literal["planned", "completed", "skipped", "modified"]
WorkoutSource = Literal["manual", "garmin", "coach"]
AthleteRole = Literal["athlete", "coach"]
StepType = Literal["warmup", "interval", "recovery", "cooldown", "steady"]
RacePriority = Literal["A", "B", "C"]
PaceUnit = Literal["sec_per_km", "sec_per_100m"]
ZoneIndex = Literal[1, 2, 3, 4, 5]


class CamelModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        from_attributes=True,
    )


# --- zones & thresholds ----------------------------------------------------


class Zone(CamelModel):
    index: ZoneIndex
    name: str
    min: int
    max: Optional[int] = None


class ThresholdValues(CamelModel):
    ftp_watts: Optional[float] = None
    run_threshold_pace_sec_per_km: Optional[float] = None
    # `to_camel` would give `cssSecPer100M`; the frontend field is lower-m.
    css_sec_per_100m: Optional[float] = Field(default=None, alias="cssSecPer100m")
    threshold_hr: Optional[float] = None
    max_hr: Optional[float] = None


# --- step tree -----------------------------------------------------------------


class StepDurationTime(CamelModel):
    kind: Literal["time"]
    seconds: float


class StepDurationDistance(CamelModel):
    kind: Literal["distance"]
    meters: float
    # Expected average speed, used to estimate time for bike distance steps.
    speed_kmh: Optional[float] = Field(default=None, gt=0, le=80)


StepDuration = Annotated[
    Union[StepDurationTime, StepDurationDistance], Field(discriminator="kind")
]


class PaceRange(CamelModel):
    unit: PaceUnit
    min: float
    max: float


class WattRange(CamelModel):
    min: float
    max: float


class StepTarget(CamelModel):
    pace_target: Optional[PaceRange] = None
    hr_zone: Optional[ZoneIndex] = None
    power_zone: Optional[ZoneIndex] = None
    power_watts: Optional[WattRange] = None
    rpe: Optional[float] = None


class StepExercise(CamelModel):
    """A strength exercise. `key` names an entry in the app's exercise catalog;
    for holds (plank) `reps` is the hold time in seconds."""

    key: str = Field(pattern=r"^[a-z0-9_]{1,40}$")
    sets: int = Field(ge=1, le=20)
    reps: int = Field(ge=1, le=300)
    weight_kg: Optional[float] = Field(default=None, ge=0, le=500)
    rest_sec: int = Field(default=90, ge=0, le=900)


class Step(CamelModel):
    id: str
    type: StepType
    label: Optional[str] = None
    duration: Optional[StepDuration] = None
    target: Optional[StepTarget] = None
    exercise: Optional[StepExercise] = None
    repeat_count: int = 1
    children: list["Step"] = Field(default_factory=list)


Step.model_rebuild()


# --- athlete -----------------------------------------------------------------


class AthleteOut(CamelModel):
    id: str
    name: str
    disciplines: list[Sport]
    thresholds: ThresholdValues
    hr_zones: Optional[list[Zone]] = None
    power_zones: Optional[list[Zone]] = None
    run_pace_zones: Optional[list[Zone]] = None
    weight_kg: Optional[float] = None
    birthdate: Optional[str] = None
    # Derived from COACH_EMAILS, not stored. Drives the coach UI in the app.
    role: AthleteRole = "athlete"
    created_at: str
    updated_at: str


class CoachAthleteOut(CamelModel):
    """One row in a coach's athlete roster."""

    id: str
    name: str
    email: str


class MessagePartner(CamelModel):
    """The other athlete in a conversation."""

    id: str
    name: str
    email: str
    role: AthleteRole = "athlete"


class MessageOut(CamelModel):
    id: str
    sender_id: str
    recipient_id: str
    body: str
    created_at: str
    read_at: Optional[str] = None


class MessageThreadOut(CamelModel):
    partner: MessagePartner
    last_message: MessageOut
    unread_count: int


class MessageCreate(CamelModel):
    body: str = Field(min_length=1, max_length=4000)


class MessagesPage(CamelModel):
    partner: MessagePartner
    messages: list[MessageOut]


class UnreadCountOut(CamelModel):
    count: int


class AthleteUpdate(CamelModel):
    """`Partial<Athlete>` — mirrors MockApi.updateAthlete (stores as given, does
    NOT recompute zones; only PUT /me/athlete/thresholds recomputes)."""

    name: Optional[str] = None
    disciplines: Optional[list[Sport]] = None
    thresholds: Optional[ThresholdValues] = None
    hr_zones: Optional[list[Zone]] = None
    power_zones: Optional[list[Zone]] = None
    run_pace_zones: Optional[list[Zone]] = None
    weight_kg: Optional[float] = None
    birthdate: Optional[str] = None


# --- training plan ---------------------------------------------------------


class PlanBlock(CamelModel):
    phase: PeriodizationPhase
    weeks: int


class PlanBase(CamelModel):
    athlete_id: Optional[str] = None  # frontend sends it; server scopes to caller
    name: str
    start_date: str
    end_date: str
    goal_event_id: Optional[str] = None
    phase: PeriodizationPhase
    blocks: Optional[list[PlanBlock]] = None
    notes: Optional[str] = None


class PlanCreate(PlanBase):
    pass


class PlanUpdate(CamelModel):
    name: Optional[str] = None
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    goal_event_id: Optional[str] = None
    phase: Optional[PeriodizationPhase] = None
    blocks: Optional[list[PlanBlock]] = None
    notes: Optional[str] = None


class PlanOut(CamelModel):
    id: str
    athlete_id: str
    name: str
    start_date: str
    end_date: str
    goal_event_id: Optional[str] = None  # `ID | null` — always emitted
    phase: PeriodizationPhase
    blocks: Optional[list[PlanBlock]] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str


# --- race event ----------------------------------------------------------------


class EventBase(CamelModel):
    athlete_id: Optional[str] = None
    name: str
    date: str
    sport: Sport
    priority: RacePriority
    distance: str
    location: Optional[str] = None


class EventCreate(EventBase):
    pass


class EventUpdate(CamelModel):
    name: Optional[str] = None
    date: Optional[str] = None
    sport: Optional[Sport] = None
    priority: Optional[RacePriority] = None
    distance: Optional[str] = None
    location: Optional[str] = None


class EventOut(CamelModel):
    id: str
    athlete_id: str
    name: str
    date: str
    sport: Sport
    priority: RacePriority
    distance: str
    location: Optional[str] = None
    created_at: str
    updated_at: str


# --- workout -----------------------------------------------------------------


class CompletedInfo(CamelModel):
    date: str
    duration_seconds: Optional[float] = None
    actual_tss: Optional[float] = None
    rpe: Optional[float] = None
    notes: Optional[str] = None
    # Measured metrics from an imported Garmin activity — all optional, all
    # metric units. Absent for a hand-logged session.
    distance_meters: Optional[float] = None
    avg_speed_mps: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    avg_cadence: Optional[float] = None
    avg_power: Optional[float] = None
    calories: Optional[float] = None


class WorkoutBase(CamelModel):
    plan_id: Optional[str] = None
    date: Optional[str] = None
    sport: Sport
    title: str
    description: Optional[str] = None
    structure: list[Step] = Field(default_factory=list)
    planned_duration: float = 0
    planned_tss: float = 0
    status: WorkoutStatus = "planned"
    completed: Optional[CompletedInfo] = None
    is_template: bool = False
    template_category: Optional[str] = None


class WorkoutCreate(WorkoutBase):
    pass


class WorkoutUpdate(CamelModel):
    plan_id: Optional[str] = None
    date: Optional[str] = None
    sport: Optional[Sport] = None
    title: Optional[str] = None
    description: Optional[str] = None
    structure: Optional[list[Step]] = None
    planned_duration: Optional[float] = None
    planned_tss: Optional[float] = None
    status: Optional[WorkoutStatus] = None
    completed: Optional[CompletedInfo] = None
    is_template: Optional[bool] = None
    template_category: Optional[str] = None


class WorkoutOut(CamelModel):
    id: str
    plan_id: Optional[str] = None  # `ID | null` — always emitted
    date: Optional[str] = None  # `ID | null` — always emitted
    sport: Sport
    title: str
    description: Optional[str] = None
    structure: list[Step]
    planned_duration: int
    planned_tss: int
    status: WorkoutStatus
    completed: Optional[CompletedInfo] = None
    is_template: bool
    template_category: Optional[str] = None
    # "manual" (app-built), "garmin" (imported), or "coach" (assigned to me).
    source: WorkoutSource = "manual"
    # Coach who assigned this workout, when source == "coach".
    assigned_by_id: Optional[str] = None
    created_at: str
    updated_at: str


class ScheduleFromTemplateBody(CamelModel):
    date: str
    plan_id: Optional[str] = None


# --- aggregate & auth ----------------------------------------------------------


class AppSnapshot(CamelModel):
    athlete: AthleteOut
    plans: list[PlanOut]
    events: list[EventOut]
    workouts: list[WorkoutOut]


class SignupBody(CamelModel):
    email: str
    password: str
    name: Optional[str] = None


class LoginBody(CamelModel):
    email: str
    password: str


class DeleteAccountBody(CamelModel):
    password: str


class TokenResponse(CamelModel):
    token: str
    token_type: str = "bearer"


# --- garmin sync -----------------------------------------------------------


class GarminConnectBody(CamelModel):
    garmin_email: str
    garmin_password: str


class GarminMfaBody(CamelModel):
    mfa_code: str


class GarminConnectResult(CamelModel):
    # "connected" | "mfa_required"
    status: str


class GarminStatusOut(CamelModel):
    connected: bool
    garmin_email: Optional[str] = None
    state: str
    display_name: Optional[str] = None
    last_sync_at: Optional[str] = None
    last_verified_at: Optional[str] = None
    cooldown_remaining: int = 0
    last_error: Optional[str] = None


class GarminSyncResult(CamelModel):
    # "ok" | "skipped"
    status: str
    reason: Optional[str] = None
    imported: int = 0
    updated: int = 0
    matched: int = 0
    skipped: int = 0


class GarminThresholds(CamelModel):
    """Subset of ThresholdValues that Garmin can supply (any may be absent)."""

    ftp_watts: Optional[float] = None
    threshold_hr: Optional[float] = None
    run_threshold_pace_sec_per_km: Optional[float] = None


class GarminMetricsOut(CamelModel):
    # `thresholds` is applied by the client; `insights` is display-only
    # passthrough (vo2MaxRunning, vo2MaxCycling, racePredictions{...}).
    thresholds: GarminThresholds
    insights: dict[str, Any] = Field(default_factory=dict)
