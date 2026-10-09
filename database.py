import sqlite3
import time
from threading import Lock

DB_PATH = "arbitrage_vault.db"
db_lock = Lock()

def init_db():
    """ Initializes schema frameworks natively with standard indexing arrays """
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        # 1. Core Balance Ledger Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                total_vault_balance REAL NOT NULL,
                today_yield REAL NOT NULL,
                last_updated REAL NOT NULL
            )
        """)
        # 2. Historical Transaction Log Table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS transactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trx_ref TEXT UNIQUE NOT NULL,
                telegram_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT NOT NULL,
                timestamp REAL NOT NULL
            )
        """)
        
        # Seed initial system states if the platform table is blank
        cursor.execute("SELECT COUNT(*) FROM system_ledger")
        if cursor.fetchone()[0] == 0:
            cursor.execute(
                "INSERT INTO system_ledger (total_vault_balance, today_yield, last_updated) VALUES (?, ?, ?)",
                (42500.00, 1.42, time.time())
            )
        conn.commit()
    print("💾 [DATABASE] Thread-safe SQLite operational matrices initialized.")

def get_ledger_metrics():
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT total_vault_balance, today_yield FROM system_ledger WHERE id = 1")
        return cursor.fetchone()

def update_ledger_yield(new_yield):
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE system_ledger SET today_yield = ?, last_updated = ? WHERE id = 1",
            (new_yield, time.time())
        )
        conn.commit()

def record_deposit(trx_ref, telegram_id, amount):
    """ Atomic Operation: Credits user wallet ledger balances and logs the receipt history """
    with db_lock, sqlite3.connect(DB_PATH) as conn:
        cursor = conn.cursor()
        try:
            # Insert log block into transaction histories
            cursor.execute(
                "INSERT INTO transactions (trx_ref, telegram_id, amount, status, timestamp) VALUES (?, ?, ?, ?, ?)",
                (trx_ref, telegram_id, amount, "SUCCESS", time.time())
            )
            # Increment the primary system vault balance
            cursor.execute(
                "UPDATE system_ledger SET total_vault_balance = total_vault_balance + ?, last_updated = ? WHERE id = 1",
                (amount, time.time())
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            conn.rollback()
            print(f"⚠️ [DATABASE] Duplicate transaction hash signature dropped: {trx_ref}")
            return False
