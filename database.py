
import os
import math
import sqlite3
import logging
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from contextlib import contextmanager

# =========================================================
# CONFIGURATION
# =========================================================

DATABASE_PATH = os.getenv("MATRIX_DATABASE_PATH", "matrix_system.db")
DATABASE_TIMEOUT_SECONDS = 15

PORTFOLIOS = (
    "PERSONAL_UPKEEP",
    "CRYPTO_ARBITRAGE",
    "FOREX_RESERVE",
    "STOCKS_EQUITIES",
    "COMMODITIES_GOLD",
    "ALT_MARKETS",
    "SPORTS_BETTING",
)

DEFAULT_SPLITS = {
    "PERSONAL_UPKEEP": "0.20",
    "CRYPTO_ARBITRAGE": "0.20",
    "FOREX_RESERVE": "0.20",
    "STOCKS_EQUITIES": "0.15",
    "COMMODITIES_GOLD": "0.10",
    "ALT_MARKETS": "0.10",
    "SPORTS_BETTING": "0.05",
}

CENT = Decimal("0.01")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
)
logger = logging.getLogger("matrix-database")


# =========================================================
# CONNECTION MANAGEMENT
# =========================================================

@contextmanager
def get_connection():
    conn = sqlite3.connect(
        DATABASE_PATH,
        timeout=DATABASE_TIMEOUT_SECONDS,
    )

    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA busy_timeout = 15000")
        yield conn
    finally:
        conn.close()


def _as_decimal(value, field_name="value"):
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"Invalid numeric {field_name}.")

    if not result.is_finite():
        raise ValueError(f"{field_name} must be finite.")

    return result


def _read_metadata(cursor, key, default="0"):
    row = cursor.execute(
        "SELECT value FROM system_metadata WHERE key = ?",
        (key,),
    ).fetchone()

    return row["value"] if row else default


def _validate_splits(splits):
    if not isinstance(splits, dict):
        raise ValueError("Allocation splits must be a dictionary.")

    if set(splits.keys()) != set(PORTFOLIOS):
        raise ValueError(
            "Allocation configuration must contain exactly "
            "the seven supported portfolio keys."
        )

    normalized = {}

    for key in PORTFOLIOS:
        value = _as_decimal(splits[key], f"split_{key}")

        if value < 0 or value > 1:
            raise ValueError(
                f"Split for {key} must be between 0 and 1."
            )

        normalized[key] = value

    if sum(normalized.values()) != Decimal("1"):
        raise ValueError(
            "Portfolio splits must total exactly 1.00 (100%)."
        )

    return normalized


# =========================================================
# INITIALIZE DATABASE
# =========================================================

def init_db():
    with get_connection() as conn:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS deposits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    reference TEXT UNIQUE NOT NULL,
                    telegram_id INTEGER NOT NULL,
                    amount REAL NOT NULL CHECK (amount > 0),
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS system_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT
                )
            """)

            for key in PORTFOLIOS:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO system_metadata (key, value)
                    VALUES (?, '0.00')
                    """,
                    (key,),
                )

            for key, value in DEFAULT_SPLITS.items():
                conn.execute(
                    """
                    INSERT OR IGNORE INTO system_metadata (key, value)
                    VALUES (?, ?)
                    """,
                    (f"split_{key}", value),
                )

    logger.info("Database initialization completed.")


# =========================================================
# SETTLEMENT ACCOUNT METADATA
# Store only what your application genuinely needs.
# Restrict access to this database and its backups.
# =========================================================

