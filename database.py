
"""
Free Arbitrage Mesh — Shared Database
Version: 2.3.0

Persistent SQLite ledger, compatible schema migration, idempotent receipt
recording, $50 USD allocation batches, task discovery storage, tuning,
indicative metrics, settlement metadata, and health/performance reporting.

Only a trusted server-side payment verifier should call
record_verified_receipt(). This module does not verify provider webhooks.

Allocation entries are bookkeeping only. No transfers, trades, bets, or
investments are executed by this module.
"""

from __future__ import annotations

import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterator

VERSION = "2.3.0"
DATABASE_PATH = os.getenv("MATRIX_DATABASE_PATH", "matrix_system.db").strip() or "matrix_system.db"
DB_TIMEOUT_SECONDS = 30
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ALLOCATION_BATCH_USD = Decimal("50.00")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("free-arbitrage-mesh.database")

DEFAULT_SPLITS = {
    "PERSONAL_UPKEEP": Decimal("0.20"),
    "CRYPTO_ARBITRAGE": Decimal("0.20"),
    "FOREX_RESERVE": Decimal("0.20"),
    "STOCKS_EQUITIES": Decimal("0.15"),
    "COMMODITIES_GOLD": Decimal("0.10"),
    "ALT_MARKETS": Decimal("0.10"),
    "SPORTS_BETTING": Decimal("0.05"),
}


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """Open a configured SQLite connection; write operations must commit."""
    path = Path(DATABASE_PATH)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=DB_TIMEOUT_SECONDS,
        isolation_level="DEFERRED",
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {DB_TIMEOUT_SECONDS * 1000}")
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid decimal number.") from exc
    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")
    return result


def _money(value: Any) -> Decimal:
    return _decimal(value, "Money value").quantize(
        CENT, rounding=ROUND_HALF_UP
    )


def _validate_splits(splits: dict[str, Any]) -> dict[str, Decimal]:
    if not isinstance(splits, dict) or set(splits) != set(DEFAULT_SPLITS):
        raise ValueError(
            "Exactly these seven allocation categories are required: "
            + ", ".join(DEFAULT_SPLITS)
        )

    result = {}
    for category, value in splits.items():
        share = _decimal(value, f"Allocation {category}")
        if not Decimal("0") <= share <= Decimal("1"):
            raise ValueError(f"Allocation {category} must be between 0 and 1.")
        result[category] = share

    if sum(result.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("Allocation percentages must total exactly 100%.")
    return result


def _table_exists(conn: sqlite3.Connection, table: str) -> bool:
    return conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (table,),
    ).fetchone() is not None


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(conn, table):
        return set()
    return {
        str(row["name"])
        for row in conn.execute(f'PRAGMA table_info("{table}")').fetchall()
    }


def _add_column(
    conn: sqlite3.Connection,
    table: str,
    column: str,
    declaration: str,
) -> None:
    if column not in _columns(conn, table):
        conn.execute(
            f'ALTER TABLE "{table}" ADD COLUMN "{column}" {declaration}'
        )


def _metadata_get(
    conn: sqlite3.Connection,
    key: str,
    default: str = "",
) -> str:
    row = conn.execute(
        "SELECT value FROM system_metadata WHERE key=?",
        (key,),
    ).fetchone()
    return str(row["value"]) if row else default


