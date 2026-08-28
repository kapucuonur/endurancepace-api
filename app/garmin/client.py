"""The ONLY module that imports `garminconnect` / `garth`.

`garth` is unmaintained (deprecation warning on import) and this whole approach
relies on Garmin's private web API — keep every bit of that surface here so a
future swap touches one file. All methods are blocking; callers wrap them in
`asyncio.to_thread`.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from garminconnect import (  # type: ignore
    Garmin,
    GarminConnectAuthenticationError,
    GarminConnectTooManyRequestsError,
)
from garth import sso as garth_sso  # type: ignore

from app.config import settings

logger = logging.getLogger("endurancepace.garmin")

LoginStatus = Literal["ok", "mfa_required", "rate_limited", "failed"]


@dataclass
class LoginOutcome:
    status: LoginStatus
    tokens_blob: str | None = None
    display_name: str | None = None
    mfa_client_state: dict[str, Any] | None = None
    message: str | None = None


def _is_rate_limited(err: Exception) -> bool:
    s = str(err)
    return isinstance(err, GarminConnectTooManyRequestsError) or (
        "429" in s or "Too Many Requests" in s
    )


def _session_dir(email: str) -> Path:
    safe = email.replace("@", "_at_").replace("/", "_").replace(".", "_")
    return Path(settings.garmin_session_dir).expanduser() / safe


class GarminClient:
    def __init__(self, email: str, password: str | None = None):
        self.email = email
        self.password = password
        self._api: Garmin | None = None

    # -- auth ---------------------------------------------------------------

    def restore(self, tokens_blob: str) -> bool:
        """Load persisted tokens. Zero network calls (garth refreshes OAuth2
        lazily on the first real request; a "verify" call here just triggers a
        429 cascade — see ai-coach's restore_session_from_data note)."""
        try:
            api = Garmin(self.email, self.password or None)
            # garth treats a >512-char tokenstore as an inline base64 string.
            api.login(tokenstore=tokens_blob)
            self._api = api
            self._ensure_display_name(network_ok=False)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Garmin token restore failed for %s: %s", self.email, exc)
            self._api = None
            return False

    def restore_from_disk(self) -> bool:
        d = _session_dir(self.email)
        if not d.exists():
            return False
        try:
            api = Garmin(self.email, self.password or None)
            api.login(tokenstore=str(d))
            self._api = api
            self._ensure_display_name(network_ok=False)
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning("Garmin disk restore failed for %s: %s", self.email, exc)
            return False

    def login_fresh(self) -> LoginOutcome:
        """Full SSO with resumable MFA (`return_on_mfa=True`)."""
        if not self.password:
            return LoginOutcome("failed", message="Garmin password not provided")
        try:
            api = Garmin(self.email, self.password, return_on_mfa=True)
            res = api.login()
            if isinstance(res, tuple) and res and res[0] == "needs_mfa":
                return LoginOutcome("mfa_required", mfa_client_state=res[1])
            self._api = api
            self._ensure_display_name(network_ok=True)
            return LoginOutcome(
                "ok",
                tokens_blob=api.garth.dumps(),
                display_name=self._display_name(),
            )
        except GarminConnectAuthenticationError as exc:
            return LoginOutcome("failed", message=f"Invalid Garmin credentials: {exc}")
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limited(exc):
                return LoginOutcome("rate_limited", message=str(exc))
            return LoginOutcome("failed", message=str(exc))

    @classmethod
    def complete_mfa(
        cls, email: str, password: str | None, client_state: dict[str, Any], code: str
    ) -> LoginOutcome:
        try:
            oauth1, oauth2 = garth_sso.resume_login(client_state, code)
            # Reuse the handshake client (it has the SSO cookies), stamp the
            # tokens on it, serialize.
            gclient = client_state["client"]
            gclient.configure(oauth1_token=oauth1, oauth2_token=oauth2)
            blob = gclient.dumps()

            api = Garmin(email, password or None)
            api.login(tokenstore=blob)  # load tokens into the garminconnect wrapper
            self = cls(email, password)
            self._api = api
            self._ensure_display_name(network_ok=True)
            return LoginOutcome(
                "ok", tokens_blob=api.garth.dumps(), display_name=self._display_name()
            )
        except Exception as exc:  # noqa: BLE001
            if _is_rate_limited(exc):
                return LoginOutcome("rate_limited", message=str(exc))
            return LoginOutcome("failed", message=f"MFA verification failed: {exc}")

    def dump_to_disk(self) -> None:
        if not self._api:
            return
        try:
            d = _session_dir(self.email)
            d.mkdir(parents=True, exist_ok=True)
            self._api.garth.dump(str(d))
        except Exception as exc:  # noqa: BLE001
            logger.debug("disk token dump failed: %s", exc)

    @staticmethod
    def forget_disk(email: str) -> None:
        d = _session_dir(email)
        try:
            for f in d.glob("*"):
                f.unlink(missing_ok=True)
            d.rmdir()
        except OSError:
            pass

    def current_blob(self) -> str | None:
        return self._api.garth.dumps() if self._api else None

    # -- display name (Garmin 403s if it's an email) -----------------------

    def _display_name(self) -> str | None:
        dn = getattr(self._api, "display_name", None)
        return dn if dn and "@" not in dn else None

    def _ensure_display_name(self, *, network_ok: bool) -> None:
        if not self._api:
            return
        if self._display_name():
            return
        if not network_ok:
            self._api.display_name = self.email  # lazily fixed before first call
            return
        try:
            prof = self._api.get_user_profile()
            name = (prof or {}).get("displayName")
            if name:
                self._api.display_name = name
        except Exception:  # noqa: BLE001
            self._api.display_name = self.email

    # -- data (blocking) --------------------------------------------------

    @property
    def ready(self) -> bool:
        return self._api is not None

    def get_activities(self, limit: int) -> list[dict]:
        self._ensure_display_name(network_ok=True)
        return self._api.get_activities(0, limit) or []  # type: ignore[union-attr]

    def get_activity_details(self, activity_id: str | int) -> dict | None:
        self._ensure_display_name(network_ok=True)
        api = self._api
        assert api is not None
        details = api.get_activity(activity_id)
        if not details:
            return None
        try:
            splits = api.get_activity_splits(activity_id)
            if splits:
                details["splits"] = splits
        except Exception as exc:  # noqa: BLE001
            logger.debug("splits fetch failed for %s: %s", activity_id, exc)
        return details

    def get_profile(self) -> dict | None:
        self._ensure_display_name(network_ok=True)
        return self._api.get_user_profile()  # type: ignore[union-attr]
