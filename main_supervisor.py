
import asyncio
import html
import json
import logging
import os
from contextlib import asynccontextmanager
from typing import Any

import telebot
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from telebot.types import Update

import database


# =========================================================
# CONFIGURATION — set secrets in Render Environment Variables
# =========================================================

APP_HOST = "0.0.0.0"
APP_PORT = int(os.getenv("PORT", "10000"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()
TELEGRAM_WEBHOOK_SECRET = os.getenv(
    "TELEGRAM_WEBHOOK_SECRET", ""
).strip()

RENDER_EXTERNAL_URL = os.getenv("RENDER_EXTERNAL_URL", "").strip().rstrip("/")
WEBHOOK_PATH = "/tg-backend-intake"

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("free-arbitrage-mesh")

# Never substitute a fake token or a real-looking hard-coded secret.
bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN, threaded=False) if TELEGRAM_BOT_TOKEN else None

DATABASE_READY = False
WEBHOOK_CONFIGURED = False
STARTED_AT = None


# =========================================================
# TELEGRAM HANDLERS
# Merge your existing command/callback handlers below.
# =========================================================

if bot:

    @bot.message_handler(commands=["start"])
    def handle_start(message):
        bot.reply_to(
            message,
            "Welcome. The service is connected.\n"
            "Use /help to see available commands."
        )

    @bot.message_handler(commands=["help"])
    def handle_help(message):
        bot.reply_to(
            message,
            "Available commands:\n"
            "/start - Start the bot\n"
            "/help - Show this help message\n\n"
            "Market scans and financial results must be "
            "based on verified data."
        )


# =========================================================
# DATABASE / BACKGROUND LIFECYCLE
# =========================================================

async def configure_telegram_webhook() -> None:
    global WEBHOOK_CONFIGURED

    if not bot:
        logger.warning("Telegram disabled: TELEGRAM_BOT_TOKEN is missing.")
        return

    if not RENDER_EXTERNAL_URL.startswith("https://"):
        logger.warning(
            "Telegram webhook not configured: set the correct "
            "HTTPS RENDER_EXTERNAL_URL."
        )
        return

    webhook_url = f"{RENDER_EXTERNAL_URL}{WEBHOOK_PATH}"

    try:
        kwargs = {
            "url": webhook_url,
            "allowed_updates": ["message", "callback_query"],
        }

        if TELEGRAM_WEBHOOK_SECRET:
            kwargs["secret_token"] = TELEGRAM_WEBHOOK_SECRET

        await asyncio.to_thread(bot.set_webhook, **kwargs)
        WEBHOOK_CONFIGURED = True
        logger.info("Telegram webhook configured.")

    except Exception:
        logger.exception("Telegram webhook configuration failed.")
        WEBHOOK_CONFIGURED = False


@asynccontextmanager
async def lifespan(app: FastAPI):
    global DATABASE_READY, STARTED_AT

    import time
    STARTED_AT = time.time()

    # Fail visibly if database initialization fails.
    await asyncio.to_thread(database.init_db)
    DATABASE_READY = True
    logger.info("Database initialized.")

    await configure_telegram_webhook()

    # The scraper and task hunter are separate Supervisor programs.
    # Do not create duplicate scanner loops in this web process.
    try:
        yield
    finally:
        logger.info("FastAPI application shutting down.")


app = FastAPI(
    title="Free Arbitrage Mesh",
    version="2.0.0",
    lifespan=lifespan,
)


# =========================================================
# HEALTH / READINESS
# /health checks the web service.
# /ready reports whether key startup dependencies are ready.
# =========================================================

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "service": "free-arbitrage-mesh",
    }


@app.get("/ready")
async def readiness():
    ready = DATABASE_READY

    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "ready": ready,
            "database_ready": DATABASE_READY,
            "telegram_configured": bot is not None,
            "telegram_webhook_configured": WEBHOOK_CONFIGURED,
        },
    )


# =========================================================
# TELEGRAM WEBHOOK
# =========================================================

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    if not bot:
        raise HTTPException(
            status_code=503,
            detail="Telegram integration is not configured.",
        )

    if TELEGRAM_WEBHOOK_SECRET:
        supplied_secret = request.headers.get(
            "X-Telegram-Bot-Api-Secret-Token", ""
        )

        # Use constant-time comparison for the webhook secret.
        import hmac

        if not hmac.compare_digest(
            supplied_secret, TELEGRAM_WEBHOOK_SECRET
        ):
            raise HTTPException(status_code=401, detail="Invalid webhook secret.")

    try:
        payload = await request.json()

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Invalid update format.")

        update = Update.de_json(payload)

        if update is None:
            raise HTTPException(status_code=400, detail="Invalid Telegram update.")

        await asyncio.to_thread(bot.process_new_updates, [update])

        return {"ok": True}

    except HTTPException:
        raise
    except Exception:
        logger.exception("Telegram webhook processing failed.")
        raise HTTPException(status_code=500, detail="Webhook processing failed.")


# =========================================================
# DASHBOARD
# =========================================================

@app.get("/", response_class=HTMLResponse)
async def operations_web_dashboard():
    metrics: Any = {}

    if DATABASE_READY:
        try:
            metrics = await asyncio.to_thread(
                database.get_comprehensive_performance_metrics
            )
        except Exception:
            logger.exception("Could not load dashboard metrics.")
            metrics = {"error": "Metrics temporarily unavailable"}

    if not isinstance(metrics, (dict, list, str, int, float, type(None))):
        metrics = str(metrics)

    metrics_json = html.escape(
        json.dumps(metrics, indent=2, default=str)
    )

    database_status = "READY" if DATABASE_READY else "NOT READY"
    telegram_status = "CONFIGURED" if bot else "NOT CONFIGURED"
    webhook_status = "CONFIGURED" if WEBHOOK_CONFIGURED else "NOT CONFIGURED"

    return f"""
    <!doctype html>
    <html lang="en">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width,initial-scale=1">
      <title>Free Arbitrage Mesh</title>
      <style>
        body {{
          margin: 0; padding: 24px; background: #101827;
          color: #edf2f7; font: 16px/1.5 Arial, sans-serif;
        }}
        main {{ max-width: 850px; margin: auto; }}
        section {{
          background: #1b2738; border: 1px solid #344256;
          border-radius: 12px; padding: 18px; margin: 14px 0;
        }}
        h1 {{ font-size: 25px; }}
        pre {{ white-space: pre-wrap; overflow-wrap: anywhere; }}
        .muted {{ color: #bac6d6; }}
      </style>
    </head>
    <body>
      <main>
        <h1>Free Arbitrage Mesh</h1>
        <p class="muted">
          Operational status dashboard. Status indicators do not
          represent verified trading profits or guaranteed returns.
        </p>
        <section>
          <h2>Service status</h2>
          <p>Web application: RUNNING</p>
          <p>Database: {html.escape(database_status)}</p>
          <p>Telegram: {html.escape(telegram_status)}</p>
          <p>Telegram webhook: {html.escape(webhook_status)}</p>
        </section>
        <section>
          <h2>Database performance metrics</h2>
          <pre>{metrics_json}</pre>
        </section>
        <section>
          <p>Health check: <a href="/health">/health</a></p>
          <p>Readiness check: <a href="/ready">/ready</a></p>
        </section>
      </main>
    </body>
    </html>
    """


if __name__ == "__main__":
    uvicorn.run(
        app,
        host=APP_HOST,
        port=APP_PORT,
        log_level=LOG_LEVEL.lower(),
        access_log=True,
    )
