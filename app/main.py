"""FastAPI application factory + wiring."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app import __version__
from app.config import settings
from app.ratelimit import limiter
from app.routers import athlete, auth, events, garmin, plans, snapshot, workouts

# Docs / OpenAPI are OFF by default — they map the whole attack surface.
# Set ENDURANCEPACE_ENABLE_DOCS=true for local dev.
_docs = "/docs" if settings.enable_docs else None
_redoc = "/redoc" if settings.enable_docs else None
_openapi = "/openapi.json" if settings.enable_docs else None

app = FastAPI(
    title="EndurancePace API",
    version=__version__,
    description="Backend for the EndurancePace training app. "
    "Endpoints map 1:1 to the frontend's EnduranceApi interface.",
    docs_url=_docs,
    redoc_url=_redoc,
    openapi_url=_openapi,
)

if settings.cors_origin_list == ["*"]:
    _cors = {"allow_origins": ["*"]}
else:
    # Also allow the Expo dev client's exp:// origins alongside the explicit list.
    _cors = {
        "allow_origins": settings.cors_origin_list,
        "allow_origin_regex": r"^exp(o)?://.*",
    }

app.add_middleware(
    CORSMiddleware,
    allow_credentials=False,  # bearer tokens, not cookies
    allow_methods=["*"],
    allow_headers=["*"],
    **_cors,
)

# Rate limiting — explicit @limiter.limit on the auth routes only.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "version": __version__}


for r in (
    auth.router,
    snapshot.router,
    athlete.router,
    plans.router,
    events.router,
    workouts.router,
    garmin.router,
):
    app.include_router(r)
