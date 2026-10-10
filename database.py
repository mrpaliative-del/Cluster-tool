import sqlite3
import time

DB_PATH = "arbitrage_vault.db"

def init_db():
    """ Initializes the advanced 7-portfolio tables and core transactional tracking schemas """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Unified Transaction Logs Table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS transactions (
            trx_ref TEXT PRIMARY KEY,
            telegram_id INTEGER,
            amount REAL,
            status TEXT,
            timestamp REAL
        )
    """)
    
    # 2. Complete Multi-Asset Portfolio Balancing Matrix
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS asset_ledgers (
            portfolio_name TEXT PRIMARY KEY,
            balance REAL DEFAULT 0.0,
            last_updated REAL
        )
    """)
    
    # Core system portfolios seed array - Expanded to 7 investment vaults
    portfolios = [
        "PERSONAL_UPKEEP", 
        "CRYPTO_ARBITRAGE", 
        "FOREX_RESERVE", 
        "STOCKS_EQUITIES", 
        "COMMODITIES_GOLD", 
        "ALT_MARKETS",
        "SPORTS_BETTING"
    ]
    for portfolio in portfolios:
        try:
            cursor.execute(
                "INSERT OR IGNORE INTO asset_ledgers (portfolio_name, balance, last_updated) VALUES (?, 0.0, ?)",
                (portfolio, time.time())
            )
        except sqlite3.Error:
            pass
            
    conn.commit()
    conn.close()
    print("💾 [DATABASE CORE] Advanced 7-asset operational ledgers initialized successfully.")

def get_ledger_metrics():
    """ Safely extracts all active balance totals from our 7-asset system fields as a clean dictionary """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT portfolio_name, balance FROM asset_ledgers")
        rows = cursor.fetchall()
        
        # PRODUCTION FIX: Converts database rows directly into a key-value dictionary map
        metrics = {row[0]: row[1] for row in rows}
        
        # If the database was empty or unseeded, fall back to safe zero counters
        defaults = ["PERSONAL_UPKEEP", "CRYPTO_ARBITRAGE", "FOREX_RESERVE", "STOCKS_EQUITIES", "COMMODITIES_GOLD", "ALT_MARKETS", "SPORTS_BETTING"]
        for key in defaults:
            if key not in metrics:
                metrics[key] = 0.0
                
        return metrics
    except sqlite3.Error as e:
        print(f"❌ Database metrics retrieval fault: {e}")
        return {}
    finally:
        conn.close()

def record_deposit(trx_ref, telegram_id, amount):
    """ Routes incoming direct capital injections completely into Crypto Arbitrage """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO transactions (trx_ref, telegram_id, amount, status, timestamp) VALUES (?, ?, ?, ?, ?)",
            (trx_ref, telegram_id, amount, "SUCCESS", time.time())
        )
        cursor.execute(
            "UPDATE asset_ledgers SET balance = balance + ?, last_updated = ? WHERE portfolio_name = 'CRYPTO_ARBITRAGE'",
            (amount, time.time())
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        conn.rollback()
        return False
    finally:
        conn.close()

def process_cascading_income(task_id, raw_payout, source_platform):
    """ Atomic Operation: Automatically cuts task revenue seven ways via your exact percentage splits """
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO transactions (trx_ref, telegram_id, amount, status, timestamp) VALUES (?, ?, ?, ?, ?)",
            (f"TASK_{source_platform}_{task_id}", 8608729377, raw_payout, "SUCCESS", time.time())
        )
        
        splits = {
            "PERSONAL_UPKEEP": raw_payout * 0.20,   
            "CRYPTO_ARBITRAGE": raw_payout * 0.20,  
            "FOREX_RESERVE": raw_payout * 0.20,     
            "STOCKS_EQUITIES": raw_payout * 0.15,   
            "COMMODITIES_GOLD": raw_payout * 0.10,  
            "ALT_MARKETS": raw_payout * 0.10,        
            "SPORTS_BETTING": raw_payout * 0.05     
        }
        
        for portfolio, allocation in splits.items():
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
