
"""
Free Arbitrage Mesh — Main Supervisor
-------------------------------------
Responsibilities:
- FastAPI application and Render health endpoints
- Optional Telegram bot and webhook
- Database initialization and status reporting
- Idempotent income recording through database.py
- Safe background task lifecycle

Important:
- No fabricated revenue or automatic deposits.
- No automatic trading or bank transfers.
- Only trusted, verified payment/task handlers should call
  process_cascading_income().
"""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import time
from contextlib import asynccontextmanager
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse

import database


# ============================================================
# 1. CONFIGURATION
# ============================================================

APP_NAME = "Free Arbitrage Mesh"
APP_VERSION = "2.0.0"

PORT = int(os.getenv("PORT", "10000"))
HOST = os.getenv("HOST", "0.0.0.0")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()

RENDER_EXTERNAL_URL = os.getenv(
    "RENDER_EXTERNAL_URL", ""
).strip().rstrip("/")

TELEGRAM_WEBHOOK_SECRET = os.getenv(
    "TELEGRAM_WEBHOOK_SECRET", ""
).strip()

# This is optional. Set to "true" only if you explicitly want
# this instance to configure Telegram's webhook at startup.
ENABLE_TELEGRAM_WEBHOOK = (
    os.getenv("ENABLE_TELEGRAM_WEBHOOK", "false").lower() == "true"
)

# Do not put payment secrets or bot tokens in source code.
# Payment-provider verification belongs in a separate, authenticated
# payment webhook handler.

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("free_arbitrage_mesh")


# ============================================================
# 2. OPTIONAL TELEGRAM CLIENT
# ============================================================

bot = None
telegram_types = None

if TELEGRAM_BOT_TOKEN:
    try:
        import telebot
        from telebot import types as _telegram_types

        bot = telebot.TeleBot(
            TELEGRAM_BOT_TOKEN,
            threaded=False,
        )
        telegram_types = _telegram_types

        logger.info("Telegram client configured.")

    except ImportError:
        logger.exception(
            "Telegram token is configured, but pyTelegramBotAPI "
            "is not installed. Telegram integration is disabled."
        )
        bot = None

else:
    logger.warning(
        "TELEGRAM_BOT_TOKEN is not configured; Telegram is disabled."
    )


# ============================================================
# 3. SMALL UTILITIES
# ============================================================

def _safe_database_health() -> dict[str, Any]:
    """Return database health without exposing internal exceptions."""
    checker = getattr(database, "check_database_health", None)

    if callable(checker):
        result = checker()
        if isinstance(result, dict):
            return result
        return {"status": "unknown", "result": str(result)}

    # Compatibility fallback for database.py versions that do not
    # yet expose check_database_health().
    initializer = getattr(database, "init_db", None)
    if not callable(initializer):
        return {
            "status": "error",
            "message": "Database initializer is missing.",
        }

    initializer()
    return {"status": "ok"}


def _safe_metrics() -> dict[str, Any]:
    """Get the available ledger metrics, if the function exists."""
    getter = getattr(
        database,
        "get_comprehensive_performance_metrics",
        None,
    )

    if not callable(getter):
        return {
            "status": "unavailable",
            "message": "Metrics function is not available.",
        }

    result = getter()
    return result if isinstance(result, dict) else {
        "result": str(result)
    }


def _send_telegram_message(
    chat_id: str | int,
    message: str,
) -> bool:
    """Send a Telegram message if the client is configured."""
    if bot is None:
        return False

    try:
        bot.send_message(chat_id, message)
        return True
    except Exception:
        logger.exception("Telegram message delivery failed.")
        return False


def notify_admin(message: str) -> bool:
    """Send an operational notification to the configured admin."""
    if not TELEGRAM_ADMIN_CHAT_ID:
        logger.info("Admin notification skipped: no admin chat configured.")
        return False

    return _send_telegram_message(
        TELEGRAM_ADMIN_CHAT_ID,
        message,
    )


# ============================================================
# 4. VERIFIED INCOME CASCADE
# ============================================================

