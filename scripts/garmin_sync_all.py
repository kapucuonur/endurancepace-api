"""Sync every connected athlete's Garmin activities.

For a systemd timer (v2 — cron-style periodic sync without an in-process
scheduler). v1 relies on the app calling POST /me/garmin/sync.

    python -m scripts.garmin_sync_all
"""

from __future__ import annotations

import asyncio
import logging

from app.database import SessionLocal
from app.garmin.ingest import sync_activities
from app.models import Athlete, User

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("endurancepace.garmin.sync_all")


async def main() -> None:
    db = SessionLocal()
    try:
        connected = (
            db.query(Athlete)
            .join(User, User.id == Athlete.user_id)
            .filter(User.garmin_email.isnot(None), User.garmin_password.isnot(None))
            .all()
        )
        log.info("syncing %d connected athlete(s)", len(connected))
        for athlete in connected:
            try:
                res = await sync_activities(db, athlete)
                log.info("athlete %s: %s", athlete.id, res)
            except Exception as exc:  # noqa: BLE001
                log.warning("athlete %s failed: %s", athlete.id, exc)
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
