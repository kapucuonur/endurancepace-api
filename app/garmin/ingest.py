"""Pull Garmin activities and upsert them as EndurancePace Workouts.

Flow: claim the sync lock -> resume Garmin session -> fetch activities ->
sanitize -> for each: dedup by external_id, else match an existing planned
workout (same day+sport), else create. Release the lock.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.clock import now_iso, shift_days, today_iso
from app.config import settings
from app.garmin import session_store as store
from app.garmin.auth import get_authed_client
from app.garmin.mapper import activity_to_workout_fields, pick_match
from app.ids import new_id
from app.models import Athlete, Workout
from app.sanitize import sanitize_for_json

logger = logging.getLogger("endurancepace.garmin")


async def sync_activities(
    db: Session, athlete: Athlete, days: int | None = None
) -> dict:
    days = days or settings.garmin_sync_default_days
    sess = store.get_or_create(db, athlete.id)

    claimed, reason = store.begin_sync(db, sess)
    if not claimed:
        return {"status": "skipped", "reason": reason, "imported": 0, "updated": 0, "matched": 0, "skipped": 0}

    result = {"status": "ok", "imported": 0, "updated": 0, "matched": 0, "skipped": 0}
    try:
        client = await get_authed_client(db, athlete)
        raw = await asyncio.to_thread(
            client.get_activities, settings.garmin_sync_activity_limit
        )
        activities = sanitize_for_json(raw) or []
        cutoff = shift_days(today_iso(), -abs(days))

        for activity in activities:
            fields = activity_to_workout_fields(activity, athlete)
            if fields is None:
                result["skipped"] += 1
                continue
            if fields["date"] and fields["date"] < cutoff:
                continue

            ext = fields["external_id"]
            existing = (
                db.query(Workout)
                .filter(
                    Workout.athlete_id == athlete.id,
                    Workout.external_id == ext,
                )
                .first()
            )
            if existing:
                existing.status = "completed"
                existing.completed = fields["completed"]
                if existing.source == "garmin":
                    existing.planned_tss = fields["planned_tss"]
                    existing.planned_duration = fields["planned_duration"]
                existing.garmin_raw = activity
                existing.updated_at = now_iso()
                result["updated"] += 1
                continue

            match = _find_planned_match(db, athlete, fields, activity)
            if match is not None:
                match.status = "completed"
                match.completed = fields["completed"]
                match.external_id = ext
                match.garmin_raw = activity
                match.updated_at = now_iso()
                result["matched"] += 1
                continue

            ts = now_iso()
            db.add(
                Workout(
                    id=new_id("wko"),
                    athlete_id=athlete.id,
                    plan_id=None,
                    date=fields["date"],
                    sport=fields["sport"],
                    title=fields["title"],
                    description=None,
                    structure=[],
                    planned_duration=fields["planned_duration"],
                    planned_tss=fields["planned_tss"],
                    status="completed",
                    completed=fields["completed"],
                    is_template=False,
                    template_category=None,
                    source="garmin",
                    external_id=ext,
                    garmin_raw=activity,
                    created_at=ts,
                    updated_at=ts,
                )
            )
            result["imported"] += 1

        db.commit()
        store.end_sync(db, sess, ok=True)
        return result
    except HTTPException as exc:
        # expected: not connected / MFA / rate-limited — release the lock, no noise
        db.rollback()
        store.end_sync(db, sess, ok=False, error=str(exc.detail))
        raise
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        store.end_sync(db, sess, ok=False, error=str(exc))
        logger.exception("Garmin sync failed for athlete %s", athlete.id)
        raise


def _find_planned_match(db: Session, athlete: Athlete, fields: dict, activity: dict):
    if not fields["date"]:
        return None
    candidates = (
        db.query(Workout)
        .filter(
            Workout.athlete_id == athlete.id,
            Workout.date == fields["date"],
            Workout.sport == fields["sport"],
            Workout.status == "planned",
            Workout.is_template.is_(False),
            Workout.external_id.is_(None),
        )
        .all()
    )
    chosen = pick_match(candidates, activity)
    if chosen is not None and len(candidates) > 1:
        note = dict(activity)
        note["_matchNote"] = (
            f"ambiguous: {len(candidates)} planned {fields['sport']} workouts on "
            f"{fields['date']}; picked by closest duration"
        )
        activity.clear()
        activity.update(note)
    return chosen
