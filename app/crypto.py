"""Field-level encryption for Garmin credentials + session token blobs.

Port of ai-coach `auth_utils.encrypt_garmin_password` / `decrypt_garmin_password`.
Symmetric (Fernet); the Garmin API needs the raw password to log in, so it
cannot be hashed. Key comes from ENDURANCEPACE_FIELD_ENCRYPT_KEY.
"""

from __future__ import annotations

import json
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from app.config import settings


def _fernet() -> Fernet:
    key = settings.field_encrypt_key
    if not key:
        raise RuntimeError(
            "ENDURANCEPACE_FIELD_ENCRYPT_KEY is not set — required for Garmin sync."
        )
    return Fernet(key.encode() if isinstance(key, str) else key)


def encrypt_str(plaintext: str) -> str:
    if not plaintext:
        return plaintext
    return _fernet().encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_str(ciphertext: str) -> str:
    """Decrypt; if the value isn't valid ciphertext, assume legacy plaintext."""
    if not ciphertext:
        return ciphertext
    try:
        return _fernet().decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except (InvalidToken, ValueError):
        return ciphertext


def encrypt_json(obj: Any) -> str:
    return encrypt_str(json.dumps(obj, separators=(",", ":")))


def decrypt_json(ciphertext: str) -> Any:
    if not ciphertext:
        return None
    raw = decrypt_str(ciphertext)
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
