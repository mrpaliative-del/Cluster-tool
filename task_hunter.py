
import asyncio
import json
import logging
import os
import sqlite3
import time
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlparse

import requests


# =========================================================
# CONFIGURATION
# =========================================================

TASK_FEED_URL = os.getenv("TASK_FEED_URL", "").strip()
TASK_FEED_TOKEN = os.getenv("TASK_FEED_TOKEN", "").strip()

SCAN_INTERVAL_SECONDS = max(
    60, int(os.getenv("TASK_SCAN_INTERVAL_SECONDS", "900"))
)
REQUEST_TIMEOUT_SECONDS = 20

STATE_DB_PATH = os.getenv(
    "TASK_HUNTER_DB_PATH", "/tmp/task_hunter_state.sqlite3"
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("task-hunter")


# =========================================================
# LOCAL DISCOVERY STATE
# This records task IDs, not income or payment balances.
# =========================================================

def init_state_db():
    Path(STATE_DB_PATH).parent.mkdir(parents=True, exist_ok=True)

    with sqlite3.connect(STATE_DB_PATH, timeout=15) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS discovered_tasks (
                task_id TEXT PRIMARY KEY,
                source TEXT NOT NULL,
                title TEXT NOT NULL,
                url TEXT,
                first_seen_at INTEGER NOT NULL
            )
        """)
        conn.commit()


def record_new_task(task):
    """Return True only when a task ID has not been recorded before."""
    with sqlite3.connect(STATE_DB_PATH, timeout=15) as conn:
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO discovered_tasks
                (task_id, source, title, url, first_seen_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                task["id"],
                task["source"],
                task["title"],
                task.get("url"),
                int(time.time()),
            ),
        )
        conn.commit()
        return cursor.rowcount == 1


# =========================================================
# TASK FEED
#
# Configure TASK_FEED_URL to an authorized JSON endpoint.
# Expected response:
# {
#   "tasks": [
#     {
#       "id": "unique-source-task-id",
#       "title": "Task title",
#       "url": "https://example.com/task",
#       "source": "provider-name"
#     }
#   ]
# }
#
# Discovery is not proof that a bounty is payable.
# =========================================================

def fetch_task_feed():
    if not TASK_FEED_URL:
        logger.warning(
            "TASK_FEED_URL is unset. No real task source is configured."
        )
        return []

    parsed = urlparse(TASK_FEED_URL)

    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError("TASK_FEED_URL must be a valid HTTPS URL.")

    headers = {
        "Accept": "application/json",
        "User-Agent": "FreeArbitrageMesh-TaskHunter/1.0",
    }

    if TASK_FEED_TOKEN:
        headers["Authorization"] = f"Bearer {TASK_FEED_TOKEN}"

    response = requests.get(
        TASK_FEED_URL,
        headers=headers,
        timeout=REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()

    payload = response.json()

    if not isinstance(payload, dict):
        raise ValueError("Task feed response must be a JSON object.")

    tasks = payload.get("tasks", [])

    if not isinstance(tasks, list):
        raise ValueError("The 'tasks' field must be a list.")

    normalized = []

    for item in tasks:
        if not isinstance(item, dict):
            continue

        task_id = str(item.get("id", "")).strip()
        title = str(item.get("title", "")).strip()
        source = str(item.get("source", "configured-feed")).strip()
        url = str(item.get("url", "")).strip()

        if not task_id or not title:
            logger.warning("Ignoring task missing its ID or title.")
            continue

        if url:
            parsed_task_url = urlparse(url)
            if (
                parsed_task_url.scheme != "https"
                or not parsed_task_url.netloc
            ):
                logger.warning(
                    "Ignoring task with an invalid URL: %s", task_id
                )
                continue

        normalized.append({
            "id": task_id,
            "title": title[:300],
            "source": source[:100],
            "url": url or None,
        })

    return normalized


# =========================================================
# DISCOVERY CYCLE
# =========================================================

async def scan_premium_enterprise_vectors():
    logger.info("Enterprise task discovery worker starting.")
    await asyncio.to_thread(init_state_db)

    while True:
        try:
            tasks = await asyncio.to_thread(fetch_task_feed)

            new_count = 0

            for task in tasks:
                is_new = await asyncio.to_thread(record_new_task, task)

                if not is_new:
                    continue

                new_count += 1

                logger.info(
                    "New task discovered | source=%s | id=%s | title=%s",
                    task["source"],
                    task["id"],
                    task["title"],
                )

                if task.get("url"):
                    logger.info("Task details: %s", task["url"])

            logger.info(
                "Discovery cycle complete | received=%d | new=%d",
                len(tasks),
                new_count,
            )

        except asyncio.CancelledError:
            raise

        except (requests.RequestException, ValueError) as exc:
            logger.warning("Task feed request or validation failed: %s", exc)

        except Exception:
            logger.exception("Unexpected task discovery failure.")

        await asyncio.sleep(SCAN_INTERVAL_SECONDS)


if __name__ == "__main__":
    try:
        asyncio.run(scan_premium_enterprise_vectors())
    except KeyboardInterrupt:
        logger.info("Task hunter stopped.")
