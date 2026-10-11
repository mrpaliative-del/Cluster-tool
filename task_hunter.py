
"""
Free Arbitrage Mesh — Task Hunter
Version: 2.1.0

Purpose:
- Discover tasks from one authorized HTTPS JSON feed.
- Validate task records and HTTPS URLs.
- Store discovered tasks in SQLite.
- Send Telegram alerts for new tasks.
- Retry failed notifications after a cooldown.
- Log discovery and notification events.

Important:
Task discovery is not income. This module does not verify payments,
record receipts, execute trades, or guarantee opportunities.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

TASK_FEED_URL = os.getenv("TASK_FEED_URL", "").strip()
TASK_FEED_TOKEN = os.getenv("TASK_FEED_TOKEN", "").strip()

SCAN_INTERVAL_SECONDS = max(
    60, int(os.getenv("TASK_SCAN_INTERVAL_SECONDS", "900"))
)
REQUEST_TIMEOUT_SECONDS = max(
    5, int(os.getenv("TASK_FEED_TIMEOUT_SECONDS", "20"))
)

DB_PATH = Path(
    os.getenv("TASK_HUNTER_DB_PATH", "task_hunter_state.sqlite3")
)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()

NOTIFICATION_RETRY_SECONDS = max(
    300, int(os.getenv("TASK_NOTIFICATION_RETRY_SECONDS", "900"))
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("task_hunter")


# ---------------------------------------------------------
# Time and validation helpers
# ---------------------------------------------------------

def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def valid_https_url(value: str) -> bool:
    """Accept HTTPS URLs with a hostname and no embedded credentials."""
    if not isinstance(value, str) or len(value) > 4096:
        return False

    try:
        parsed = urlparse(value.strip())
        return (
            parsed.scheme.lower() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


def clean_text(value, limit: int = 2000) -> str:
    if value is None:
        return ""
    return " ".join(str(value).split())[:limit]


def validate_task(item) -> dict | None:
    if not isinstance(item, dict):
        return None

    task_id = clean_text(item.get("id") or item.get("task_id"), 200)
    title = clean_text(item.get("title") or item.get("name"), 300)
    url = clean_text(item.get("url") or item.get("link"), 4096)
    source = clean_text(item.get("source") or "configured_feed", 150)
    description = clean_text(item.get("description"), 2000)
    deadline = clean_text(item.get("deadline"), 100)

    if not task_id or not title or not valid_https_url(url):
        return None

    return {
        "task_id": task_id,
        "title": title,
        "url": url,
        "source": source,
        "description": description,
        "deadline": deadline,
    }


# ---------------------------------------------------------
# SQLite storage
# ---------------------------------------------------------

def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    return connection


def _ensure_column(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    definition: str,
) -> None:
    existing = {
        row["name"]
        for row in connection.execute(f"PRAGMA table_info({table})")
    }

    if column not in existing:
        # Table and column names are fixed internal constants.
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {column} {definition}"
        )


def init_db() -> None:
    with get_connection() as connection:
        connection.execute("""
            CREATE TABLE IF NOT EXISTS discovered_tasks (
                task_id TEXT PRIMARY KEY,
                title TEXT NOT NULL DEFAULT '',
                url TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                description TEXT NOT NULL DEFAULT '',
                deadline TEXT NOT NULL DEFAULT '',
                first_seen_at TEXT NOT NULL DEFAULT '',
                last_seen_at TEXT NOT NULL DEFAULT '',
                notification_status TEXT NOT NULL DEFAULT 'PENDING',
                last_notification_attempt_at TEXT NOT NULL DEFAULT ''
            )
        """)

        connection.execute("""
            CREATE TABLE IF NOT EXISTS task_hunter_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                task_id TEXT,
                details TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            )
        """)

        # Upgrade databases created by earlier versions.
        columns = {
            "title": "TEXT NOT NULL DEFAULT ''",
            "url": "TEXT NOT NULL DEFAULT ''",
            "source": "TEXT NOT NULL DEFAULT ''",
            "description": "TEXT NOT NULL DEFAULT ''",
            "deadline": "TEXT NOT NULL DEFAULT ''",
            "first_seen_at": "TEXT NOT NULL DEFAULT ''",
            "last_seen_at": "TEXT NOT NULL DEFAULT ''",
            "notification_status": "TEXT NOT NULL DEFAULT 'PENDING'",
            "last_notification_attempt_at": "TEXT NOT NULL DEFAULT ''",
        }

        for column, definition in columns.items():
            _ensure_column(
                connection, "discovered_tasks", column, definition
            )

        connection.execute("""
            CREATE INDEX IF NOT EXISTS idx_task_notification_status
            ON discovered_tasks(notification_status)
        """)

        connection.commit()

    logger.info("Task Hunter database initialized at %s", DB_PATH)


def record_event(
    event_type: str,
    task_id: str | None = None,
    details: str = "",
) -> None:
    try:
        with get_connection() as connection:
            connection.execute(
                """
                INSERT INTO task_hunter_events
                    (event_type, task_id, details, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    event_type[:100],
                    task_id,
                    details[:2000],
                    utc_now(),
                ),
            )
            connection.commit()
    except sqlite3.Error:
        logger.exception("Could not save Task Hunter event")


