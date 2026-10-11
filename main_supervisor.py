
"""
Free Arbitrage Mesh
Main FastAPI application and service health endpoints.

This file runs the web application.
Supervisor separately manages the Java engine, scraper, and task hunter.
Health checks do not imply that trades or earnings have occurred.
"""

from __future__ import annotations

import logging
import os
import time
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import database


APP_NAME = "Free Arbitrage Mesh"
APP_VERSION = "1.0.0"

PORT = int(os.getenv("PORT", "10000"))
HOST = os.getenv("HOST", "0.0.0.0")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").lower()

STARTED_AT = time.time()

logging.basicConfig(
    level=LOG_LEVEL.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("free-arbitrage-mesh")


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Initialize shared database tables when the web service starts."""
    logger.info("Starting %s.", APP_NAME)

    try:
        database.init_db()
        logger.info("Database initialization completed.")
    except Exception:
        logger.exception("Database initialization failed.")
        raise

    yield

    logger.info("Stopping %s.", APP_NAME)


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "Opportunity discovery and internal ledger service. "
        "Discovery estimates are not verified income."
    ),
    lifespan=lifespan,
)


@app.get("/", tags=["General"])
async def root():
    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "message": "Service endpoint is available.",
        "health_endpoint": "/health",
        "readiness_endpoint": "/ready",
    }


@app.get("/health", tags=["Health"])
async def health():
    """
    Lightweight process health check.

    This endpoint confirms that FastAPI can answer requests.
    It does not confirm database, market-feed, or worker health.
    """
    return {
        "service": APP_NAME,
        "status": "ok",
        "uptime_seconds": int(time.time() - STARTED_AT),
        "timestamp": int(time.time()),
    }


@app.get("/ready", tags=["Health"])
async def readiness():
    """Check whether the web service can access its database."""
    try:
        with database.get_connection() as connection:
            connection.execute("SELECT 1").fetchone()

        return {
            "service": APP_NAME,
            "ready": True,
            "database": "reachable",
            "timestamp": int(time.time()),
        }

    except Exception:
        logger.exception("Readiness check failed.")

        return JSONResponse(
            status_code=503,
            content={
                "service": APP_NAME,
                "ready": False,
                "database": "unavailable",
                "timestamp": int(time.time()),
            },
        )


@app.get("/api/system/status", tags=["System"])
async def system_status():
    """
    Report basic application status without exposing secrets,
    settlement-account information, or fabricated performance metrics.
    """
    database_status = "available"

    try:
        with database.get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
    except Exception:
        database_status = "unavailable"

    return {
        "service": APP_NAME,
        "version": APP_VERSION,
        "web_service": "running",
        "database": database_status,
        "task_feed_configured": bool(
            os.getenv("TASK_FEED_URL", "").strip()
        ),
        "market_page_configured": bool(
            os.getenv("MARKET_PAGE_URL", "").strip()
        ),
        "timestamp": int(time.time()),
    }


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL,
        access_log=True,
    )
