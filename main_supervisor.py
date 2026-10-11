
"""
Free Arbitrage Mesh — Task Hunter
Version: 2.0.0

Features:
- Configurable HTTPS task-feed integration
- SQLite task discovery and deduplication
- Optional Telegram notifications
- Optional trusted, verified-payment ledger recording
- Retry-friendly polling and structured logging

Task discovery is NOT proof of earnings.
Only a separate trusted payment-verification process may record income.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from typing import Any
from urllib.parse import urlparse

import requests


# ============================================================
# 1. CONFIGURATION
# ============================================================

APP_NAME = "Free Arbitrage Mesh Task Hunter"

TASK_FEED_URL = os.getenv("TASK_FEED_URL", "").strip()
TASK_FEED_TOKEN = os.getenv("TASK_FEED_TOKEN", "").strip()

TASK_SCAN_INTERVAL_SECONDS = max(
    60,
    int(os.getenv("TASK_SCAN_INTERVAL_SECONDS", "900")),
)

TASK_FEED_TIMEOUT_SECONDS = max(
    5,
    int(os.getenv("TASK_FEED_TIMEOUT_SECONDS", "20")),
)

TASK_HUNTER_DB_PATH = os.getenv(
    "TASK_HUNTER_DB_PATH",
    "task_hunter_state.sqlite3",
).strip()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv(
    "TELEGRAM_ADMIN_CHAT_ID", ""
).strip()

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("task_hunter")

session = requests.Session()
session.headers.update({
    "User-Agent": "FreeArbitrageMesh-TaskHunter/2.0",
    "Accept": "application/json",
})


# ============================================================
# 2. VALIDATION HELPERS
# ============================================================

def is_https_url(value: str) -> bool:
    """Accept HTTPS URLs with a hostname."""
    try:
        parsed = urlparse(value)
        return (
            parsed.scheme.lower() == "https"
            and bool(parsed.hostname)
            and not parsed.username
            and not parsed.password
        )
    except (TypeError, ValueError):
        return False


def clean_text(value: Any, max_length: int = 1000) -> str:
    if value is None:
        return ""
    return str(value).strip()[:max_length]


def validate_task(task: Any) -> dict[str, str] | None:
    """
    Expected feed task:
    {
        "id": "unique-task-id",
        "title": "Task title",
        "url": "https://example.com/task/123",
        "source": "Example platform"
    }

    Optional fields such as description and deadline may be included.
    No payout is treated as earned income.
    """
    if not isinstance(task, dict):
        return None

    task_id = clean_text(task.get("id"), 200)
    title = clean_text(task.get("title"), 300)
    url = clean_text(task.get("url"), 2000)
    source = clean_text(task.get("source"), 200)
    description = clean_text(task.get("description"), 2000)
    deadline = clean_text(task.get("deadline"), 100)

    if not task_id or not title or not url:
        return None

    if not is_https_url(url):
        logger.warning(
            "Ignoring task with invalid or non-HTTPS URL: %s",
            task_id,
        )
        return None

    return {
        "task_id": task_id,
        "title": title,
        "url": url,
        "source": source or "Unspecified source",
        "description": description,
        "deadline": deadline,
    }


# ============================================================
# 3. SQLITE STATE DATABASE
# ============================================================

def connect_state_db() -> sqlite3.Connection:
    conn = sqlite3.connect(
        TASK_HUNTER_DB_PATH,
        timeout=30,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    return conn


def init_state_db() -> None:
    """Create task state tables and indexes."""
    with connect_state_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS discovered_tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                url TEXT NOT NULL,
                source TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                deadline TEXT NOT NULL DEFAULT '',
                first_seen_at INTEGER NOT NULL,
                last_seen_at INTEGER NOT NULL,
                notification_status TEXT NOT NULL DEFAULT 'PENDING'
            )
        """)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_tasks_first_seen
            ON discovered_tasks(first_seen_at DESC)
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS task_hunter_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                task_id TEXT,
                message TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)

        conn.commit()

    logger.info("Task Hunter state database initialized.")


