
"""
Free Arbitrage Mesh — API Supervisor
Version: 2.1.0

Provides health, readiness, and configuration diagnostics.
It does not claim that external feeds, scraping, or trading work
merely because their processes have started.
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import database


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "10000"))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

STARTED_AT = time.monotonic()
STARTED_AT_UTC = datetime.now(timezone.utc).isoformat()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("main_supervisor")


# ---------------------------------------------------------
# Application lifecycle
# ---------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Free Arbitrage Mesh API starting.")

    try:
        database.init_db()
        logger.info("Application database initialized.")
    except Exception:
        logger.exception("Database initialization failed.")
        raise

    yield

    logger.info("Free Arbitrage Mesh API shutting down.")


app = FastAPI(
    title="Free Arbitrage Mesh",
    description=(
        "API health and configuration diagnostics for the "
        "Free Arbitrage Mesh monitoring system."
    ),
    version="2.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------

@app.get("/", tags=["system"])
def root():
    return {
        "service": "Free Arbitrage Mesh",
        "version": "2.1.0",
        "status": "online",
        "message": (
            "Monitoring API is responding. External integrations "
            "must be checked separately."
        ),
        "health_url": "/health",
        "readiness_url": "/ready",
        "diagnostics_url": "/api/system/status",
    }


@app.get("/health", tags=["system"])
def health():
    """
    Liveness check: confirms the API can respond to a request.
    It does not verify external providers or worker processes.
    """
    return {
        "status": "ok",
        "service": "api",
        "uptime_seconds": round(time.monotonic() - STARTED_AT, 2),
        "started_at": STARTED_AT_UTC,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/ready", tags=["system"])
def readiness():
    """Readiness check for the application's SQLite database."""
    try:
        with database.get_connection() as connection:
            connection.execute("SELECT 1").fetchone()

        return {
            "status": "ready",
            "database": "available",
        }

    except Exception:
        logger.exception("Readiness check failed.")

        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "unavailable",
            },
        )


@app.get("/api/system/status", tags=["system"])
def system_status():
    """
    Reports configuration presence, not integration success.
    Never returns secret values.
    """
    try:
        with database.get_connection() as connection:
            connection.execute("SELECT 1").fetchone()
        database_status = "available"
    except Exception:
        logger.exception("Database status check failed.")
        database_status = "unavailable"

    telegram_configured = bool(
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    )

    return {
        "service": "Free Arbitrage Mesh",
        "version": "2.1.0",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "uptime_seconds": round(time.monotonic() - STARTED_AT, 2),
        "components": {
            "api": "responding",
            "database": database_status,
            "task_feed": (
                "configured"
                if os.getenv("TASK_FEED_URL", "").strip()
                else "not_configured"
            ),
            "price_monitor": (
                "configured"
                if (
                    os.getenv("MARKET_PAGE_URL", "").strip()
                    and os.getenv("PRICE_SELECTOR", "").strip()
                )
                else "not_configured"
            ),
            "telegram_alerts": (
                "configured" if telegram_configured else "not_configured"
            ),
            "java_engine": "simulation_only",
            "live_trade_execution": "not_implemented",
        },
        "notes": [
            "Configuration does not prove provider connectivity.",
            "Task discovery is not verified income.",
            "Price differences are indicative metrics, not realized profit.",
            "No live trade execution is implemented.",
        ],
    }


# ---------------------------------------------------------
# Local entry point
# ---------------------------------------------------------

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
    )