def process_cascading_income(
    telegram_id: int,
    amount: float,
    reference: str,
    *,
    verified: bool = False,
    verification_source: str = "",
) -> dict[str, Any]:
    """
    Record one verified income event using database.py.

    The database.record_deposit() function is responsible for
    idempotency and distributing the amount using its configured
    portfolio split.

    This function does NOT:
    - verify a Paystack payment by itself;
    - execute bank transfers;
    - create profit from scanning;
    - guarantee that an external task was paid.

    Call this only after a trusted server-side handler has verified
    the payment or confirmed the actual receipt of funds.

    Do not expose this function through an unauthenticated API route.
    """

    if not verified:
        raise ValueError(
            "Income rejected: the payment/task receipt has not been verified."
        )

    allowed_sources = {
        "paystack_verified_webhook",
        "verified_task_payment",
        "verified_manual_receipt",
    }

    if verification_source not in allowed_sources:
        raise ValueError(
            "Income rejected: verification source is not allowed."
        )

    if isinstance(telegram_id, bool) or int(telegram_id) <= 0:
        raise ValueError("telegram_id must be a positive integer.")

    reference = str(reference).strip()
    if not reference or len(reference) > 200:
        raise ValueError("A valid transaction reference is required.")

    try:
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid income amount.") from exc

    if (
        not decimal_amount.is_finite()
        or decimal_amount <= 0
    ):
        raise ValueError("Income amount must be positive and finite.")

    # database.py expects a numeric amount. It performs the actual
    # idempotent deposit and configured portfolio allocation.
    recorded = database.record_deposit(
        reference=reference,
        telegram_id=int(telegram_id),
        amount=float(decimal_amount),
    )

    if not recorded:
        logger.info(
            "Duplicate income reference ignored: %s",
            reference,
        )
        return {
            "ok": True,
            "status": "duplicate_ignored",
            "reference": reference,
        }

    logger.info(
        "Verified income recorded. reference=%s amount=%s source=%s",
        reference,
        decimal_amount,
        verification_source,
    )

    notify_admin(
        "Verified income recorded in the internal ledger.\n"
        f"Reference: {reference}\n"
        f"Amount: {decimal_amount}\n"
        f"Source: {verification_source}\n"
        "This confirms ledger recording only, not a bank transfer."
    )

    return {
        "ok": True,
        "status": "recorded",
        "reference": reference,
        "amount": str(decimal_amount),
        "verification_source": verification_source,
        "note": "Internal ledger entry; no external transfer was executed.",
    }


# ============================================================
# 5. TELEGRAM COMMAND HANDLERS
# ============================================================

if bot is not None:

    @bot.message_handler(commands=["start", "help"])
    def telegram_start(message):
        _send_telegram_message(
            message.chat.id,
            (
                "Welcome to Free Arbitrage Mesh.\n\n"
                "Available commands:\n"
                "/start — Show this message\n"
                "/status — Check application status\n"
                "/help — Show available commands\n\n"
                "This bot does not guarantee trading profits."
            ),
        )

    @bot.message_handler(commands=["status"])
    def telegram_status(message):
        try:
            health = _safe_database_health()
            status_text = (
                "Free Arbitrage Mesh status\n"
                f"Application: running\n"
                f"Database: {health.get('status', 'checked')}\n"
                f"Time: {time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}"
            )
        except Exception:
            logger.exception("Unable to get Telegram status.")
            status_text = (
                "Application is responding, but database status "
                "could not be confirmed."
            )

        _send_telegram_message(message.chat.id, status_text)


# ============================================================
# 6. APPLICATION LIFECYCLE
# ============================================================

_background_tasks: set[asyncio.Task] = set()


async def background_monitor() -> None:
    """
    Lightweight operational monitor.

    This intentionally does not fabricate earnings, create deposits,
    scrape arbitrary sites, or place trades.
    """
    while True:
        try:
            logger.debug("Background monitor heartbeat.")
            await asyncio.sleep(60)

        except asyncio.CancelledError:
            logger.info("Background monitor stopping.")
            raise

        except Exception:
            logger.exception("Background monitor error.")
            await asyncio.sleep(10)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting %s v%s", APP_NAME, APP_VERSION)

    # Fail startup if database initialization fails.
    try:
        database.init_db()
        logger.info("Database initialization completed.")
    except Exception:
        logger.exception("Database initialization failed.")
        raise

    monitor_task = asyncio.create_task(
        background_monitor(),
        name="background-monitor",
    )
    _background_tasks.add(monitor_task)

    # Do not silently replace an existing webhook unless explicitly
    # enabled and a real Render URL is available.
    if (
        bot is not None
        and ENABLE_TELEGRAM_WEBHOOK
        and RENDER_EXTERNAL_URL
    ):
        try:
            webhook_url = f"{RENDER_EXTERNAL_URL}/telegram/webhook"

            webhook_kwargs = {"url": webhook_url}
            if TELEGRAM_WEBHOOK_SECRET:
                webhook_kwargs["secret_token"] = TELEGRAM_WEBHOOK_SECRET

            bot.set_webhook(**webhook_kwargs)
            logger.info("Telegram webhook configured.")

        except Exception:
            # Do not crash the entire web application just because
            # Telegram webhook setup failed.
            logger.exception("Telegram webhook setup failed.")

    elif bot is not None and ENABLE_TELEGRAM_WEBHOOK:
        logger.warning(
            "Webhook setup requested but RENDER_EXTERNAL_URL is missing."
        )

    try:
        yield
    finally:
        logger.info("Application shutdown requested.")

        if bot is not None and ENABLE_TELEGRAM_WEBHOOK:
            try:
                bot.close_session()
            except Exception:
                logger.debug(
                    "Telegram session cleanup was unsuccessful.",
                    exc_info=True,
                )

        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass
        finally:
            _background_tasks.discard(monitor_task)

        logger.info("Application shutdown completed.")


app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description=(
        "Application health, Telegram integration, and "
        "verified internal income-ledger processing."
    ),
    lifespan=lifespan,
)


