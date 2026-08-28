"""Seed data — a faithful port of the frontend's src/services/seed.ts.

`apply_seed(db, athlete)` wipes the athlete's plans/events/workouts and replaces
them (and the athlete profile) with the sample dataset: one athlete profile,
one active plan, two races, ~2 weeks of workouts across swim/bike/run, plus
three library templates. Used by scripts/seed_db.py and POST /me/reset.

Completed-session jitter uses a fixed RNG seed so re-seeding is deterministic
(the TS version uses Math.random()).
"""

from __future__ import annotations

import random

from sqlalchemy.orm import Session

from app.clock import now_iso, shift_days, today_iso, week_start
from app.ids import new_id
from app.models import Athlete, RaceEvent, TrainingPlan, Workout
from app.workout_metrics import compute_workout_metrics
from app.zones import derive_zones

THRESHOLDS = {
    "ftpWatts": 265,
    "runThresholdPaceSecPerKm": 258,  # 4:18 /km
    "cssSecPer100m": 95,  # 1:35 /100m
    "thresholdHr": 168,
    "maxHr": 190,
}


# --- step helpers (mirror seed.ts `step` / `repeat`) --------------------------


def _step(step_type, *, seconds=None, meters=None, target=None, label=None):
    duration = None
    if seconds:
        duration = {"kind": "time", "seconds": seconds}
    elif meters:
        duration = {"kind": "distance", "meters": meters}
    out = {
        "id": new_id("st"),
        "type": step_type,
        "repeatCount": 1,
        "children": [],
        "duration": duration,
    }
    if target is not None:
        out["target"] = target
    if label is not None:
        out["label"] = label
    return out


def _repeat(count, children, label=None):
    out = {
        "id": new_id("st"),
        "type": "interval",
        "repeatCount": count,
        "children": children,
    }
    if label is not None:
        out["label"] = label
    return out


# --- workout templates -------------------------------------------------------


def _easy_run():
    return [
        _step("warmup", seconds=600, target={"hrZone": 1}, label="Easy warmup"),
        _step("steady", seconds=2400, target={"hrZone": 2}, label="Aerobic"),
        _step("cooldown", seconds=300, target={"hrZone": 1}),
    ]


def _run_intervals():
    return [
        _step("warmup", seconds=900, target={"hrZone": 1}),
        _repeat(
            6,
            [
                _step("interval", seconds=180, target={"hrZone": 4}, label="3 min hard"),
                _step("recovery", seconds=120, target={"hrZone": 1}, label="jog"),
            ],
            "6 x 3min Z4",
        ),
        _step("cooldown", seconds=600, target={"hrZone": 1}),
    ]


def _bike_endurance():
    return [
        _step("warmup", seconds=600, target={"powerZone": 2}),
        _step("steady", seconds=4800, target={"powerZone": 2}, label="Endurance"),
        _step("cooldown", seconds=600, target={"powerZone": 1}),
    ]


def _bike_threshold():
    return [
        _step("warmup", seconds=900, target={"powerZone": 2}),
        _repeat(
            3,
            [
                _step("interval", seconds=600, target={"powerZone": 4}, label="10 min FTP"),
                _step("recovery", seconds=300, target={"powerZone": 1}),
            ],
            "3 x 10min Z4",
        ),
        _step("cooldown", seconds=600, target={"powerZone": 1}),
    ]


def _swim_technique():
    return [
        _step("warmup", meters=400, target={"rpe": 3}, label="Warmup mix"),
        _repeat(
            8,
            [
                _step("interval", meters=50, target={"rpe": 6}, label="Drill/Swim"),
                _step("recovery", seconds=20, target={"rpe": 1}),
            ],
            "8 x 50",
        ),
        _step("steady", meters=600, target={"rpe": 5}, label="Pull"),
        _step("cooldown", meters=200, target={"rpe": 2}),
    ]


def _swim_threshold():
    return [
        _step("warmup", meters=400, target={"rpe": 3}),
        _repeat(
            5,
            [
                _step("interval", meters=200, target={"rpe": 7}, label="CSS 200s"),
                _step("recovery", seconds=25, target={"rpe": 1}),
            ],
            "5 x 200 @ CSS",
        ),
        _step("cooldown", meters=200, target={"rpe": 2}),
    ]


# offset (days from today), sport, title, builder
WEEK_PLAN = [
    (-7, "swim", "Swim — Technique", _swim_technique),
    (-6, "bike", "Bike — Endurance", _bike_endurance),
    (-5, "run", "Run — Easy aerobic", _easy_run),
    (-4, "swim", "Swim — CSS intervals", _swim_threshold),
    (-3, "bike", "Bike — FTP 3x10", _bike_threshold),
    (-2, "run", "Run — Track intervals", _run_intervals),
    (-1, "bike", "Bike — Long endurance", _bike_endurance),
    (0, "run", "Run — Easy aerobic", _easy_run),
    (1, "swim", "Swim — Technique", _swim_technique),
    (2, "bike", "Bike — FTP 3x10", _bike_threshold),
    (3, "run", "Run — Track intervals", _run_intervals),
    (4, "swim", "Swim — CSS intervals", _swim_threshold),
    (5, "bike", "Bike — Long endurance", _bike_endurance),
    (6, "run", "Run — Long run", _easy_run),
]

