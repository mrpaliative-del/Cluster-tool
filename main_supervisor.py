
"""
Free Arbitrage Mesh — Consolidated API Supervisor
Version: 2.3.0

Combines:
- FastAPI supervisor and lifecycle management
- API health and readiness endpoints
- Database and configuration diagnostics
- Income Cascade validation

Security:
- No caller-supplied flag is accepted as proof of payment.
- Income allocation remains disabled until a trusted server-side
  payment-verification integration is implemented.
- This application does not execute trades or transfer funds.
"""

import logging
import os
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional

import uvicorn
from fastapi import FastAPI
from fastapi.responses import JSONResponse

import database


# =========================================================
# 1. CONFIGURATION
# =========================================================

HOST = os.getenv("HOST", "0.0.0.0")

try:
    PORT = int(os.getenv("PORT", "10000"))
    if not 1 <= PORT <= 65535:
        raise ValueError("PORT must be between 1 and 65535.")
except ValueError:
    PORT = 10000

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

if LOG_LEVEL not in logging._nameToLevel:
    LOG_LEVEL = "INFO"

SERVICE_NAME = "Free Arbitrage Mesh"
SERVICE_VERSION = "2.3.0"

STARTED_AT = time.monotonic()
STARTED_AT_UTC = datetime.now(timezone.utc).isoformat()

# Deliberately disabled until a trusted provider-side verifier
# is implemented and connected to the database receipt function.
INCOME_VERIFICATION_ENABLED = False

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("main_supervisor")
income_logger = logging.getLogger("income-cascade")


def utc_now() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""
    return datetime.now(timezone.utc).isoformat()


def get_uptime_seconds() -> float:
    """Return process uptime in seconds."""
    return round(time.monotonic() - STARTED_AT, 2)


# =========================================================
# 2. INCOME CASCADE
# =========================================================

def process_cascading_income(
    task_id,
    raw_payout,
    source_platform,
    *,
    verified=False,
    telegram_id=None,
):
    """
    Validate an income event without recording unverified income.

    IMPORTANT:
    A boolean such as verified=True is not proof that a payment
    was received. A trusted server-side payment-provider verifier
    must be implemented before this function can allocate receipts.

    Returns None when allocation is refused.
    """

    if verified is not True:
        income_logger.warning(
            "Rejected unverified income event: reference=%s",
            task_id,
        )
        return None

    reference = str(task_id or "").strip()
    source = str(source_platform or "").strip()

    if not reference or not source:
        income_logger.error(
            "Transaction reference and source platform are required."
        )
        return None

    try:
        amount = Decimal(str(raw_payout))

        if not amount.is_finite() or amount <= Decimal("0"):
            raise ValueError("Payout must be positive and finite.")

        amount = amount.quantize(Decimal("0.01"))

    except (InvalidOperation, TypeError, ValueError):
        income_logger.warning(
            "Rejected invalid payout amount for reference=%s",
            reference,
        )
        return None

    if telegram_id is None or not str(telegram_id).strip():
        income_logger.warning(
            "Missing owner identifier for reference=%s",
            reference,
        )
        return None

    # Fail closed: the previous database.py intentionally disables
    # record_deposit(). Never replace this with a direct deposit write.
    #
    # Before enabling income allocation, implement a trusted server-side
    # provider verifier that independently checks the transaction status,
    # reference, amount, currency, fees, refunds and settlement details.
    # That verifier must then call database.record_verified_receipt()
    # using its actual supported arguments.
    if not INCOME_VERIFICATION_ENABLED:
        income_logger.error(
            "Income allocation refused: trusted payment verification "
            "is not configured. reference=%s source=%s amount=%s",
            reference,
            source,
            amount,
        )
        return None

    # No code path below this point is enabled until a trusted verifier
    # has been integrated. Do not set the flag to True manually.
    return None


# =========================================================
# 3. DATABASE CHECKS
# =========================================================

def check_database() -> tuple[bool, Optional[str]]:
    """
    Test basic SQLite connectivity.

    Returns:
        (True, None) on success.
        (False, error_message) on failure.
    """
    try:
        with database.get_connection() as connection:
            connection.execute("SELECT 1").fetchone()

        return True, None

    except Exception as exc:
        logger.exception("Database connectivity check failed.")
        return False, str(exc)


