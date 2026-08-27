"""Timestamp helpers.

The frontend stores timestamps as `new Date().toISOString()` — millisecond
precision, `Z` suffix (e.g. `2026-08-29T06:30:00.000Z`). We emit the exact same
shape so records round-trip through the API with zero reformatting.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone


def now_iso() -> str:
    """UTC now as `YYYY-MM-DDTHH:MM:SS.mmmZ`."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def today_iso() -> str:
    """Today's calendar day as `YYYY-MM-DD` (matches frontend `todayISO()`)."""
    return date.today().isoformat()


def shift_days(iso_date: str, days: int) -> str:
    return (date.fromisoformat(iso_date) + timedelta(days=days)).isoformat()


def week_start(iso_date: str) -> str:
    """Monday of the week containing `iso_date` (frontend weeks are Monday-first)."""
    d = date.fromisoformat(iso_date)
    return (d - timedelta(days=d.weekday())).isoformat()