# ============================================================
# 7. HEALTH AND READINESS ENDPOINTS
# ============================================================

@app.get("/")
async def home():
    return HTMLResponse(
        """
        <!doctype html>
        <html lang="en">
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width,initial-scale=1">
          <title>Free Arbitrage Mesh</title>
          <style>
            body {
              font-family: system-ui, sans-serif;
              background: #101827;
              color: #f3f4f6;
              margin: 0;
              padding: 24px;
            }
            main {
              max-width: 760px;
              margin: 6vh auto;
              padding: 24px;
              border: 1px solid #334155;
              border-radius: 16px;
              background: #172235;
            }
            a { color: #93c5fd; }
            .muted { color: #cbd5e1; }
          </style>
        </head>
        <body>
          <main>
            <h1>Free Arbitrage Mesh</h1>
            <p class="muted">
              Application control panel and service health.
            </p>
            <ul>
              <li><a href="/health">Application health</a></li>
              <li><a href="/ready">Readiness check</a></li>
              <li><a href="/status">Service status</a></li>
              <li><a href="/docs">API documentation</a></li>
            </ul>
            <p class="muted">
              Displayed status is operational telemetry, not proof
              of trading profit or completed bank settlements.
            </p>
          </main>
        </body>
        </html>
        """
    )


@app.get("/health")
async def health():
    # Liveness check: answers whether the web process is responding.
    return {
        "status": "ok",
        "application": APP_NAME,
        "version": APP_VERSION,
        "timestamp": int(time.time()),
    }


@app.get("/ready")
async def ready():
    # Readiness check: includes database verification.
    try:
        health_result = _safe_database_health()

        status = str(
            health_result.get("status", "")
        ).lower()

        # Support common health-check return values from database.py.
        unhealthy = status in {
            "error",
            "failed",
            "unhealthy",
            "offline",
        }

        if unhealthy:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "not_ready",
                    "database": health_result,
                },
            )

        return {
            "status": "ready",
            "database": health_result,
        }

    except Exception:
        logger.exception("Readiness check failed.")
        return JSONResponse(
            status_code=503,
            content={
                "status": "not_ready",
                "database": "check_failed",
            },
        )


@app.get("/status")
async def service_status():
    """Operational status without exposing credentials or account secrets."""
    try:
        health_result = _safe_database_health()
    except Exception:
        logger.exception("Status health check failed.")
        health_result = {"status": "error"}

    return {
        "application": APP_NAME,
        "version": APP_VERSION,
        "web_server": "running",
        "telegram_configured": bot is not None,
        "database": health_result,
        "timestamp": int(time.time()),
    }


@app.get("/api/metrics")
async def api_metrics():
    """
    Return database metrics.

    Restrict this endpoint before exposing private financial metrics
    publicly. The implementation below intentionally returns only
    general metrics to unauthenticated callers.
    """
    return {
        "application": APP_NAME,
        "status": "running",
        "timestamp": int(time.time()),
        "note": (
            "Detailed financial metrics should be protected by "
            "authentication before public exposure."
        ),
    }


# ============================================================
# 8. TELEGRAM WEBHOOK
# ============================================================

@app.post("/telegram/webhook")
async def telegram_webhook(
    request: Request,
    x_telegram_bot_api_secret_token: str | None = Header(
        default=None,
    ),
):
    if bot is None:
        raise HTTPException(
            status_code=503,
            detail="Telegram integration is not configured.",
        )

    # If a webhook secret is configured, require a constant-time match.
    if TELEGRAM_WEBHOOK_SECRET:
        supplied = x_telegram_bot_api_secret_token or ""

        if not hmac.compare_digest(
            supplied,
            TELEGRAM_WEBHOOK_SECRET,
        ):
            raise HTTPException(
                status_code=401,
                detail="Invalid webhook secret.",
            )

    try:
        payload = await request.json()

        if not isinstance(payload, dict):
            raise HTTPException(
                status_code=400,
                detail="Invalid Telegram update payload.",
            )

        update = telegram_types.Update.de_json(payload)
        bot.process_new_updates([update])

        return {"ok": True}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Telegram webhook processing failed.")
        # Telegram can retry failed deliveries. Avoid returning internal
        # exception details to the caller.
        raise HTTPException(
            status_code=500,
            detail="Webhook processing failed.",
        )


# ============================================================
# 9. OPTIONAL INTERNAL METRICS
# ============================================================

@app.get("/api/database-metrics")
async def database_metrics():
    """
    Compatibility endpoint for the database metrics helper.

    Before exposing this publicly, add authentication because the
    returned information may contain financial ledger details.
    """
    try:
        return _safe_metrics()
    except Exception:
        logger.exception("Database metrics retrieval failed.")
        raise HTTPException(
            status_code=503,
            detail="Database metrics are temporarily unavailable.",
        )


# ============================================================
# 10. LOCAL DEVELOPMENT ENTRY POINT
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "main_supervisor:app",
        host=HOST,
        port=PORT,
        reload=False,
        log_level=os.getenv("UVICORN_LOG_LEVEL", "info").lower(),
    )
