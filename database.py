
"""
Free Arbitrage Mesh — Shared Database
Version: 2.0.0

Responsibilities:
- Persistent SQLite ledger
- Idempotent verified receipt recording
- USD 50 allocation batches with remainder carry-forward
- Configurable portfolio allocation percentages
- Indicative yield tracking, separate from realized profit
- Database health and performance metrics

IMPORTANT:
Only a trusted server-side payment verifier should call
record_verified_receipt(). Discovery estimates are not income.
Ledger allocations are bookkeeping, not actual bank transfers
or executed investments.
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


# ============================================================
# 1. CONFIGURATION
# ============================================================

DATABASE_PATH = os.getenv(
    "MATRIX_DATABASE_PATH", "matrix_system.db"
).strip()

DB_TIMEOUT_SECONDS = 30
CENT = Decimal("0.01")
ZERO = Decimal("0.00")
ALLOCATION_BATCH_USD = Decimal("50.00")

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=LOG_LEVEL,
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


# ============================================================
# 2. DATABASE CONNECTION
# ============================================================

@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    """
    Open a database connection with busy timeout and foreign keys.

    The connection is closed automatically. Transactions should be
    committed explicitly by write operations.
    """
    path = Path(DATABASE_PATH)
    if str(path.parent) not in ("", "."):
        path.parent.mkdir(parents=True, exist_ok=True)

    connection = sqlite3.connect(
        DATABASE_PATH,
        timeout=DB_TIMEOUT_SECONDS,
        isolation_level="DEFERRED",
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 30000")
    connection.execute("PRAGMA foreign_keys = ON")

    try:
        yield connection
    finally:
        connection.close()


# ============================================================
# 3. DECIMAL AND CONFIGURATION HELPERS
# ============================================================

def _decimal(value: Any, field: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} must be a valid decimal number.") from exc

    if not result.is_finite():
        raise ValueError(f"{field} must be finite.")

    return result


def _money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def _validate_splits(splits: dict[str, Any]) -> dict[str, Decimal]:
    if set(splits) != set(DEFAULT_SPLITS):
        raise ValueError(
            "Allocation configuration must contain exactly the seven "
            "supported portfolio categories."
        )

    normalized: dict[str, Decimal] = {}

    for key, value in splits.items():
        share = _decimal(value, f"Allocation {key}")

        if share < 0 or share > 1:
            raise ValueError(
                f"Allocation {key} must be between zero and one."
            )

        normalized[key] = share

    if sum(normalized.values(), Decimal("0")) != Decimal("1"):
        raise ValueError("Allocation percentages must sum to 100%.")

    return normalized


def _metadata_get(
    connection: sqlite3.Connection,
    key: str,
    default: str = "",
) -> str:
    row = connection.execute(
        "SELECT value FROM system_metadata WHERE key = ?",
        (key,),
    ).fetchone()

    return str(row["value"]) if row else default


def _metadata_set(
    connection: sqlite3.Connection,
    key: str,
    value: str,
) -> None:
    connection.execute(
        """
        INSERT INTO system_metadata (key, value)
        VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )


def _get_splits(connection: sqlite3.Connection) -> dict[str, Decimal]:
    values = {}

    for key, default in DEFAULT_SPLITS.items():
        raw = _metadata_get(connection, f"allocation_{key}", str(default))
        values[key] = _decimal(raw, f"Stored allocation {key}")

    return _validate_splits(values)


# ============================================================
# 4. INITIALIZATION AND SCHEMA
# ============================================================