def log_event(
    event_type: str,
    message: str,
    task_id: str | None = None,
) -> None:
    try:
        with connect_state_db() as conn:
            conn.execute(
                """
                INSERT INTO task_hunter_events
                    (event_type, task_id, message, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event_type,
                    task_id,
                    clean_text(message, 2000),
                    int(time.time()),
                ),
            )
            conn.commit()
    except sqlite3.Error:
        logger.exception("Unable to write task event.")


def save_discovered_task(task: dict[str, str]) -> bool:
    """
    Save or refresh a task.

    Returns True only for a newly discovered task.
    Existing task IDs are not reported as new tasks.
    """
    now = int(time.time())

    with connect_state_db() as conn:
        conn.execute("BEGIN IMMEDIATE")

        existing = conn.execute(
            "SELECT task_id FROM discovered_tasks WHERE task_id = ?",
            (task["task_id"],),
        ).fetchone()

        if existing:
            conn.execute(
                """
                UPDATE discovered_tasks
                SET title = ?,
                    url = ?,
                    source = ?,
                    description = ?,
                    deadline = ?,
                    last_seen_at = ?
                WHERE task_id = ?
                """,
                (
                    task["title"],
                    task["url"],
                    task["source"],
                    task["description"],
                    task["deadline"],
                    now,
                    task["task_id"],
                ),
            )
            conn.commit()
            return False

        conn.execute(
            """
            INSERT INTO discovered_tasks (
                task_id, title, url, source, description,
                deadline, first_seen_at, last_seen_at,
                notification_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING')
            """,
            (
                task["task_id"],
                task["title"],
                task["url"],
                task["source"],
                task["description"],
                task["deadline"],
                now,
                now,
            ),
        )

        conn.commit()
        return True


def set_notification_status(
    task_id: str,
    status: str,
) -> None:
    with connect_state_db() as conn:
        conn.execute(
            """
            UPDATE discovered_tasks
            SET notification_status = ?
            WHERE task_id = ?
            """,
            (status, task_id),
        )
        conn.commit()


# ============================================================
# 4. TELEGRAM NOTIFICATIONS
# ============================================================

def notify_admin(message: str) -> bool:
    """Send a Telegram message without exposing credentials in logs."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        logger.info(
            "Telegram notification skipped; credentials are not configured."
        )
        return False

    endpoint = (
        f"https://api.telegram.org/bot"
        f"{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = session.post(
            endpoint,
            json={
                "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                "text": message[:4000],
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        response.raise_for_status()

        result = response.json()
        if not result.get("ok"):
            logger.warning("Telegram API did not confirm message delivery.")
            return False

        return True

    except requests.RequestException:
        logger.exception("Telegram notification request failed.")
        return False
    except ValueError:
        logger.warning("Telegram returned an invalid JSON response.")
        return False


def notify_new_task(task: dict[str, str]) -> bool:
    message = (
        "New task discovered\n\n"
        f"Title: {task['title']}\n"
        f"Source: {task['source']}\n"
        f"Task ID: {task['task_id']}\n"
        f"Link: {task['url']}\n"
    )

    if task["deadline"]:
        message += f"Deadline: {task['deadline']}\n"

    if task["description"]:
        message += f"\nDetails: {task['description'][:1000]}\n"

    message += (
        "\nStatus: Discovered, not completed or paid. "
        "Check the task provider's terms before accepting."
    )

    return notify_admin(message)


# ============================================================
# 5. FETCH TASK FEED
# ============================================================

def fetch_tasks() -> list[dict[str, str]]:
    """
    Fetch tasks from the configured HTTPS JSON endpoint.

    Expected response:
    {
        "tasks": [
            {
                "id": "task-001",
                "title": "Example task",
                "url": "https://provider.example/tasks/001",
                "source": "Provider"
            }
        ]
    }

    Authentication uses Bearer token if TASK_FEED_TOKEN is set.
    """
    if not TASK_FEED_URL:
        logger.warning(
            "TASK_FEED_URL is not configured; task discovery is disabled."
        )
        return []

    if not is_https_url(TASK_FEED_URL):
        logger.error(
            "TASK_FEED_URL must be a valid HTTPS URL. "
            "Task feed request skipped."
        )
        return []

    headers = {}
    if TASK_FEED_TOKEN:
        headers["Authorization"] = f"Bearer {TASK_FEED_TOKEN}"

    try:
        response = session.get(
            TASK_FEED_URL,
            headers=headers,
            timeout=TASK_FEED_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        payload = response.json()

    except requests.RequestException:
        logger.exception("Task feed request failed.")
        log_event("FEED_ERROR", "Task feed request failed.")
        return []

    except ValueError:
        logger.error("Task feed did not return valid JSON.")
        log_event("FEED_ERROR", "Task feed returned invalid JSON.")
        return []

    if isinstance(payload, list):
        raw_tasks = payload
    elif isinstance(payload, dict):
        raw_tasks = payload.get("tasks", [])
    else:
        raw_tasks = []

    if not isinstance(raw_tasks, list):
        logger.warning("Task feed 'tasks' field is not a list.")
        return []

    valid_tasks: list[dict[str, str]] = []

    for raw_task in raw_tasks:
        task = validate_task(raw_task)
        if task:
            valid_tasks.append(task)

    logger.info("Task feed returned %d valid tasks.", len(valid_tasks))
    return valid_tasks


# ============================================================
# 6. DISCOVERY CYCLE
# ============================================================

def run_discovery_cycle() -> int:
    """Fetch tasks, deduplicate them, and notify about new discoveries."""
    tasks = fetch_tasks()
    new_count = 0

    for task in tasks:
        try:
            is_new = save_discovered_task(task)

            if not is_new:
                continue

            new_count += 1
            log_event(
                "TASK_DISCOVERED",
                f"Discovered task: {task['title']}",
                task["task_id"],
            )

            delivered = notify_new_task(task)

            set_notification_status(
                task["task_id"],
                "SENT" if delivered else "NOT_SENT",
            )

            logger.info(
                "New task recorded: id=%s notification_sent=%s",
                task["task_id"],
                delivered,
            )

        except Exception:
            logger.exception(
                "Error processing discovered task %s",
                task.get("task_id", "unknown"),
            )

    logger.info(
        "Discovery cycle complete. New tasks: %d",
        new_count,
    )

    return new_count


# ============================================================
# 7. VERIFIED PAYMENT RECORDING
# ============================================================

def record_verified_task_payment(
    *,
    task_id: str,
    payment_reference: str,
    telegram_id: int,
    amount: Decimal | str | int | float,
    verification_source: str,
) -> dict[str, Any]:
    """
    Record income only when a trusted upstream payment verifier
    has already confirmed the actual receipt of funds.

    This function is intentionally NOT called by task discovery.

    Only call from a trusted server-side integration after checking
    the provider's authenticated payment status and amount.

    Never trust a task-feed field such as "paid": true as proof.
    """
    allowed_sources = {
        "paystack_verified_webhook",
        "verified_task_payment",
        "verified_manual_receipt",
    }

    if verification_source not in allowed_sources:
        raise ValueError("Unrecognized payment verification source.")

    if not task_id or not payment_reference:
        raise ValueError("Task ID and payment reference are required.")

    try:
        decimal_amount = Decimal(str(amount))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise ValueError("Invalid payment amount.") from exc

    if not decimal_amount.is_finite() or decimal_amount <= 0:
        raise ValueError("Payment amount must be positive and finite.")

    # Import the shared database module, not main_supervisor.py.
    # This avoids importing the web application into the worker.
    import database

    recorded = database.record_deposit(
        reference=payment_reference.strip(),
        telegram_id=int(telegram_id),
        amount=float(decimal_amount),
    )

    if not recorded:
        return {
            "ok": True,
            "status": "duplicate_ignored",
            "payment_reference": payment_reference,
        }

    log_event(
        "VERIFIED_PAYMENT_RECORDED",
        (
            f"Verified income recorded for task {task_id}; "
            f"reference={payment_reference}; "
            f"source={verification_source}"
        ),
        task_id,
    )

    notify_admin(
        "Verified task payment recorded in the internal ledger.\n"
        f"Task ID: {task_id}\n"
        f"Reference: {payment_reference}\n"
        f"Amount: {decimal_amount}\n"
        f"Source: {verification_source}\n"
        "This is a ledger entry, not a bank transfer."
    )

    return {
        "ok": True,
        "status": "recorded",
        "task_id": task_id,
        "payment_reference": payment_reference,
        "amount": str(decimal_amount),
        "note": "Recorded in internal ledger only.",
    }


# ============================================================
# 8. TASK-HUNTER STATUS
# ============================================================

def get_task_hunter_status() -> dict[str, Any]:
    with connect_state_db() as conn:
        task_count = conn.execute(
            "SELECT COUNT(*) AS count FROM discovered_tasks"
        ).fetchone()["count"]

        recent_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM discovered_tasks
            WHERE first_seen_at >= ?
            """,
            (int(time.time()) - 86400,),
        ).fetchone()["count"]

    return {
        "service": APP_NAME,
        "status": "running",
        "feed_configured": bool(TASK_FEED_URL),
        "telegram_configured": bool(
            TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID
        ),
        "total_discovered_tasks": task_count,
        "discovered_last_24_hours": recent_count,
        "scan_interval_seconds": TASK_SCAN_INTERVAL_SECONDS,
        "timestamp": int(time.time()),
    }


# ============================================================
# 9. WORKER LOOP
# ============================================================

def main() -> None:
    logger.info("Starting %s.", APP_NAME)

    init_state_db()

    while True:
        started_at = time.monotonic()

        try:
            run_discovery_cycle()
        except KeyboardInterrupt:
            logger.info("Shutdown requested.")
            break
        except Exception:
            logger.exception("Unexpected discovery-cycle failure.")
            log_event(
                "WORKER_ERROR",
                "Unexpected discovery-cycle failure.",
            )

        elapsed = time.monotonic() - started_at
        sleep_seconds = max(
            1,
            TASK_SCAN_INTERVAL_SECONDS - int(elapsed),
        )

        logger.info(
            "Next task scan in %d seconds.",
            sleep_seconds,
        )

        try:
            time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            logger.info("Shutdown requested.")
            break

    session.close()
    logger.info("Task Hunter stopped.")


if __name__ == "__main__":
    main()