def save_task(task: dict) -> bool:
    """Save or update a task. Return True only for a newly discovered ID."""
    now = utc_now()

    with get_connection() as connection:
        existing = connection.execute(
            "SELECT task_id FROM discovered_tasks WHERE task_id = ?",
            (task["task_id"],),
        ).fetchone()

        if existing:
            connection.execute(
                """
                UPDATE discovered_tasks
                SET title = ?, url = ?, source = ?, description = ?,
                    deadline = ?, last_seen_at = ?
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
            connection.commit()
            return False

        connection.execute(
            """
            INSERT INTO discovered_tasks (
                task_id, title, url, source, description, deadline,
                first_seen_at, last_seen_at, notification_status,
                last_notification_attempt_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', '')
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
        connection.commit()

    record_event("TASK_DISCOVERED", task["task_id"], task["title"])
    return True


# ---------------------------------------------------------
# Feed integration
# ---------------------------------------------------------

def fetch_tasks() -> list[dict]:
    if not TASK_FEED_URL:
        logger.warning(
            "TASK_FEED_URL is not configured; discovery is disabled."
        )
        return []

    if not valid_https_url(TASK_FEED_URL):
        logger.error("TASK_FEED_URL must be a valid HTTPS URL.")
        return []

    headers = {"Accept": "application/json"}
    if TASK_FEED_TOKEN:
        headers["Authorization"] = f"Bearer {TASK_FEED_TOKEN}"

    try:
        response = requests.get(
            TASK_FEED_URL,
            headers=headers,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()

        # Avoid processing unexpectedly large responses.
        if len(response.content) > 5_000_000:
            raise ValueError("Feed response exceeds the 5 MB limit.")

        payload = response.json()

        if isinstance(payload, dict):
            raw_tasks = payload.get("tasks", [])
        elif isinstance(payload, list):
            raw_tasks = payload
        else:
            raise ValueError("Feed must return a JSON list or a tasks list.")

        if not isinstance(raw_tasks, list):
            raise ValueError("'tasks' must be a JSON list.")

        valid_tasks = []
        rejected = 0

        for item in raw_tasks:
            task = validate_task(item)
            if task:
                valid_tasks.append(task)
            else:
                rejected += 1

        if rejected:
            logger.warning("Rejected %d invalid feed records.", rejected)

        logger.info("Feed returned %d valid task records.", len(valid_tasks))
        return valid_tasks

    except (
        requests.RequestException,
        ValueError,
        json.JSONDecodeError,
    ):
        logger.exception("Task feed request or parsing failed.")
        record_event("FEED_ERROR", details="Request or JSON parsing failed")
        return []


# ---------------------------------------------------------
# Telegram notifications
# ---------------------------------------------------------

def telegram_is_configured() -> bool:
    return bool(TELEGRAM_BOT_TOKEN and TELEGRAM_ADMIN_CHAT_ID)


def send_telegram(message: str) -> bool:
    if not telegram_is_configured():
        logger.info("Telegram is not configured; alert not sent.")
        return False

    endpoint = (
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            endpoint,
            json={
                "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                "text": message[:4000],
                "disable_web_page_preview": True,
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        result = response.json()

        if not isinstance(result, dict) or not result.get("ok"):
            logger.warning("Telegram did not confirm message delivery.")
            return False

        return True

    except (requests.RequestException, ValueError):
        logger.exception("Telegram notification failed.")
        return False


def task_notification_text(task: dict) -> str:
    description = task.get("description") or "No description supplied."
    deadline = task.get("deadline") or "Not supplied"

    return (
        "Free Arbitrage Mesh — Task Discovery\n\n"
        f"Title: {task['title']}\n"
        f"Source: {task['source']}\n"
        f"Description: {description}\n"
        f"Deadline: {deadline}\n"
        f"Task link: {task['url']}\n\n"
        "Check the provider's terms, eligibility, requirements, and "
        "payment conditions before doing any work. Discovery is not income."
    )


def notify_pending_tasks() -> None:
    now = time.time()

    with get_connection() as connection:
        rows = connection.execute(
            """
            SELECT *
            FROM discovered_tasks
            WHERE notification_status IN ('PENDING', 'NOT_SENT')
            ORDER BY first_seen_at ASC
            LIMIT 50
            """
        ).fetchall()

    for row in rows:
        last_attempt = row["last_notification_attempt_at"] or ""

        if last_attempt:
            try:
                previous = datetime.fromisoformat(last_attempt).timestamp()
                if now - previous < NOTIFICATION_RETRY_SECONDS:
                    continue
            except ValueError:
                pass

        task = dict(row)
        attempted_at = utc_now()

        with get_connection() as connection:
            connection.execute(
                """
                UPDATE discovered_tasks
                SET last_notification_attempt_at = ?
                WHERE task_id = ?
                """,
                (attempted_at, task["task_id"]),
            )
            connection.commit()

        sent = send_telegram(task_notification_text(task))
        status = "SENT" if sent else "NOT_SENT"

        with get_connection() as connection:
            connection.execute(
                """
                UPDATE discovered_tasks
                SET notification_status = ?
                WHERE task_id = ?
                """,
                (status, task["task_id"]),
            )
            connection.commit()

        record_event(
            "NOTIFICATION_SENT" if sent else "NOTIFICATION_FAILED",
            task["task_id"],
            status,
        )


# ---------------------------------------------------------
# Discovery cycle and worker
# ---------------------------------------------------------

def run_discovery_cycle() -> dict:
    tasks = fetch_tasks()
    newly_discovered = 0

    for task in tasks:
        try:
            if save_task(task):
                newly_discovered += 1
                logger.info(
                    "New task discovered: %s | %s",
                    task["title"],
                    task["url"],
                )
        except sqlite3.Error:
            logger.exception(
                "Could not save task ID %s", task["task_id"]
            )
            record_event(
                "TASK_SAVE_ERROR",
                task["task_id"],
                "Database write failed",
            )

    notify_pending_tasks()

    summary = {
        "feed_records_valid": len(tasks),
        "new_tasks": newly_discovered,
        "checked_at": utc_now(),
    }
    logger.info("Discovery cycle complete: %s", summary)
    return summary


def main() -> None:
    init_db()
    logger.info(
        "Task Hunter started. Scan interval: %s seconds.",
        SCAN_INTERVAL_SECONDS,
    )

    while True:
        started = time.monotonic()

        try:
            run_discovery_cycle()
        except Exception:
            logger.exception("Unexpected discovery-cycle failure.")
            record_event("CYCLE_ERROR", details="Unexpected worker error")

        elapsed = time.monotonic() - started
        time.sleep(max(1, SCAN_INTERVAL_SECONDS - int(elapsed)))


if __name__ == "__main__":
    main()
