"""
TrueBellaa API — application entry point.

Run locally:
    uvicorn app.main:app --reload
Interactive docs:
    http://localhost:8000/docs
"""
import logging
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from sqlalchemy import text

from app.core.config import settings
from app.core.database import read_engine
from app.api.v1 import api_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s: %(message)s")

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description="Multi-tenant jewellery commerce backend (FastAPI + MySQL).",
)


class CatchErrorsMiddleware(BaseHTTPMiddleware):
    """
    Turn any unhandled exception into a JSON 500 *inside* the CORS layer, so
    the browser still receives the Access-Control-Allow-Origin header. Without
    this, a server error (e.g. the DB being unreachable) shows up in the
    browser as a confusing "CORS policy" error instead of the real cause.
    """
    async def dispatch(self, request: Request, call_next):
        try:
            return await call_next(request)
        except Exception as exc:  # noqa: BLE001
            detail = f"{type(exc).__name__}: {exc}" if settings.DEBUG else "Internal server error"
            return JSONResponse(status_code=500, content={"detail": detail})


# NOTE on order: the LAST middleware added is the OUTERMOST. We add the error
# catcher first and CORS second, so CORS wraps the catcher — meaning the JSON
# 500 the catcher returns still gets CORS headers on the way out.
app.add_middleware(CatchErrorsMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)

# DEMO-mode image storage: served locally whenever MilesWeb FTP credentials
# aren't configured yet (see app/integrations/mileswebstorage_client.py).
# In LIVE mode images live on MilesWeb and this mount is simply unused.
os.makedirs(settings.LOCAL_UPLOAD_DIR, exist_ok=True)
app.mount(
    settings.LOCAL_UPLOAD_PUBLIC_BASE_URL, StaticFiles(directory=settings.LOCAL_UPLOAD_DIR), name="uploads"
)


@app.get("/health", tags=["system"])
def health():
    """Reports app status AND whether the database is reachable."""
    db_ok, db_error = True, None
    try:
        with read_engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:  # noqa: BLE001
        db_ok, db_error = False, str(exc)
    return {
        "status": "ok" if db_ok else "degraded",
        "app": settings.APP_NAME, "env": settings.ENV,
        "database_connected": db_ok,
        "database_error": db_error,
        "razorpay_live": settings.razorpay_live,
        "shiprocket_live": settings.shiprocket_live,
        "ftp_live": settings.ftp_live,
    }