def init_db() -> None:
    """Create all shared tables and initialize default settings."""
    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        connection.executescript("""
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
                verification_provider TEXT NOT NULL,
                verification_id TEXT NOT NULL,
                recorded_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS allocation_batches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_reference TEXT NOT NULL UNIQUE,
                batch_amount_usd TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS allocations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                batch_id INTEGER NOT NULL,
                category TEXT NOT NULL,
                percentage TEXT NOT NULL,
                amount_usd TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                FOREIGN KEY(batch_id)
                    REFERENCES allocation_batches(id),
                UNIQUE(batch_id, category)
            );

            CREATE TABLE IF NOT EXISTS indicative_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                metric_name TEXT NOT NULL,
                metric_value TEXT NOT NULL,
                updated_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS ledger_yield_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                indicative_difference_pct TEXT NOT NULL,
                recorded_at INTEGER NOT NULL
            );

            CREATE TABLE IF NOT EXISTS task_hunter_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                task_id TEXT,
                message TEXT NOT NULL,
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

            CREATE INDEX IF NOT EXISTS idx_deposits_recorded_at
                ON deposits(recorded_at);

            CREATE INDEX IF NOT EXISTS idx_allocations_category
                ON allocations(category);

            CREATE INDEX IF NOT EXISTS idx_discovered_tasks_first_seen
                ON discovered_tasks(first_seen_at DESC);
        """)

        for key, value in DEFAULT_SPLITS.items():
            _metadata_set(
                connection,
                f"allocation_{key}",
                str(value),
            )

        _metadata_set(
            connection,
            "allocation_batch_usd",
            str(ALLOCATION_BATCH_USD),
        )

        _metadata_set(
            connection,
            "allocation_carry_usd",
            _metadata_get(
                connection,
                "allocation_carry_usd",
                "0.00",
            ),
        )

        _metadata_set(
            connection,
            "indicative_yield_pct",
            _metadata_get(
                connection,
                "indicative_yield_pct",
                "0.00",
            ),
        )

        connection.commit()

    logger.info("Shared database initialized.")


# ============================================================
# 5. ALLOCATION SETTINGS
# ============================================================

def get_tuning_matrix() -> dict[str, str]:
    """Return allocation percentages as strings."""
    with get_connection() as connection:
        splits = _get_splits(connection)

    return {key: str(value) for key, value in splits.items()}


def update_tuning_matrix(splits: dict[str, Any]) -> dict[str, str]:
    """Update allocation percentages after validating a 100% total."""
    normalized = _validate_splits(splits)

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        for key, value in normalized.items():
            _metadata_set(connection, f"allocation_{key}", str(value))

        connection.commit()

    return {key: str(value) for key, value in normalized.items()}