def update_settlement_account(bank_name, account_number, account_name):
    values = {
        "settlement_bank": str(bank_name).strip(),
        "settlement_account_no": str(account_number).strip(),
        "settlement_account_name": str(account_name).strip(),
    }

    if not all(values.values()):
        raise ValueError("All settlement account fields are required.")

    with get_connection() as conn:
        with conn:
            for key, value in values.items():
                conn.execute(
                    """
                    INSERT INTO system_metadata (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, value),
                )


def get_settlement_account():
    defaults = {
        "bank": "Not Synced",
        "account_number": "—",
        "account_name": "—",
    }

    try:
        with get_connection() as conn:
            rows = conn.execute(
                """
                SELECT key, value
                FROM system_metadata
                WHERE key IN (
                    'settlement_bank',
                    'settlement_account_no',
                    'settlement_account_name'
                )
                """
            ).fetchall()

            values = {row["key"]: row["value"] for row in rows}

            return {
                "bank": values.get("settlement_bank", defaults["bank"]),
                "account_number": values.get(
                    "settlement_account_no",
                    defaults["account_number"],
                ),
                "account_name": values.get(
                    "settlement_account_name",
                    defaults["account_name"],
                ),
            }

    except sqlite3.Error:
        logger.exception("Unable to retrieve settlement metadata.")
        return defaults


# =========================================================
# SPLIT CONFIGURATION
# =========================================================

def get_tuning_matrix():
    with get_connection() as conn:
        return {
            key: float(
                _as_decimal(
                    _read_metadata(conn.cursor(), f"split_{key}", "0")
                )
            )
            for key in PORTFOLIOS
        }


def update_tuning_matrix(new_matrix):
    """
    Accepts a mapping of portfolio names to decimal fractions.

    Example:
    {
        "PERSONAL_UPKEEP": 0.20,
        "CRYPTO_ARBITRAGE": 0.20,
        ...
    }
    """
    try:
        normalized = _validate_splits(new_matrix)

        with get_connection() as conn:
            with conn:
                for key in PORTFOLIOS:
                    conn.execute(
                        """
                        INSERT INTO system_metadata (key, value)
                        VALUES (?, ?)
                        ON CONFLICT(key) DO UPDATE SET value = excluded.value
                        """,
                        (f"split_{key}", str(normalized[key])),
                    )

        return True

    except (ValueError, sqlite3.Error):
        logger.exception("Could not update allocation configuration.")
        return False


# =========================================================
# DEPOSIT LEDGER AND ATOMIC SEVEN-WAY ALLOCATION
# IMPORTANT:
# Call this only after independently verifying an actual receipt.
# =========================================================

def record_deposit(reference, telegram_id, amount):
    reference = str(reference).strip()

    if not reference or len(reference) > 200:
        raise ValueError("A valid transaction reference is required.")

    try:
        telegram_id = int(telegram_id)
    except (TypeError, ValueError):
        raise ValueError("telegram_id must be an integer.")

    if telegram_id <= 0:
        raise ValueError("telegram_id must be positive.")

    deposit_amount = _as_decimal(amount, "deposit amount")

    if deposit_amount <= 0:
        raise ValueError("Deposit amount must be greater than zero.")

    deposit_amount = deposit_amount.quantize(
        CENT,
        rounding=ROUND_HALF_UP,
    )

    if deposit_amount <= 0:
        raise ValueError("Deposit amount is too small.")

    try:
        with get_connection() as conn:
            # A single writer at a time prevents concurrent allocations
            # from reading and overwriting the same portfolio balances.
            conn.execute("BEGIN IMMEDIATE")

            existing = conn.execute(
                "SELECT 1 FROM deposits WHERE reference = ?",
                (reference,),
            ).fetchone()

            if existing:
                conn.rollback()
                logger.warning(
                    "Duplicate deposit reference rejected: %s",
                    reference,
                )
                return False

            cursor = conn.cursor()

            splits = {
                key: _as_decimal(
                    _read_metadata(cursor, f"split_{key}", "0"),
                    f"split_{key}",
                )
                for key in PORTFOLIOS
            }

            splits = _validate_splits(splits)

            allocations = {}
            allocated_so_far = Decimal("0.00")

            # Round each allocation to two decimal places. Assign any
            # rounding remainder to the final portfolio so the allocated
            # total matches the original deposit.
            for index, key in enumerate(PORTFOLIOS):
                if index == len(PORTFOLIOS) - 1:
                    allocation = deposit_amount - allocated_so_far
                else:
                    allocation = (
                        deposit_amount * splits[key]
                    ).quantize(CENT, rounding=ROUND_HALF_UP)

                    allocated_so_far += allocation

                allocations[key] = allocation

            if sum(allocations.values()) != deposit_amount:
                raise ValueError("Allocation totals failed validation.")

            conn.execute(
                """
                INSERT INTO deposits (reference, telegram_id, amount)
                VALUES (?, ?, ?)
                """,
                (reference, telegram_id, float(deposit_amount)),
            )

            for key in PORTFOLIOS:
                current_balance = _as_decimal(
                    _read_metadata(cursor, key, "0"),
                    key,
                )

                new_balance = (
                    current_balance + allocations[key]
                ).quantize(CENT, rounding=ROUND_HALF_UP)

                conn.execute(
                    """
                    INSERT INTO system_metadata (key, value)
                    VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, str(new_balance)),
                )

            conn.commit()

            logger.info(
                "Verified deposit recorded and allocated. "
                "Reference=%s Amount=%s",
                reference,
                deposit_amount,
            )

            return True

    except (ValueError, sqlite3.Error):
        logger.exception("Deposit transaction failed.")
        return False


