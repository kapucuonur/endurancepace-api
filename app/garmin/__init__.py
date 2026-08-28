"""Garmin sync layer — data ingestion only (no coaching/reasoning).

Ported from ai-coach's Garmin integration with the in-memory session weaknesses
fixed: all auth/session/cooldown/MFA state lives in the `garmin_sessions` table.
All `garminconnect` / `garth` usage is isolated in `client.py`.
"""