# ============================================================
# 6. VERIFIED RECEIPTS AND ATOMIC $50 USD BATCHES
# ============================================================

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
) -> dict[str, Any]:
    """
    Record a receipt AFTER a trusted server-side provider verifier
    has authenticated and confirmed the payment.

    amount:
        Original gross amount in the receipt currency.

    net_amount:
        Amount eligible for allocation after fees, refunds and other
        deductions, expressed in the original receipt currency.

    fx_to_usd:
        Verified conversion rate: USD per one unit of receipt currency.
        For USD receipts, use 1.

    This function does not itself verify Paystack or any other provider.
    Only the verified-payment integration should call it.
    """
    reference = str(reference).strip()
    currency = str(currency).strip().upper()
    provider = str(verification_provider).strip()
    verification_id = str(verification_id).strip()

    if not reference or not provider or not verification_id:
        raise ValueError(
            "Receipt reference, verification provider, and "
            "verification ID are required."
        )

    if len(reference) > 200 or len(verification_id) > 300:
        raise ValueError("Payment reference is too long.")

    if not currency or len(currency) != 3 or not currency.isalpha():
        raise ValueError("Currency must be a three-letter currency code.")

    if telegram_id < 0:
        raise ValueError("telegram_id cannot be negative.")

    gross = _money(_decimal(amount, "Gross amount"))
    net = _money(_decimal(net_amount, "Net amount"))
    rate = _decimal(fx_to_usd, "FX rate")

    if gross <= 0:
        raise ValueError("Gross amount must be positive.")

    if net <= 0 or net > gross:
        raise ValueError(
            "Net amount must be positive and cannot exceed gross amount."
        )

    if rate <= 0:
        raise ValueError("FX rate must be positive.")

    if currency == "USD" and rate != Decimal("1"):
        raise ValueError("USD receipts must use an FX rate of 1.")

    net_usd = _money(net * rate)

    if net_usd <= 0:
        raise ValueError("Converted eligible receipt must be positive.")

    now = int(time.time())
    new_batches: list[dict[str, Any]] = []

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        existing = connection.execute(
            "SELECT reference FROM deposits WHERE reference = ?",
            (reference,),
        ).fetchone()

        if existing:
            connection.rollback()
            return {
                "ok": True,
                "status": "duplicate_ignored",
                "reference": reference,
                "allocated_usd": "0.00",
            }

        splits = _get_splits(connection)

        # Persist the verified receipt exactly once.
        connection.execute(
            """
            INSERT INTO deposits (
                reference, telegram_id, amount, currency,
                net_amount, fx_to_usd, net_usd,
                verification_provider, verification_id, recorded_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                reference,
                int(telegram_id),
                str(gross),
                currency,
                str(net),
                str(rate),
                str(net_usd),
                provider,
                verification_id,
                now,
            ),
        )

        carry = _decimal(
            _metadata_get(connection, "allocation_carry_usd", "0.00"),
            "Allocation carry",
        )

        if carry < 0 or carry >= ALLOCATION_BATCH_USD:
            raise RuntimeError(
                "Stored allocation carry is outside the expected range."
            )

        available = carry + net_usd
        allocated_total = ZERO
        batch_number = 0

        while available >= ALLOCATION_BATCH_USD:
            batch_number += 1
            batch_amount = ALLOCATION_BATCH_USD

            batch_reference = f"{reference}:batch:{batch_number}"

            cursor = connection.execute(
                """
                INSERT INTO allocation_batches (
                    batch_reference, batch_amount_usd, created_at
                )
                VALUES (?, ?, ?)
                """,
                (batch_reference, str(batch_amount), now),
            )

            batch_id = cursor.lastrowid
            allocated_this_batch = ZERO

            for category, percentage in splits.items():
                if category == "SPORTS_BETTING":
                    # Round to cents like every other category.
                    allocation = _money(batch_amount * percentage)
                else:
                    allocation = _money(batch_amount * percentage)

                allocated_this_batch += allocation

                connection.execute(
                    """
                    INSERT INTO allocations (
                        batch_id, category, percentage,
                        amount_usd, created_at
                    )
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        batch_id,
                        category,
                        str(percentage),
                        str(allocation),
                        now,
                    ),
                )

            # Keep rounding differences explicit rather than hiding them.
            rounding_difference = batch_amount - allocated_this_batch

            if rounding_difference != ZERO:
                personal = connection.execute(
                    """
                    SELECT id, amount_usd FROM allocations
                    WHERE batch_id = ? AND category = 'PERSONAL_UPKEEP'
                    """,
                    (batch_id,),
                ).fetchone()

                adjusted = _money(
                    _decimal(personal["amount_usd"], "Personal allocation")
                    + rounding_difference
                )

                connection.execute(
                    "UPDATE allocations SET amount_usd = ? WHERE id = ?",
                    (str(adjusted), personal["id"]),
                )

            available -= batch_amount
            allocated_total += batch_amount

            new_batches.append({
                "batch_reference": batch_reference,
                "amount_usd": str(batch_amount),
            })

        _metadata_set(
            connection,
            "allocation_carry_usd",
            str(_money(available)),
        )

        _metadata_set(
            connection,
            "last_verified_receipt_at",
            str(now),
        )

        connection.commit()

    logger.info(
        "Verified receipt recorded. reference=%s net_usd=%s allocated=%s",
        reference,
        net_usd,
        allocated_total,
    )

    return {
        "ok": True,
        "status": "recorded",
        "reference": reference,
        "currency": currency,
        "gross_amount": str(gross),
        "net_amount": str(net),
        "fx_to_usd": str(rate),
        "eligible_net_usd": str(net_usd),
        "allocated_usd": str(allocated_total),
        "carry_usd": str(_money(available)),
        "batches_created": new_batches,
        "note": (
            "Internal bookkeeping only. No bank transfer or investment "
            "was executed by this database function."
        ),
    }


def record_deposit(
    reference: str,
    telegram_id: int,
    amount: Any,
) -> bool:
    """
    Legacy compatibility guard.

    Older modules called this function without trusted provider evidence.
    Such calls must not silently create verified income. Update callers
    to use record_verified_receipt() after real payment verification.
    """
    raise RuntimeError(
        "Direct deposit recording is disabled. Use the trusted "
        "payment-verification integration and record_verified_receipt()."
    )


# ============================================================
# 7. INDICATIVE YIELD — NEVER REALIZED PROFIT
# ============================================================

def update_ledger_yield(value: Any) -> None:
    """
    Save a market comparison metric.

    This value is indicative only. It must never modify deposits,
    allocation balances, realized profit, or investment returns.
    """
    indicative_value = _decimal(value, "Indicative yield")

    now = int(time.time())

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        _metadata_set(
            connection,
            "indicative_yield_pct",
            str(indicative_value),
        )

        connection.execute(
            """
            INSERT INTO ledger_yield_history (
                indicative_difference_pct, recorded_at
            )
            VALUES (?, ?)
            """,
            (str(indicative_value), now),
        )

        connection.commit()


