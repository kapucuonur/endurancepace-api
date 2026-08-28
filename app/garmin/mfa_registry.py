"""In-process holding area for a pending Garmin MFA `client_state`.

garth's `return_on_mfa` client_state contains a **live HTTP client** (session +
cookies from the SSO handshake) — it cannot be serialized to the DB and resumed
in another process. So the two-request MFA dance (`/connect` then `/connect/mfa`)
must land on the same worker.

Consequences, all acceptable for this deployment:
  - Run `uvicorn --workers 1` (already the plan). Data sync and every other bit
    of Garmin state is DB-backed and multi-worker-safe; only these two requests
    within a ~10-minute window are process-local.
  - A worker restart between the two requests drops the pending state -> the
    user just restarts with POST /me/garmin/connect (handled with a clear 400).

The authoritative TTL + `mfa_pending` status live in `garmin_sessions`; this
registry is a short-lived cache keyed by athlete id.
"""

from __future__ import annotations

import time
from typing import Any

from app.config import settings

_PENDING: dict[str, tuple[float, dict[str, Any]]] = {}


def stash(athlete_id: str, client_state: dict[str, Any]) -> None:
    _PENDING[athlete_id] = (time.time(), client_state)


def take(athlete_id: str) -> dict[str, Any] | None:
    entry = _PENDING.pop(athlete_id, None)
    if entry is None:
        return None
    started, state = entry
    if time.time() - started > settings.garmin_mfa_ttl_seconds:
        return None
    return state


def drop(athlete_id: str) -> None:
    _PENDING.pop(athlete_id, None)
