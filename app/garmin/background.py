"""Fire-and-forget Garmin sync (ai-coach's `fire_sync` pattern).

Used by GET /me/snapshot when ENDURANCEPACE_GARMIN_SYNC_ON_SNAPSHOT=true. Runs
in a daemon thread with its own DB session; the sync lock + min-interval
debounce in session_store keep concurrent requests from double-processing.
"""

from __future__ import annotations

import asyncio
import logging
import threading

from app.database import SessionLocal
from app.models import Athlete, GarminSession, User

logger = logging.getLogger("endurancepace.garmin")


def _run(athlete_id: str) -> None:
    from app.garmin.ingest import sync_activities  # avoid import cycle

    db = SessionLocal()
    try:
        athlete = db.query(Athlete).filter(Athlete.id == athlete_id).first()
        if athlete is None:
            return
        asyncio.run(sync_activities(db, athlete))
    except Exception as exc:  # noqa: BLE001
        logger.warning("background garmin sync failed for %s: %s", athlete_id, exc)
    finally:
        db.close()


def maybe_sync(db, athlete: Athlete) -> None:
    """Kick a background sync only if this athlete has Garmin connected."""
    user = db.query(User).filter(User.id == athlete.user_id).first()
    if not user or not (user.garmin_email and user.garmin_password):
        return
    sess = db.query(GarminSession).filter(GarminSession.athlete_id == athlete.id).first()
    if sess and sess.sync_in_progress:
        return
    threading.Thread(target=_run, args=(athlete.id,), daemon=True).start()
