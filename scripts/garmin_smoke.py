"""REAL Garmin integration smoke test — hits Garmin's actual SSO. Run once by
hand before trusting the mocked pytest suite.

    export GARMIN_TEST_EMAIL="you@example.com"
    export GARMIN_TEST_PASSWORD="..."
    export ENDURANCEPACE_FIELD_ENCRYPT_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')"
    python -m scripts.garmin_smoke

Single process: connect -> (if MFA) wait for ./mfa_code.txt -> complete -> sync.
garth's MFA resume state can't cross processes, so the whole flow runs in one
invocation. Throwaway DB at ./garmin_smoke.db. Credentials come from the
environment only — never printed or logged.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.clock import now_iso
from app.database import Base
from app.garmin import auth as garmin_auth
from app.garmin.ingest import sync_activities
from app.garmin.mapper import tss_source
from app.ids import new_id
from app.models import Athlete, User, Workout

DB_PATH = "./garmin_smoke.db"
CODE_FILE = "./mfa_code.txt"


def _session():
    engine = create_engine(
        f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, autocommit=False)()


def _athlete(db):
    user = db.query(User).filter(User.email == "smoke@local").first()
    if not user:
        ts = now_iso()
        user = User(email="smoke@local", hashed_password="x", created_at=ts)
        db.add(user)
        db.flush()
        db.add(
            Athlete(
                id=new_id("ath"),
                user_id=user.id,
                name="Smoke",
                disciplines=["swim", "bike", "run", "strength"],
                thresholds={"thresholdHr": 165},  # lets the HR TSS fallback fire
                created_at=ts,
                updated_at=ts,
            )
        )
        db.commit()
    return db.query(Athlete).filter(Athlete.user_id == user.id).first()


def _wait_for_code(timeout_s: int = 480) -> str | None:
    if os.path.exists(CODE_FILE):
        os.remove(CODE_FILE)
    print(
        f"\n>>> MFA required. Write the code Garmin just sent to {CODE_FILE} "
        f"(e.g. `echo 123456 > {CODE_FILE}`). Waiting up to {timeout_s // 60} min...\n",
        flush=True,
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if os.path.exists(CODE_FILE):
            with open(CODE_FILE) as f:
                code = f.read().strip()
            os.remove(CODE_FILE)
            if code:
                return code
        time.sleep(3)
    return None


async def _sync_report(db, athlete) -> int:
    print("== status ==", flush=True)
    print("  ", garmin_auth.status_payload(db, athlete), flush=True)
    print("== sync (last 30d) ==", flush=True)
    print("  ", await sync_activities(db, athlete), flush=True)

    rows = (
        db.query(Workout)
        .filter(Workout.athlete_id == athlete.id, Workout.source == "garmin")
        .order_by(Workout.date.desc())
        .limit(10)
        .all()
    )
    print(f"== imported garmin workouts ({len(rows)} shown) ==", flush=True)
    src_counts: dict[str, int] = {}
    for w in rows:
        src = tss_source(w.garmin_raw or {})
        src_counts[src] = src_counts.get(src, 0) + 1
        actual = (w.completed or {}).get("actualTss")
        print(
            f"  {w.date}  {w.sport:5}  {w.planned_duration:>5}s  "
            f"actualTss={str(actual):>5} (from {src})  {(w.title or '')[:40]}",
            flush=True,
        )
    print("  TSS sources:", src_counts, flush=True)
    return 0


async def main() -> int:
    email = os.getenv("GARMIN_TEST_EMAIL")
    password = os.getenv("GARMIN_TEST_PASSWORD")
    if not email or not password:
        print("set GARMIN_TEST_EMAIL and GARMIN_TEST_PASSWORD", file=sys.stderr)
        return 2
    if not os.getenv("ENDURANCEPACE_FIELD_ENCRYPT_KEY"):
        print("set ENDURANCEPACE_FIELD_ENCRYPT_KEY (Fernet key)", file=sys.stderr)
        return 2

    db = _session()
    athlete = _athlete(db)

    print("== connect ==", flush=True)
    res = await garmin_auth.connect(db, athlete, email, password)
    print("  ->", res, flush=True)

    if res["status"] == "mfa_required":
        code = _wait_for_code()
        if not code:
            print("  no code provided; aborting", flush=True)
            return 1
        print("== connect/mfa ==", flush=True)
        res = await garmin_auth.complete_mfa(db, athlete, code)
        print("  ->", res, flush=True)

    if res.get("status") != "connected":
        print("  connect failed", flush=True)
        return 1

    return await _sync_report(db, athlete)


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
