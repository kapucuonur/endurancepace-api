"""Entrypoint shim so `uvicorn main:app` works with WorkingDirectory at the
repo root (matches the bikefit-api systemd unit style)."""

from app.main import app  # noqa: F401

if __name__ == "__main__":
    import uvicorn

    from app.config import settings

    uvicorn.run("app.main:app", host="0.0.0.0", port=settings.port, reload=True)