def get_indicative_yield() -> dict[str, str]:
    with get_connection() as connection:
        value = _metadata_get(
            connection,
            "indicative_yield_pct",
            "0.00",
        )

    return {
        "indicative_difference_pct": value,
        "status": "indicative_only",
        "realized_profit": "not_calculated",
    }


# ============================================================
# 8. LEDGER METRICS AND HEALTH
# ============================================================

def get_ledger_metrics() -> dict[str, Any]:
    with get_connection() as connection:
        receipt_row = connection.execute(
            """
            SELECT COUNT(*) AS receipt_count
            FROM deposits
            """
        ).fetchone()

        total_row = connection.execute(
            """
            SELECT COALESCE(SUM(CAST(net_usd AS REAL)), 0)
                AS net_usd
            FROM deposits
            """
        ).fetchone()

        batch_row = connection.execute(
            """
            SELECT COUNT(*) AS batch_count
            FROM allocation_batches
            """
        ).fetchone()

        carry = _metadata_get(
            connection,
            "allocation_carry_usd",
            "0.00",
        )

    return {
        "verified_receipt_count": int(receipt_row["receipt_count"]),
        "eligible_net_receipts_usd": round(float(total_row["net_usd"]), 2),
        "allocation_batch_count": int(batch_row["batch_count"]),
        "allocation_batch_size_usd": str(ALLOCATION_BATCH_USD),
        "allocation_carry_usd": carry,
        "realized_profit_usd": None,
        "note": (
            "Receipt totals represent recorded eligible net receipts, "
            "not trading profits or funds transferred to investments."
        ),
    }


def get_comprehensive_performance_metrics() -> dict[str, Any]:
    """
    Conservative compatibility endpoint for older application code.
    Does not fabricate returns or report unverified balances as profit.
    """
    metrics = get_ledger_metrics()
    indicative = get_indicative_yield()

    return {
        "database_status": "reachable",
        "verified_receipts": metrics["verified_receipt_count"],
        "eligible_net_receipts_usd": metrics["eligible_net_receipts_usd"],
        "allocation_batch_count": metrics["allocation_batch_count"],
        "allocation_carry_usd": metrics["allocation_carry_usd"],
        "indicative_yield_pct": indicative["indicative_difference_pct"],
        "realized_profit_usd": None,
    }


def database_health_check() -> dict[str, Any]:
    try:
        with get_connection() as connection:
            connection.execute("SELECT 1").fetchone()

        return {
            "status": "ok",
            "database": "reachable",
        }

    except Exception:
        logger.exception("Database health check failed.")
        return {
            "status": "error",
            "database": "unavailable",
        }


# ============================================================
# 9. OPTIONAL SETTLEMENT ACCOUNT METADATA
# ============================================================

def update_settlement_account(
    bank_name: str,
    account_number: str,
    account_name: str,
) -> None:
    """
    Store settlement details for internal configuration only.

    Do not expose these values through public status endpoints.
    For production, prefer a protected secret store and restrict access.
    """
    values = {
        "settlement_bank_name": str(bank_name).strip(),
        "settlement_account_number": str(account_number).strip(),
        "settlement_account_name": str(account_name).strip(),
    }

    if not all(values.values()):
        raise ValueError("All settlement account fields are required.")

    with get_connection() as connection:
        connection.execute("BEGIN IMMEDIATE")

        for key, value in values.items():
            _metadata_set(connection, key, value)

        connection.commit()


def get_settlement_account() -> dict[str, str]:
    """Return settlement details only to a trusted internal caller."""
    with get_connection() as connection:
        return {
            "bank_name": _metadata_get(
                connection, "settlement_bank_name"
            ),
            "account_number": _metadata_get(
                connection, "settlement_account_number"
            ),
            "account_name": _metadata_get(
                connection, "settlement_account_name"
            ),
        }


# ============================================================
# 10. COMMAND-LINE INITIALIZATION
# ============================================================

if __name__ == "__main__":
    init_db()
    print("Free Arbitrage Mesh database initialized.")
    print(get_ledger_metrics())
