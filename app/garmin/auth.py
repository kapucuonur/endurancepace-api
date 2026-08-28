"""Garmin auth orchestration: connect / MFA / disconnect + the session-resume
ladder (DB blob -> disk -> full SSO). Ties GarminClient to garmin_sessions.
"""

from __future__ import annotations

import asyncio

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.crypto import decrypt_str, encrypt_str
from app.garmin import mfa_registry, session_store as store
from app.garmin.client import GarminClient
from app.models import Athlete, User


class GarminNotConnected(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_409_CONFLICT, "GARMIN_NOT_CONNECTED")


class GarminMfaRequired(HTTPException):
    def __init__(self) -> None:
        super().__init__(status.HTTP_409_CONFLICT, "GARMIN_MFA_REQUIRED")


class GarminRateLimited(HTTPException):
    def __init__(self, seconds: int) -> None:
        super().__init__(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Garmin is rate-limiting logins. Retry in ~{seconds // 60}m {seconds % 60}s.",
        )


def _user_of(db: Session, athlete: Athlete) -> User:
    return db.query(User).filter(User.id == athlete.user_id).first()


# --- connect / mfa -----------------------------------------------------------


async def connect(
    db: Session, athlete: Athlete, garmin_email: str, garmin_password: str
) -> dict:
    user = _user_of(db, athlete)
    sess = store.get_or_create(db, athlete.id)

    remaining = store.cooldown_remaining(sess)
    if remaining:
        raise GarminRateLimited(remaining)

    # Persist the credential up front — fixes the ai-coach bug where the
    # password is lost between /connect and /connect/mfa.
    user.garmin_email = garmin_email.strip().lower()
    user.garmin_password = encrypt_str(garmin_password)
    db.commit()

    client = GarminClient(user.garmin_email, garmin_password)
    outcome = await asyncio.to_thread(client.login_fresh)

    if outcome.status == "ok":
        store.save_tokens(db, sess, {"blob": outcome.tokens_blob}, outcome.display_name)
        await asyncio.to_thread(client.dump_to_disk)
        return {"status": "connected"}

    if outcome.status == "mfa_required":
        mfa_registry.stash(athlete.id, outcome.mfa_client_state or {})
        store.set_mfa_pending(db, sess)
        return {"status": "mfa_required"}

    if outcome.status == "rate_limited":
        store.set_cooldown(db, sess)
        raise GarminRateLimited(store.cooldown_remaining(sess))

    # failed — bad credentials: clear what we stored
    user.garmin_email = None
    user.garmin_password = None
    db.commit()
    store.mark_error(db, sess, outcome.message or "login failed")
    raise HTTPException(status.HTTP_400_BAD_REQUEST, outcome.message or "Garmin login failed")


async def complete_mfa(db: Session, athlete: Athlete, code: str) -> dict:
    user = _user_of(db, athlete)
    sess = store.get(db, athlete.id)

    if not store.mfa_pending_valid(sess):
        mfa_registry.drop(athlete.id)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "MFA session expired. Start over with POST /me/garmin/connect.",
        )
    client_state = mfa_registry.take(athlete.id)
    if client_state is None:
        # DB says pending but the in-process state is gone (worker restart, or a
        # different worker). Recoverable only by restarting the connect flow.
        store.clear_mfa(db, sess)
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "MFA session was lost (server restarted). Start over with POST /me/garmin/connect.",
        )

    password = decrypt_str(user.garmin_password) if user.garmin_password else None
    outcome = await asyncio.to_thread(
        GarminClient.complete_mfa, user.garmin_email, password, client_state, code.strip()
    )

    if outcome.status == "ok":
        store.save_tokens(db, sess, {"blob": outcome.tokens_blob}, outcome.display_name)
        store.clear_mfa(db, sess)
        return {"status": "connected"}

    if outcome.status == "rate_limited":
        store.clear_mfa(db, sess)
        store.set_cooldown(db, sess)
        raise GarminRateLimited(store.cooldown_remaining(sess))

    store.clear_mfa(db, sess)
    raise HTTPException(status.HTTP_400_BAD_REQUEST, outcome.message or "MFA failed")


def disconnect(db: Session, athlete: Athlete) -> None:
    user = _user_of(db, athlete)
    email = user.garmin_email
    user.garmin_email = None
    user.garmin_password = None
    db.commit()
    store.disconnect(db, athlete.id)
    if email:
        GarminClient.forget_disk(email)


# --- resume for data calls -------------------------------------------------


async def get_authed_client(db: Session, athlete: Athlete) -> GarminClient:
    """Session-resume ladder for data fetches. Raises if not usable."""
    user = _user_of(db, athlete)
    if not user.garmin_email or not user.garmin_password:
        raise GarminNotConnected()

    sess = store.get_or_create(db, athlete.id)
    remaining = store.cooldown_remaining(sess)
    if remaining:
        raise GarminRateLimited(remaining)

    password = decrypt_str(user.garmin_password)
    client = GarminClient(user.garmin_email, password)

    # tier 1: DB token blob
    blob = store.load_token_blob(sess)
    if blob and blob.get("blob"):
        if await asyncio.to_thread(client.restore, blob["blob"]):
            store.mark_verified(db, sess)
            return client

    # tier 2: disk
    if await asyncio.to_thread(client.restore_from_disk):
        fresh = client.current_blob()
        if fresh:
            store.save_tokens(db, sess, {"blob": fresh}, None)
        return client

    # tier 3: full SSO
    outcome = await asyncio.to_thread(client.login_fresh)
    if outcome.status == "ok":
        store.save_tokens(db, sess, {"blob": outcome.tokens_blob}, outcome.display_name)
        await asyncio.to_thread(client.dump_to_disk)
        return client
    if outcome.status == "mfa_required":
        mfa_registry.stash(athlete.id, outcome.mfa_client_state or {})
        store.set_mfa_pending(db, sess)
        raise GarminMfaRequired()
    if outcome.status == "rate_limited":
        store.set_cooldown(db, sess)
        raise GarminRateLimited(store.cooldown_remaining(sess))
    store.mark_error(db, sess, outcome.message or "login failed")
    raise HTTPException(status.HTTP_502_BAD_GATEWAY, outcome.message or "Garmin login failed")


def status_payload(db: Session, athlete: Athlete) -> dict:
    user = _user_of(db, athlete)
    sess = store.get(db, athlete.id)
    connected = bool(user.garmin_email and user.garmin_password)
    return {
        "connected": connected,
        "garminEmail": user.garmin_email,
        "state": (sess.status if sess else ("idle" if connected else "not_connected")),
        "displayName": sess.display_name if sess else None,
        "lastSyncAt": sess.last_sync_at if sess else None,
        "lastVerifiedAt": sess.last_verified_at if sess else None,
        "cooldownRemaining": store.cooldown_remaining(sess) if sess else 0,
        "lastError": sess.last_error if sess else None,
    }