TEMPLATES = [
    ("run", "Run — Track intervals", "Speed", _run_intervals),
    ("bike", "Bike — FTP 3x10", "Threshold", _bike_threshold),
    ("swim", "Swim — Technique", "Technique", _swim_technique),
]


def apply_seed(db: Session, athlete: Athlete) -> None:
    """Replace this athlete's data (and profile) with the sample dataset."""
    rng = random.Random(42)
    ts = now_iso()
    today = today_iso()

    db.query(Workout).filter(Workout.athlete_id == athlete.id).delete()
    db.query(TrainingPlan).filter(TrainingPlan.athlete_id == athlete.id).delete()
    db.query(RaceEvent).filter(RaceEvent.athlete_id == athlete.id).delete()

    athlete.name = "Alex Rivera"
    athlete.disciplines = ["swim", "bike", "run", "strength"]
    athlete.thresholds = dict(THRESHOLDS)
    zones = derive_zones(THRESHOLDS)
    athlete.hr_zones = zones["hrZones"]
    athlete.power_zones = zones["powerZones"]
    athlete.run_pace_zones = zones["runPaceZones"]
    athlete.weight_kg = 70
    athlete.birthdate = "1992-04-18"
    athlete.updated_at = ts

    goal_event_id = new_id("evt")
    db.add_all(
        [
            RaceEvent(
                id=goal_event_id,
                athlete_id=athlete.id,
                name="Alpine Olympic Triathlon",
                date=shift_days(today, 70),
                sport="run",
                priority="A",
                distance="Olympic (1.5 / 40 / 10)",
                location="Annecy, FR",
                created_at=ts,
                updated_at=ts,
            ),
            RaceEvent(
                id=new_id("evt"),
                athlete_id=athlete.id,
                name="Local Sprint Tri",
                date=shift_days(today, 28),
                sport="run",
                priority="C",
                distance="Sprint (0.75 / 20 / 5)",
                location=None,
                created_at=ts,
                updated_at=ts,
            ),
        ]
    )

    plan_id = new_id("pln")
    db.add(
        TrainingPlan(
            id=plan_id,
            athlete_id=athlete.id,
            name="Base → Build: Annecy",
            start_date=week_start(shift_days(today, -7)),
            end_date=shift_days(today, 70),
            goal_event_id=goal_event_id,
            phase="build",
            blocks=[
                {"phase": "base", "weeks": 4},
                {"phase": "build", "weeks": 4},
                {"phase": "peak", "weeks": 2},
                {"phase": "taper", "weeks": 1},
            ],
            notes=(
                "Progressive build toward the A race. "
                "Bike-focused with 3 quality sessions/week."
            ),
            created_at=ts,
            updated_at=ts,
        )
    )

    for offset, sport, title, build in WEEK_PLAN:
        structure = build()
        metrics = compute_workout_metrics(structure, sport, THRESHOLDS)
        is_past = offset < 0
        skipped = offset == -4
        completed = None
        if is_past and not skipped:
            completed = {
                "date": shift_days(today, offset) + "T07:00:00.000Z",
                "durationSeconds": round(
                    metrics["durationSeconds"] * (0.95 + rng.random() * 0.1)
                ),
                "actualTss": round(metrics["tss"] * (0.95 + rng.random() * 0.1)),
                "rpe": 5 + rng.randint(0, 2),
            }
        db.add(
            Workout(
                id=new_id("wko"),
                athlete_id=athlete.id,
                plan_id=plan_id,
                date=shift_days(today, offset),
                sport=sport,
                title=title,
                description=None,
                structure=structure,
                planned_duration=metrics["durationSeconds"],
                planned_tss=metrics["tss"],
                status="skipped" if skipped else ("completed" if is_past else "planned"),
                completed=completed,
                is_template=False,
                template_category=None,
                created_at=ts,
                updated_at=ts,
            )
        )

    for sport, title, category, build in TEMPLATES:
        structure = build()
        metrics = compute_workout_metrics(structure, sport, THRESHOLDS)
        db.add(
            Workout(
                id=new_id("wko"),
                athlete_id=athlete.id,
                plan_id=None,
                date=None,
                sport=sport,
                title=title,
                description=None,
                structure=structure,
                planned_duration=metrics["durationSeconds"],
                planned_tss=metrics["tss"],
                status="planned",
                completed=None,
                is_template=True,
                template_category=category,
                created_at=ts,
                updated_at=ts,
            )
        )

    db.commit()