# =========================================================
# 4. APPLICATION LIFECYCLE
# =========================================================

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(
        "%s API starting; version=%s",
        SERVICE_NAME,
        SERVICE_VERSION,
    )

    try:
        database.init_db()
        logger.info("Database initialization completed.")

    except Exception:
        logger.exception("Database initialization failed.")
        raise

    yield

    logger.info("%s API shutting down.", SERVICE_NAME)


# =========================================================
# 5. FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title=SERVICE_NAME,
    description=(
        "API health, readiness and configuration diagnostics "
        "for the Free Arbitrage Mesh monitoring system."
    ),
    version=SERVICE_VERSION,
    lifespan=lifespan,
)


# =========================================================
# 6. ROOT ENDPOINT
# =========================================================

@app.get("/", tags=["system"])
def root():
    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "status": "online",
        "message": (
            "The monitoring API is responding. External integrations "
            "and worker processes must be checked separately."
        ),
        "endpoints": {
            "health": "/health",
            "readiness": "/ready",
            "diagnostics": "/api/system/status",
            "api_docs": "/docs",
        },
    }


# =========================================================
# 7. LIVENESS ENDPOINT
# =========================================================

@app.get("/health", tags=["system"])
def health():
    """
    Liveness check.

    Confirms that the API can respond. It does not establish that
    the database, workers or external providers are operational.
    """
    return {
        "status": "ok",
        "service": "api",
        "version": SERVICE_VERSION,
        "uptime_seconds": get_uptime_seconds(),
        "started_at": STARTED_AT_UTC,
        "timestamp": utc_now(),
    }


# =========================================================
# 8. READINESS ENDPOINT
# =========================================================

@app.get("/ready", tags=["system"])
def readiness():
    """Check whether the API can access its SQLite database."""

    database_available, _ = check_database()

    if not database_available:
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "unavailable",
                "timestamp": utc_now(),
            },
        )

    return {
        "status": "ready",
        "database": "available",
        "timestamp": utc_now(),
    }


# =========================================================
# 9. SYSTEM DIAGNOSTICS
# =========================================================

@app.get("/api/system/status", tags=["system"])
def system_status():
    """
    Report API status and configuration presence.

    Secret values are never returned. Configuration presence does
    not prove that a provider connection or worker is functioning.
    """

    database_available, _ = check_database()

    telegram_configured = bool(
        os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
        and os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
    )

    task_feed_configured = bool(
        os.getenv("TASK_FEED_URL", "").strip()
    )

    price_monitor_configured = bool(
        os.getenv("MARKET_PAGE_URL", "").strip()
        and os.getenv("PRICE_SELECTOR", "").strip()
    )

    return {
        "service": SERVICE_NAME,
        "version": SERVICE_VERSION,
        "timestamp": utc_now(),
        "uptime_seconds": get_uptime_seconds(),
        "components": {
            "api": "responding",
            "database": (
                "available" if database_available else "unavailable"
            ),
            "task_feed": (
                "configured"
                if task_feed_configured
                else "not_configured"
            ),
            "price_monitor": (
                "configured"
                if price_monitor_configured
                else "not_configured"
            ),
            "telegram_alerts": (
                "configured"
                if telegram_configured
                else "not_configured"
            ),
            "java_engine": "simulation_only",
            "income_cascade": (
                "enabled"
                if INCOME_VERIFICATION_ENABLED
                else "disabled_pending_trusted_payment_verifier"
            ),
            "live_trade_execution": "not_implemented",
            "automated_fund_transfers": "not_implemented",
        },
        "notes": [
            "Configuration presence does not prove provider connectivity.",
            "Task discovery is not verified income.",
            "A verified receipt must be checked by a trusted server-side "
            "payment-provider integration.",
            "Ledger allocations do not represent real bank transfers.",
            "Price differences are indicative metrics, not realized profit.",
            "The Java engine is simulation-only.",
            "Live trade execution is not implemented.",
        ],
    }


# =========================================================
# 10. LOCAL ENTRY POINT
# =========================================================

if __name__ == "__main__":
    uvicorn.run(
        app,
        host=HOST,
        port=PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
    )
