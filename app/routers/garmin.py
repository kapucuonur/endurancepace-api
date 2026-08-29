"""Garmin sync endpoints (all under the authenticated athlete).

- POST   /me/garmin/connect       {garminEmail, garminPassword} -> connected | mfa_required
- POST   /me/garmin/connect/mfa   {mfaCode}                     -> connected
- DELETE /me/garmin/connect                                     -> 204
- GET    /me/garmin/status
- POST   /me/garmin/sync          ?days=                        -> counts
- GET    /me/garmin/activities    ?limit=   (raw passthrough, debug)
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from app.deps import get_current_athlete
from app.database import get_db
from app.garmin import auth as garmin_auth
from app.garmin.ingest import sync_activities
from app.garmin.profile import athlete_metrics
from app.models import Athlete
from app.sanitize import sanitize_for_json
from app.schemas import (
    GarminConnectBody,
    GarminConnectResult,
    GarminMetricsOut,
    GarminMfaBody,
    GarminStatusOut,
    GarminSyncResult,
)

router = APIRouter(prefix="/me/garmin", tags=["garmin"])


@router.post("/connect", response_model=GarminConnectResult)
async def connect(
    body: GarminConnectBody,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> dict:
    return await garmin_auth.connect(
        db, athlete, body.garmin_email, body.garmin_password
    )


@router.post("/connect/mfa", response_model=GarminConnectResult)
async def connect_mfa(
    body: GarminMfaBody,
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> dict:
    return await garmin_auth.complete_mfa(db, athlete, body.mfa_code)


@router.delete("/connect", status_code=status.HTTP_204_NO_CONTENT)
def disconnect(
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> Response:
    garmin_auth.disconnect(db, athlete)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/status", response_model=GarminStatusOut)
def get_status(
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> dict:
    return garmin_auth.status_payload(db, athlete)


@router.get("/thresholds", response_model=GarminMetricsOut)
async def garmin_thresholds(
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> dict:
    """Preview training metrics from Garmin. Does not write — the client picks
    which fields to apply via PUT /me/athlete/thresholds."""
    import asyncio

    client = await garmin_auth.get_authed_client(db, athlete)
    return await asyncio.to_thread(athlete_metrics, client)


@router.post("/sync", response_model=GarminSyncResult)
async def sync(
    days: int | None = Query(default=None, ge=1, le=365),
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> dict:
    return await sync_activities(db, athlete, days=days)


@router.get("/activities")
async def raw_activities(
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    athlete: Athlete = Depends(get_current_athlete),
) -> list:
    client = await garmin_auth.get_authed_client(db, athlete)
    import asyncio

    data = await asyncio.to_thread(client.get_activities, limit)
    return sanitize_for_json(data) or []
