"""Runtime configuration, loaded from environment / .env (prefix ENDURANCEPACE_)."""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="ENDURANCEPACE_",
        extra="ignore",
    )

    database_url: str = "sqlite:///./endurancepace.db"

    # Auth — same scheme as bikefit-api (stateless JWT, HS256, sub = email).
    jwt_secret_key: str = "change-me-in-production"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24 * 7  # 7 days

    # Comma-separated browser origins. The native app sends no Origin so CORS
    # doesn't gate it — this only matters for the web build / dev tools.
    # Expo web dev ports plus the deployed web app; "*" is explicit opt-in.
    cors_origins: str = (
        "http://localhost:8081,http://localhost:19006,"
        "https://endurancepace.coachonurai.com"
    )

    # Gate for POST /me/reset (wipe + reseed the caller's own data).
    allow_reset: bool = False

    # Swagger /docs, /redoc, /openapi.json — off by default (attack-surface map).
    enable_docs: bool = False

    # Auth-route rate limiting (slowapi). Off in tests.
    ratelimit_enabled: bool = True

    port: int = 8006

    # --- Garmin sync (garminconnect/garth, email+password) ---------------------
    # Fernet key for encrypting stored Garmin passwords + session token blobs.
    # Generate: python -c "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())"
    field_encrypt_key: str = ""
    # Disk fallback for garth token dumps (session-resume ladder tier 2).
    garmin_session_dir: str = "~/.endurancepace_garth"
    # First-connect backfill window (days) and per-sync activity cap.
    garmin_sync_default_days: int = 30
    garmin_sync_activity_limit: int = 100
    # Minimum seconds between syncs for one athlete (debounces pull-to-refresh).
    garmin_sync_min_interval_seconds: int = 120
    # Abandoned MFA attempts older than this are treated as expired.
    garmin_mfa_ttl_seconds: int = 600
    # SSO 429 cooldown before another full login is attempted.
    garmin_login_cooldown_seconds: int = 900
    # Fire a best-effort sync from GET /me/snapshot.
    garmin_sync_on_snapshot: bool = False
    # Garmin activityType.typeKey substrings -> our sport. First match wins.
    garmin_sport_map: str = (
        "swimming=swim,cycling=bike,biking=bike,ride=bike,"
        "running=run,strength_training=strength"
    )

    @property
    def garmin_sport_rules(self) -> list[tuple[str, str]]:
        rules: list[tuple[str, str]] = []
        for pair in self.garmin_sport_map.split(","):
            if "=" in pair:
                key, sport = pair.split("=", 1)
                rules.append((key.strip().lower(), sport.strip()))
        return rules

    @property
    def cors_origin_list(self) -> list[str]:
        raw = self.cors_origins.strip()
        if raw == "*":
            return ["*"]
        return [o.strip() for o in raw.split(",") if o.strip()]


settings = Settings()