# =========================================================
# PORTFOLIO METRICS
# =========================================================

def get_ledger_metrics():
    with get_connection() as conn:
        cursor = conn.cursor()

        return {
            key: float(_as_decimal(_read_metadata(cursor, key, "0"), key))
            for key in PORTFOLIOS
        }


def update_ledger_yield(yield_percent):
    """
    Stores the latest indicative market-price difference.

    This is not realized profit, deposit income, or a verified return.
    """
    value = _as_decimal(yield_percent, "indicative yield")

    with get_connection() as conn:
        with conn:
            conn.execute(
                """
                INSERT INTO system_metadata (key, value)
                VALUES ('latest_indicative_yield_pct', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (str(value),),
            )


def get_comprehensive_performance_metrics():
    try:
        with get_connection() as conn:
            rows = conn.execute(
                "SELECT key, value FROM system_metadata"
            ).fetchall()

            metadata = {row["key"]: row["value"] for row in rows}

            portfolio_balances = {
                key: float(
                    _as_decimal(metadata.get(key, "0"), key)
                )
                for key in PORTFOLIOS
            }

            total_allocated = sum(portfolio_balances.values())

            deposit_stats = conn.execute(
                "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM deposits"
            ).fetchone()

            deposit_count = int(deposit_stats[0] or 0)
            total_deposits = float(deposit_stats[1] or 0)

            return {
                "financial_summary": {
                    "gross_volume_processed_ngn": total_deposits,
                    "total_successful_deposits": deposit_count,
                    "active_matrix_allocation_pool_ngn": total_allocated,
                    "average_ticket_size_ngn": (
                        total_deposits / deposit_count
                        if deposit_count else 0.0
                    ),
                },
                "portfolio_matrix_breakdown": portfolio_balances,
                "indicative_market_data": {
                    "latest_price_difference_pct": metadata.get(
                        "latest_indicative_yield_pct"
                    ),
                    "description": (
                        "Price comparison only; not verified trading profit."
                    ),
                },
                "infrastructure_telemetry": {
                    "database_health": "OPTIMAL",
                    "storage_sync_state": (
                        "CONNECTED"
                        if metadata.get("settlement_bank")
                        else "PENDING_INITIALIZATION"
                    ),
                },
            }

    except (sqlite3.Error, ValueError, TypeError):
        logger.exception("Failed to compute performance metrics.")

        return {
            "status": "ERROR",
            "financial_summary": {
                "gross_volume_processed_ngn": 0.0,
                "total_successful_deposits": 0,
                "active_matrix_allocation_pool_ngn": 0.0,
                "average_ticket_size_ngn": 0.0,
            },
            "portfolio_matrix_breakdown": {},
            "infrastructure_telemetry": {
                "database_health": "CRITICAL_FAULT",
                "storage_sync_state": "ERROR",
            },
        }


# =========================================================
# BASIC DATABASE HEALTH CHECK
# =========================================================

def check_database_health():
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        logger.exception("Database health check failed.")
        return False