def _metadata_set(
    conn: sqlite3.Connection,
    key: str,
    value: Any,
) -> None:
    conn.execute(
        """
        INSERT INTO system_metadata(key, value) VALUES(?, ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value
        """,
        (key, str(value)),
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (ValueError, TypeError, OverflowError):
        return default


def init_db() -> None:
    """Create tables and add compatible columns without deleting old records."""
    with get_connection() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS system_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS deposits (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reference TEXT NOT NULL UNIQUE,
                telegram_id INTEGER NOT NULL DEFAULT 0,
                amount TEXT NOT NULL,
                currency TEXT NOT NULL DEFAULT 'USD',
                net_amount TEXT NOT NULL,
                fx_to_usd TEXT NOT NULL DEFAULT '1',
                net_usd TEXT NOT NULL,
                verification_provider TEXT NOT NULL DEFAULT 'legacy-migrated',
                verification_id TEXT NOT NULL DEFAULT 'legacy-migrated',
                recorded_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS allocation_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_reference TEXT NOT NULL UNIQUE,
                amount_usd TEXT,
                batch_amount_usd TEXT,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                percentage TEXT NOT NULL,
                amount_usd TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'LEDGER_ONLY',
                created_at INTEGER NOT NULL,
                FOREIGN KEY(batch_id) REFERENCES allocation_batches(id),
                UNIQUE(batch_id, category)
            );

            CREATE TABLE IF NOT EXISTS indicative_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                metric_value TEXT NOT NULL,
                recorded_at INTEGER,
                updated_at INTEGER
            );

            CREATE TABLE IF NOT EXISTS ledger_yield_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                value TEXT,
                indicative_difference_pct TEXT,
                recorded_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_hunter_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                task_id TEXT,
                details TEXT,
                message TEXT,
                created_at INTEGER NOT NULL
            );

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
            );

            CREATE TABLE IF NOT EXISTS tuning_matrix (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settlement_account (
                id INTEGER PRIMARY KEY CHECK(id=1),
                provider TEXT,
                account_reference TEXT,
                currency TEXT,
                updated_at INTEGER
            );
        """)

        migrations = (
            ("deposits", "fx_source", "TEXT NOT NULL DEFAULT ''"),
            ("deposits", "fx_recorded_at", "INTEGER"),
            ("allocation_batches", "amount_usd", "TEXT"),
            ("allocation_batches", "batch_amount_usd", "TEXT"),
            ("allocations", "status", "TEXT NOT NULL DEFAULT 'LEDGER_ONLY'"),
            ("indicative_metrics", "recorded_at", "INTEGER"),
            ("indicative_metrics", "updated_at", "INTEGER"),
            ("ledger_yield_history", "value", "TEXT"),
            ("ledger_yield_history", "indicative_difference_pct", "TEXT"),
            ("task_hunter_events", "details", "TEXT"),
            ("task_hunter_events", "message", "TEXT"),
        )
        for table, column, declaration in migrations:
            _add_column(conn, table, column, declaration)

        conn.execute("""
            UPDATE allocation_batches
            SET amount_usd=COALESCE(NULLIF(amount_usd,''),batch_amount_usd),
                batch_amount_usd=COALESCE(NULLIF(batch_amount_usd,''),amount_usd)
        """)
        conn.execute("""
            UPDATE indicative_metrics
            SET recorded_at=COALESCE(recorded_at,updated_at,0),
                updated_at=COALESCE(updated_at,recorded_at,0)
        """)
        conn.execute("""
            UPDATE ledger_yield_history
            SET value=COALESCE(NULLIF(value,''),indicative_difference_pct,'0'),
                indicative_difference_pct=
                    COALESCE(NULLIF(indicative_difference_pct,''),value,'0')
        """)
        conn.execute("""
            UPDATE task_hunter_events
            SET details=COALESCE(NULLIF(details,''),message,''),
                message=COALESCE(NULLIF(message,''),details,'')
        """)

        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_deposits_recorded_at ON deposits(recorded_at)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_allocations_category ON allocations(category)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_discovered_tasks_first_seen "
            "ON discovered_tasks(first_seen_at DESC)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_indicative_metrics_name_time "
            "ON indicative_metrics(metric_name, recorded_at)"
        )

        # Migrate allocation settings without resetting custom values.
        now = int(time.time())
        for category, default in DEFAULT_SPLITS.items():
            old_key = f"allocation_{category}"
            new_key = f"allocation.{category}"
            old_value = _metadata_get(conn, old_key, "")
            tuning_row = conn.execute(
                "SELECT value FROM tuning_matrix WHERE key=?",
                (new_key,),
            ).fetchone()
            chosen = (
                str(tuning_row["value"])
                if tuning_row and str(tuning_row["value"]).strip()
                else old_value or str(default)
            )
            _metadata_set(conn, old_key, chosen)
            conn.execute("""
                INSERT INTO tuning_matrix(key,value,updated_at) VALUES(?,?,?)
                ON CONFLICT(key) DO UPDATE SET
                    value=excluded.value, updated_at=excluded.updated_at
            """, (new_key, chosen, now))

        carry = _metadata_get(
            conn,
            "allocation_carry_usd",
            _metadata_get(conn, "allocation_carry_forward_usd", "0.00"),
        )
        _metadata_set(conn, "allocation_carry_usd", carry)
        _metadata_set(conn, "allocation_carry_forward_usd", carry)
        _metadata_set(conn, "allocation_batch_usd", ALLOCATION_BATCH_USD)
        yield_value = _metadata_get(
            conn,
            "indicative_yield_pct",
            _metadata_get(conn, "indicative_yield", "0.00"),
        )
        _metadata_set(conn, "indicative_yield_pct", yield_value)
        _metadata_set(conn, "indicative_yield", yield_value)
        _metadata_set(conn, "database_schema_version", VERSION)
        conn.commit()

    logger.info("Shared database initialized/migrated to schema %s.", VERSION)


def _get_splits(conn: sqlite3.Connection) -> dict[str, Decimal]:
    splits = {
        category: _decimal(
            _metadata_get(conn, f"allocation_{category}", str(default)),
            f"Stored allocation {category}",
        )
        for category, default in DEFAULT_SPLITS.items()
    }
    return _validate_splits(splits)


def get_allocation_splits() -> dict[str, str]:
    with get_connection() as conn:
        splits = _get_splits(conn)
    return {key: str(value) for key, value in splits.items()}


def get_tuning_matrix() -> dict[str, Any]:
    result: dict[str, Any] = {}
    with get_connection() as conn:
        for row in conn.execute("SELECT key,value FROM tuning_matrix ORDER BY key"):
            key, raw = str(row["key"]), str(row["value"])
            try:
                result[key] = float(raw)
            except (TypeError, ValueError):
                result[key] = raw
        for category, share in _get_splits(conn).items():
            result.setdefault(f"allocation.{category}", float(share))
    return result


def update_tuning_matrix(key: Any, value: Any = None) -> dict[str, Any]:
    """Support both whole-split dictionary updates and key/value updates."""
    now = int(time.time())

    if isinstance(key, dict):
        normalized = _validate_splits(key)
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            for category, share in normalized.items():
                _metadata_set(conn, f"allocation_{category}", share)
                conn.execute("""
                    INSERT INTO tuning_matrix(key,value,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value, updated_at=excluded.updated_at
                """, (f"allocation.{category}", str(share), now))
            conn.commit()
        return {category: str(share) for category, share in normalized.items()}

    setting_key = str(key).strip()
    if not setting_key or len(setting_key) > 200:
        raise ValueError("Tuning key must contain 1 to 200 characters.")
    if value is None:
        raise ValueError("A value is required when updating a tuning key.")

    if setting_key.startswith("allocation."):
        category = setting_key[len("allocation."):].strip()
        if category not in DEFAULT_SPLITS:
            raise ValueError(f"Unsupported allocation category: {category}")
        proposed = _decimal(value, f"Tuning value {setting_key}")
        if not Decimal("0") <= proposed <= Decimal("1"):
            raise ValueError("Allocation share must be between 0 and 1.")
        with get_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            current = _get_splits(conn)
            current[category] = proposed
            normalized = _validate_splits(current)
            for name, share in normalized.items():
                _metadata_set(conn, f"allocation_{name}", share)
                conn.execute("""
                    INSERT INTO tuning_matrix(key,value,updated_at) VALUES(?,?,?)
                    ON CONFLICT(key) DO UPDATE SET
                        value=excluded.value, updated_at=excluded.updated_at
                """, (f"allocation.{name}", str(share), now))
            conn.commit()
        return {"key": setting_key, "value": float(proposed)}

    parsed = _decimal(value, f"Tuning value {setting_key}")
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            INSERT INTO tuning_matrix(key,value,updated_at) VALUES(?,?,?)
            ON CONFLICT(key) DO UPDATE SET
                value=excluded.value, updated_at=excluded.updated_at
        """, (setting_key, str(parsed), now))
        conn.commit()
    return {"key": setting_key, "value": float(parsed)}


def record_verified_receipt(
    *,
    reference: str,
    amount: Any,
    currency: str,
    net_amount: Any,
    fx_to_usd: Any,
    verification_provider: str,
    verification_id: str,
    telegram_id: int = 0,
    fx_source: str = "",
    fx_recorded_at: int | None = None,
) -> dict[str, Any]:
    """
    Record a receipt after trusted server-side verification.
    fx_to_usd means USD per one unit of receipt currency.
    """
    reference = str(reference).strip()
    currency = str(currency).strip().upper()
    provider = str(verification_provider).strip()
    verification_id = str(verification_id).strip()

    if not reference or not provider or not verification_id:
        raise ValueError("Receipt reference, provider, and verification ID are required.")
    if len(reference) > 200 or len(verification_id) > 300:
        raise ValueError("Payment reference or verification ID is too long.")
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("Currency must be a three-letter code.")
    if isinstance(telegram_id, bool):
        raise ValueError("telegram_id must be a non-negative integer.")
    try:
        telegram_id = int(telegram_id)
    except (ValueError, TypeError, OverflowError) as exc:
        raise ValueError("telegram_id must be a non-negative integer.") from exc
    if telegram_id < 0:
        raise ValueError("telegram_id must be a non-negative integer.")

    gross = _money(_decimal(amount, "Gross amount"))
    net = _money(_decimal(net_amount, "Net amount"))
    rate = _decimal(fx_to_usd, "FX rate")
    if gross <= 0:
        raise ValueError("Gross amount must be positive.")
    if net <= 0 or net > gross:
        raise ValueError("Net amount must be positive and cannot exceed gross amount.")
    if rate <= 0:
        raise ValueError("FX rate must be positive.")
    if currency == "USD" and rate != Decimal("1"):
        raise ValueError("USD receipts must use an FX rate of 1.")

    net_usd = _money(net * rate)
    if net_usd <= 0:
        raise ValueError("Converted eligible receipt must be positive.")

    now = int(time.time())
    fx_timestamp = int(fx_recorded_at) if fx_recorded_at is not None else now
    fx_source = str(fx_source).strip()[:200]
    batches: list[dict[str, str]] = []
    allocated_total = ZERO

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute(
            """SELECT reference,net_usd,verification_provider,verification_id
               FROM deposits WHERE reference=?""",
            (reference,),
        ).fetchone()

        if existing:
            if (
                str(existing["verification_provider"]) != provider
                or str(existing["verification_id"]) != verification_id
            ):
                conn.rollback()
                raise ValueError(
                    "Receipt reference already exists with different verification details."
                )
            conn.rollback()
            return {
                "ok": True,
                "status": "duplicate_ignored",
                "reference": reference,
                "eligible_net_usd": str(existing["net_usd"]),
                "allocated_usd": "0.00",
                "batches_created": [],
            }

        if not {"fx_source", "fx_recorded_at"}.issubset(_columns(conn, "deposits")):
            conn.rollback()
            raise RuntimeError("Call init_db() before recording receipts.")

        splits = _get_splits(conn)
        conn.execute("""
            INSERT INTO deposits(
                reference,telegram_id,amount,currency,net_amount,fx_to_usd,net_usd,
                verification_provider,verification_id,recorded_at,fx_source,fx_recorded_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            reference, telegram_id, str(gross), currency, str(net), str(rate),
            str(net_usd), provider, verification_id, now, fx_source, fx_timestamp,
        ))

        carry = _decimal(
            _metadata_get(conn, "allocation_carry_usd", "0.00"),
            "Allocation carry",
        )
        if carry < ZERO or carry >= ALLOCATION_BATCH_USD:
            raise RuntimeError("Stored allocation carry must be between $0 and $50.")

        available = carry + net_usd
        batch_number = 0

        while available >= ALLOCATION_BATCH_USD:
            batch_number += 1
            batch_ref = f"{reference}:batch:{batch_number}"
            batch_amount = ALLOCATION_BATCH_USD
            cur = conn.execute("""
                INSERT INTO allocation_batches(
                    batch_reference,amount_usd,batch_amount_usd,created_at
                ) VALUES(?,?,?,?)
            """, (batch_ref, str(batch_amount), str(batch_amount), now))
            batch_id = cur.lastrowid

            amounts = {
                category: _money(batch_amount * share)
                for category, share in splits.items()
            }
            rounding_delta = batch_amount - sum(amounts.values(), ZERO)
            if rounding_delta:
                amounts["PERSONAL_UPKEEP"] = _money(
                    amounts["PERSONAL_UPKEEP"] + rounding_delta
                )
            if sum(amounts.values(), ZERO) != batch_amount:
                raise RuntimeError("Allocation batch does not total exactly $50.")

            for category, share in splits.items():
                conn.execute("""
                    INSERT INTO allocations(
                        batch_id,category,percentage,amount_usd,status,created_at
                    ) VALUES(?,?,?,?,?,?)
                """, (
                    batch_id, category, str(share), str(amounts[category]),
                    "LEDGER_ONLY", now,
                ))

            available -= batch_amount
            allocated_total += batch_amount
            batches.append({
                "batch_reference": batch_ref,
                "amount_usd": str(batch_amount),
            })

        carry = _money(available)
        _metadata_set(conn, "allocation_carry_usd", carry)
        _metadata_set(conn, "allocation_carry_forward_usd", carry)
        _metadata_set(conn, "last_verified_receipt_at", now)
        conn.commit()

    logger.info(
        "Verified receipt recorded: reference=%s net_usd=%s allocated=%s",
        reference, net_usd, allocated_total,
    )
    return {
        "ok": True,
        "status": "recorded",
        "reference": reference,
        "currency": currency,
        "gross_amount": str(gross),
        "net_amount": str(net),
        "fx_to_usd": str(rate),
        "fx_source": fx_source,
        "fx_recorded_at": fx_timestamp,
        "eligible_net_usd": str(net_usd),
        "allocated_usd": str(allocated_total),
        "carry_usd": str(carry),
        "batches_created": batches,
        "transfers_executed": False,
        "note": "Ledger bookkeeping only; no transfer or investment was executed.",
    }


def record_deposit(reference: str, telegram_id: int, amount: Any) -> bool:
    """Legacy compatibility guard; unverified deposits cannot be recorded."""
    raise RuntimeError(
        "Direct deposit recording is disabled. Use trusted payment verification "
        "before calling record_verified_receipt()."
    )


def update_ledger_yield(value: Any) -> None:
    """Record an indicative market comparison; never realized profit."""
    indicative = _decimal(value, "Indicative yield")
    now = int(time.time())

    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _metadata_set(conn, "indicative_yield_pct", indicative)
        _metadata_set(conn, "indicative_yield", indicative)
        conn.execute("""
            INSERT INTO ledger_yield_history(
                value,indicative_difference_pct,recorded_at
            ) VALUES(?,?,?)
        """, (str(indicative), str(indicative), now))
        conn.execute("""
            INSERT INTO indicative_metrics(
                metric_name,metric_value,recorded_at,updated_at
            ) VALUES(?,?,?,?)
        """, ("indicative_price_difference_pct", str(indicative), now, now))
        conn.commit()


def get_indicative_yield() -> dict[str, str]:
    with get_connection() as conn:
        value = _metadata_get(
            conn,
            "indicative_yield_pct",
            _metadata_get(conn, "indicative_yield", "0.00"),
        )
    return {
        "indicative_difference_pct": value,
        "status": "indicative_only",
        "realized_profit": "not_calculated",
    }


def get_ledger_metrics() -> dict[str, Any]:
    with get_connection() as conn:
        receipt_count = conn.execute(
            "SELECT COUNT(*) AS n FROM deposits"
        ).fetchone()["n"]
        receipt_total = conn.execute("""
            SELECT COALESCE(SUM(CAST(net_usd AS REAL)),0) AS n FROM deposits
        """).fetchone()["n"]
        batch_count = conn.execute(
            "SELECT COUNT(*) AS n FROM allocation_batches"
        ).fetchone()["n"]
        carry = _metadata_get(conn, "allocation_carry_usd", "0.00")
        categories = conn.execute("""
            SELECT category,COALESCE(SUM(CAST(amount_usd AS REAL)),0) AS total
            FROM allocations GROUP BY category ORDER BY category
        """).fetchall()
        batch_total = conn.execute("""
            SELECT COALESCE(
                SUM(CAST(COALESCE(NULLIF(amount_usd,''),batch_amount_usd) AS REAL)),0
            ) AS n FROM allocation_batches
        """).fetchone()["n"]

    receipts = round(float(receipt_total), 2)
    carry_text = f"{_safe_float(carry):.2f}"
    category_totals = {
        str(row["category"]): round(float(row["total"]), 2)
        for row in categories
    }
    return {
        "verified_receipt_count": int(receipt_count),
        "verified_net_receipts_usd": receipts,
        "eligible_net_receipts_usd": receipts,
        "allocation_batch_count": int(batch_count),
        "allocation_batch_size_usd": str(ALLOCATION_BATCH_USD),
        "amount_allocated_usd": round(float(batch_total), 2),
        "allocation_carry_forward_usd": carry_text,
        "allocation_carry_usd": carry_text,
        "allocation_ledger_by_category": category_totals,
        "realized_profit_usd": None,
        "transfers_executed": False,
        "note": (
            "Eligible net receipts are not trading profits. Allocation rows "
            "are bookkeeping and do not prove funds were transferred or invested."
        ),
    }


def get_comprehensive_performance_metrics() -> dict[str, Any]:
    ledger = get_ledger_metrics()
    indicative = get_indicative_yield()

    with get_connection() as conn:
        latest = conn.execute("""
            SELECT metric_name,metric_value,
                   COALESCE(recorded_at,updated_at,0) AS event_time
            FROM indicative_metrics
            ORDER BY COALESCE(recorded_at,updated_at,0) DESC,id DESC
            LIMIT 1
        """).fetchone()

    return {
        "database_status": "reachable",
        "verified_receipts": ledger["verified_receipt_count"],
        "verified_receipt_count": ledger["verified_receipt_count"],
        "verified_net_receipts_usd": ledger["verified_net_receipts_usd"],
        "eligible_net_receipts_usd": ledger["eligible_net_receipts_usd"],
        "allocation_batch_count": ledger["allocation_batch_count"],
        "amount_allocated_usd": ledger["amount_allocated_usd"],
        "allocation_carry_usd": ledger["allocation_carry_usd"],
        "allocation_carry_forward_usd": ledger["allocation_carry_forward_usd"],
        "allocation_ledger_by_category": ledger["allocation_ledger_by_category"],
        "indicative_yield_pct": indicative["indicative_difference_pct"],
        "latest_indicative_metric": (
            {
                "name": str(latest["metric_name"]),
                "value": str(latest["metric_value"]),
                "recorded_at": int(latest["event_time"]),
            } if latest else None
        ),
        "indicative_metric_is_realized_profit": False,
        "realized_profit_usd": None,
        "live_trading_enabled": False,
        "transfers_executed": False,
    }


def database_health_check() -> dict[str, Any]:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
            if _table_exists(conn, "deposits"):
                conn.execute("SELECT COUNT(*) FROM deposits").fetchone()
        return {
            "status": "ok",
            "database": "reachable",
            "database_path": DATABASE_PATH,
            "checked_at": int(time.time()),
            "schema_version": VERSION,
        }
    except Exception as exc:
        logger.exception("Database health check failed.")
        return {
            "status": "error",
            "database": "unavailable",
            "error_type": type(exc).__name__,
            "checked_at": int(time.time()),
        }


def update_settlement_account(
    provider: str = "",
    account_reference: str = "",
    currency: str = "",
    *,
    bank_name: str | None = None,
    account_number: str | None = None,
    account_name: str | None = None,
) -> None:
    """Store sensitive settlement metadata for trusted internal use only."""
    chosen_provider = str(bank_name if bank_name is not None else provider).strip()
    chosen_reference = str(
        account_number if account_number is not None else account_reference
    ).strip()
    chosen_currency = str(
        account_name if account_name is not None else currency
    ).strip()

    if not chosen_provider or not chosen_reference or not chosen_currency:
        raise ValueError("All settlement-account fields are required.")

    now = int(time.time())
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        _metadata_set(conn, "settlement_bank_name", chosen_provider)
        _metadata_set(conn, "settlement_account_number", chosen_reference)
        _metadata_set(conn, "settlement_account_name", chosen_currency)
        conn.execute("""
            INSERT INTO settlement_account(
                id,provider,account_reference,currency,updated_at
            ) VALUES(1,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
                provider=excluded.provider,
                account_reference=excluded.account_reference,
                currency=excluded.currency,
                updated_at=excluded.updated_at
        """, (chosen_provider, chosen_reference, chosen_currency, now))
        conn.commit()


def get_settlement_account() -> dict[str, str] | None:
    """Return settlement details only to a trusted internal caller."""
    with get_connection() as conn:
        row = conn.execute("""
            SELECT provider,account_reference,currency
            FROM settlement_account WHERE id=1
        """).fetchone()

        if row and row["provider"] and row["account_reference"] and row["currency"]:
            provider = str(row["provider"])
            reference = str(row["account_reference"])
            currency = str(row["currency"])
        else:
            provider = _metadata_get(conn, "settlement_bank_name", "")
            reference = _metadata_get(conn, "settlement_account_number", "")
            currency = _metadata_get(conn, "settlement_account_name", "")

    if not (provider and reference and currency):
        return None

    return {
        "provider": provider,
        "account_reference": reference,
        "currency": currency,
        "bank_name": provider,
        "account_number": reference,
        "account_name": currency,
    }


if __name__ == "__main__":
    init_db()
    print(f"Free Arbitrage Mesh database initialized (schema {VERSION}).")
    print(get_ledger_metrics())
