import sqlite3
import time

DB_PATH = "arbitrage_vault.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Unified Transaction Logs
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            trx_ref TEXT PRIMARY KEY,
            telegram_id INTEGER,
            amount REAL,
            status TEXT,
            timestamp REAL
        )
    """)
    
    # 2. Multi-Asset Portfolio Balancing Matrix
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS asset_ledgers (
            portfolio_name TEXT PRIMARY KEY,
            balance REAL DEFAULT 0.0,
            last_updated REAL
        )
    """)
    
    # 3. NEW FEATURE: Dynamic Configuration Storage Array
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS allocation_rules (
            portfolio_name TEXT PRIMARY KEY,
            percentage REAL,
            last_tuned REAL
        )
    """)
    
    # Core default 7-asset split strategy array
    default_splits = {
        "PERSONAL_UPKEEP": 0.20,
        "CRYPTO_ARBITRAGE": 0.20,
        "FOREX_RESERVE": 0.20,
        "STOCKS_EQUITIES": 0.15,
        "COMMODITIES_GOLD": 0.10,
        "ALT_MARKETS": 0.10,
        "SPORTS_BETTING": 0.05
    }
    
    for portfolio, pct in default_splits.items():
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO asset_ledgers (portfolio_name, balance, last_updated) VALUES (?, 0.0, ?)",
                (portfolio, time.time())
            )
            cursor.execute(
                "INSERT OR IGNORE INTO allocation_rules (portfolio_name, percentage, last_tuned) VALUES (?, ?, ?)",
                (portfolio, pct, time.time())
            )
        except sqlite3.Error:
            pass
            
    conn.commit()
    conn.close()
    print("💾 [DATABASE CORE] Advanced dynamic tuning tables seeded successfully.")

def update_tuning_matrix(new_rules):
    """ Overwrites active portfolio splits over the network securely """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        for portfolio, pct in new_rules.items():
            cursor.execute(
                "UPDATE allocation_rules SET percentage = ?, last_tuned = ? WHERE portfolio_name = ?",
                (pct, time.time(), portfolio)
            )
        conn.commit()
        return True
    except sqlite3.Error:
        conn.rollback()
        return False
    finally:
        conn.close()

def process_cascading_income(task_id, raw_payout, source_platform):
    """ Atomic Operation: Automatically cuts task revenue based on your live dynamic ratios """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        # Extract live tuned percentages from database rows
        cursor.execute("SELECT portfolio_name, percentage FROM allocation_rules")
        rules = dict(cursor.fetchall())
        
        # Fallback to defaults if rules are not yet initialized or read incorrectly
        if not rules:
            rules = {"PERSONAL_UPKEEP": 0.20, "CRYPTO_ARBITRAGE": 0.20, "FOREX_RESERVE": 0.20, "STOCKS_EQUITIES": 0.15, "COMMODITIES_GOLD": 0.10, "ALT_MARKETS": 0.10, "SPORTS_BETTING": 0.05}
            
        cursor.execute(
            "INSERT INTO transactions (trx_ref, telegram_id, amount, status, timestamp) VALUES (?, ?, ?, ?, ?)",
            (f"TASK_{source_platform}_{task_id}", 8608729377, raw_payout, "SUCCESS", time.time())
        )
        
        splits = {}
        for portfolio, pct in rules.items():
            allocation = raw_payout * pct
            splits[portfolio] = allocation
            
            cursor.execute("""
                UPDATE asset_ledgers 
                SET balance = balance + ?, last_updated = ? 
                WHERE portfolio_name = ?
            """, (allocation, time.time(), portfolio))
            
        conn.commit()
        return splits
    except sqlite3.IntegrityError:
        conn.rollback()
        return None
    finally:
        conn.close()

# Keep your previous get_ledger_metrics and record_deposit functions exactly the same below...
def get_ledger_metrics():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT portfolio_name, balance FROM asset_ledgers")
        rows = cursor.fetchall()
        metrics = {row[0]: row[1] for row in rows}
        defaults = ["PERSONAL_UPKEEP", "CRYPTO_ARBITRAGE", "FOREX_RESERVE", "STOCKS_EQUITIES", "COMMODITIES_GOLD", "ALT_MARKETS", "SPORTS_BETTING"]
        for key in defaults:
            if key not in metrics: metrics[key] = 0.0
        return metrics
    except sqlite3.Error: return {}
    finally: conn.close()

def record_deposit(trx_ref, telegram_id, amount):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO transactions (trx_ref, telegram_id, amount, status, timestamp) VALUES (?, ?, ?, ?, ?)", (trx_ref, telegram_id, amount, "SUCCESS", time.time()))
        cursor.execute("UPDATE asset_ledgers SET balance = balance + ?, last_updated = ? WHERE portfolio_name = 'CRYPTO_ARBITRAGE'", (amount, time.time()))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally: conn.close()
