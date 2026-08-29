"""Shared rate limiter (slowapi, in-memory — fine for a single worker).

Behind the Cloudflare Tunnel every request's peer address is the tunnel itself,
so key on `CF-Connecting-IP` (the real client) when present.
"""

from __future__ import annotations

from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from app.config import settings


def client_key(request: Request) -> str:
    return request.headers.get("cf-connecting-ip") or get_remote_address(request)


limiter = Limiter(key_func=client_key, enabled=settings.ratelimit_enabled)
