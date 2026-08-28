"""DB-backed Garmin session state.

Replaces ai-coach's module-level dicts:
  GLOBAL_CLIENTS        -> garmin_sessions.token_blob (encrypted)
  SESSION_LAST_VERIFIED -> garmin_sessions.last_verified_at
  FAILED_LOGIN_COOLDOWN -> garmin_sessions.cooldown_until
  PENDING_SESSIONS      -> garmin_sessions.mfa_client_state (+ mfa_initiated_at TTL)

Everything here is safe under multiple uvicorn workers.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from app.clock import now_iso
from app.config import settings
from app.crypto import decrypt_json, encrypt_json
from app.models import GarminSession


def _parse(iso: str | None) -> datetime | None:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def get_or_create(db: Session, athlete_id: str) -> GarminSession:
    sess = (
        db.query(GarminSession)
        .filter(GarminSession.athlete_id == athlete_id)
        .first()
    )
    if sess is None:
        ts = now_iso()
        sess = GarminSession(
            athlete_id=athlete_id, status="error", created_at=ts, updated_at=ts
        )
        db.add(sess)
        db.flush()
    return sess


def get(db: Session, athlete_id: str) -> GarminSession | None:
    return (
        db.query(GarminSession)
        .filter(GarminSession.athlete_id == athlete_id)
        .first()
    )


# --- tokens --------------------------------------------------------------------


def load_token_blob(sess: GarminSession) -> dict | None:
    return decrypt_json(sess.token_blob) if sess.token_blob else None


def save_tokens(
    db: Session, sess: GarminSession, blob: dict, display_name: str | None
) -> None:
    sess.token_blob = encrypt_json(blob)
    if display_name:
        sess.display_name = display_name
    sess.status = "active"
    sess.last_verified_at = now_iso()
    sess.last_error = None
    sess.updated_at = now_iso()
    db.commit()


def mark_verified(db: Session, sess: GarminSession) -> None:
    sess.last_verified_at = now_iso()
    sess.status = "active"
    sess.updated_at = now_iso()
    db.commit()


def mark_error(db: Session, sess: GarminSession, message: str) -> None:
    sess.status = "error"
    sess.last_error = message[:2000]
    sess.updated_at = now_iso()
    db.commit()


def mark_expired(db: Session, sess: GarminSession) -> None:
    sess.status = "expired"
    sess.token_blob = None
    sess.updated_at = now_iso()
    db.commit()


# --- cooldown -----------------------------------------------------------------


def set_cooldown(db: Session, sess: GarminSession, seconds: int | None = None) -> None:
    seconds = seconds or settings.garmin_login_cooldown_seconds
    sess.cooldown_until = (
        (_now() + timedelta(seconds=seconds))
        .strftime("%Y-%m-%dT%H:%M:%S.")
        + "000Z"
    )
    sess.updated_at = now_iso()
    db.commit()


def cooldown_remaining(sess: GarminSession) -> int:
    until = _parse(sess.cooldown_until)
    if not until:
        return 0
    return max(0, int((until - _now()).total_seconds()))


# --- MFA (status + TTL; the resume state lives in mfa_registry) --------------


def set_mfa_pending(db: Session, sess: GarminSession) -> None:
    sess.mfa_initiated_at = now_iso()
    sess.status = "mfa_pending"
    sess.updated_at = now_iso()
    db.commit()


def mfa_pending_valid(sess: GarminSession) -> bool:
    """True if a pending MFA attempt exists and is within the TTL."""
    if not sess or sess.status != "mfa_pending" or not sess.mfa_initiated_at:
        return False
    started = _parse(sess.mfa_initiated_at)
    if not started:
        return False
    return (_now() - started).total_seconds() <= settings.garmin_mfa_ttl_seconds


def clear_mfa(db: Session, sess: GarminSession) -> None:
    sess.mfa_initiated_at = None
    if sess.status == "mfa_pending":
        sess.status = "error"
    sess.updated_at = now_iso()
    db.commit()


# --- sync lock / debounce ----------------------------------------------------


def begin_sync(db: Session, sess: GarminSession) -> tuple[bool, str | None]:
    """Claim the sync lock. False + reason if another sync is running or the
    last one was too recent."""
    if sess.sync_in_progress:
        # Stale-lock guard: if it's been "in progress" for >10 min, take it over.
        started = _parse(sess.updated_at)
        if started and (_now() - started).total_seconds() < 600:
            return False, "already_running"
    last = _parse(sess.last_sync_at)
    if last:
        elapsed = (_now() - last).total_seconds()
        if elapsed < settings.garmin_sync_min_interval_seconds:
            return False, "too_soon"
    sess.sync_in_progress = True
    sess.updated_at = now_iso()
    db.commit()
    return True, None


def end_sync(
    db: Session, sess: GarminSession, ok: bool, error: str | None = None
) -> None:
    sess.sync_in_progress = False
    if ok:
        sess.last_sync_at = now_iso()
        sess.last_error = None
    elif error:
        sess.last_error = error[:2000]
    sess.updated_at = now_iso()
    db.commit()


def disconnect(db: Session, athlete_id: str) -> None:
    db.query(GarminSession).filter(
        GarminSession.athlete_id == athlete_id
    ).delete()
    db.commit()
