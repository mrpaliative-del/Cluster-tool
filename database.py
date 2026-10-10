import sqlite3

def init_db():
    """
    Initialises the SQLite structural schema layers required to sustain 
    the operational matrix framework.
    """
    conn = sqlite3.connect("matrix_system.db")
    cursor = conn.cursor()
    
    # 1. Deposits Transaction Registry Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference TEXT UNIQUE NOT NULL,
            telegram_id INTEGER NOT NULL,
            amount REAL NOT NULL,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # 2. General Global System Metadata Properties Engine Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS system_metadata (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    
    # 3. Inject Initial Asset Balance Ledger Fallbacks if empty
    allocation_keys = [
        'PERSONAL_UPKEEP', 'CRYPTO_ARBITRAGE', 'FOREX_RESERVE', 
        'STOCKS_EQUITIES', 'COMMODITIES_GOLD', 'ALT_MARKETS', 'SPORTS_BETTING'
    ]
    for key in allocation_keys:
        cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES (?, '0.0')", (key,))
        
    # 4. Inject Initial Matrix Allocation Configuration Percentages
    cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES ('split_PERSONAL_UPKEEP', '0.20')")
    cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES ('split_CRYPTO_ARBITRAGE', '0.20')")
    cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES ('split_FOREX_RESERVE', '0.20')")
    cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES ('split_STOCKS_EQUITIES', '0.15')")
    cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES ('split_COMMODITIES_GOLD', '0.10')")
    cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES ('split_ALT_MARKETS', '0.10')")
    cursor.execute("INSERT OR IGNORE INTO system_metadata (key, value) VALUES ('split_SPORTS_BETTING', '0.05')")

    conn.commit()
    conn.close()
    print("💾 [DATABASE CORE] Advanced dynamic tuning tables seeded successfully.")

def update_settlement_account(bank_name, account_number, account_name):
    """
    Dynamically stores or updates the active Paystack payout bank account 
    details in your local infrastructure records.
    """
    conn = sqlite3.connect("matrix_system.db")
    cursor = conn.cursor()
    
    cursor.execute("INSERT OR REPLACE INTO system_metadata (key, value) VALUES ('settlement_bank', ?)", (bank_name,))
    cursor.execute("INSERT OR REPLACE INTO system_metadata (key, value) VALUES ('settlement_account_no', ?)", (account_number,))
    cursor.execute("INSERT OR REPLACE INTO system_metadata (key, value) VALUES ('settlement_account_name', ?)", (account_name,))
    
    conn.commit()
    conn.close()

def get_settlement_account():
    """Retrieves the synced bank metadata profiles from memory."""
    conn = sqlite3.connect("matrix_system.db")
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT value FROM system_metadata WHERE key = 'settlement_bank'")
        bank = cursor.fetchone()
        cursor.execute("SELECT value FROM system_metadata WHERE key = 'settlement_account_no'")
        acc_no = cursor.fetchone()
        cursor.execute("SELECT value FROM system_metadata WHERE key = 'settlement_account_name'")
        name = cursor.fetchone()
        
        return {
            "bank": bank[0] if bank else "Not Synced",
            "account_number": acc_no[0] if acc_no else "—",
            "account_name": name[0] if name else "—"
        }
    except Exception:
        return {"bank": "Not Synced", "account_number": "—", "account_name": "—"}
    finally:
        conn.close()

def record_deposit(reference, telegram_id, amount):
    """
    Registers a new inbound credit event and safely scales the capital 
    across allocation vectors using your custom split parameters.
    """
    conn = sqlite3.connect("matrix_system.db")
    cursor = conn.cursor()
    try:
        # Check if reference has already been executed to prevent double spending
        cursor.execute("SELECT 1 FROM deposits WHERE reference = ?", (reference,))
        if cursor.fetchone():
            return False
            
        # Log Transaction
        cursor.execute("INSERT INTO deposits (reference, telegram_id, amount) VALUES (?, ?, ?)", (reference, telegram_id, amount))
        
        # Pull Active Multipliers Configuration Splits
        keys = ['PERSONAL_UPKEEP', 'CRYPTO_ARBITRAGE', 'FOREX_RESERVE', 'STOCKS_EQUITIES', 'COMMODITIES_GOLD', 'ALT_MARKETS', 'SPORTS_BETTING']
        splits = {}
        for k in keys:
            cursor.execute("SELECT value FROM system_metadata WHERE key = ?", (f"split_{k}",))
            row = cursor.fetchone()
            splits[k] = float(row[0]) if row else 0.0
            
        # Scale Balance Allocations Live
        for k in keys:
            cursor.execute("SELECT value FROM system_metadata WHERE key = ?", (k,))
            current_row = cursor.fetchone()
            current_bal = float(current_row[0]) if current_row else 0.0
            
            new_bal = current_bal + (amount * splits[k])
            cursor.execute("INSERT OR REPLACE INTO system_metadata (key, value) VALUES (?, ?)", (k, str(new_bal)))
            
        conn.commit()
        return True
    except Exception as e:
        print(f"❌ Critical Database Error processing deposit event: {e}")
        return False
    finally:
        conn.close()

def get_ledger_metrics():
    """Retrieves standard ledger metric lists for basic Telegram interfaces."""
    conn = sqlite3.connect("matrix_system.db")
    cursor = conn.cursor()
    keys = ['PERSONAL_UPKEEP', 'CRYPTO_ARBITRAGE', 'FOREX_RESERVE', 'STOCKS_EQUITIES', 'COMMODITIES_GOLD', 'ALT_MARKETS', 'SPORTS_BETTING']
    balances = {}
    for k in keys:
        cursor.execute("SELECT value FROM system_metadata WHERE key = ?", (k,))
        row = cursor.fetchone()
        balances[k] = float(row[0]) if row else 0.0
    conn.close()
    return balances

def update_tuning_matrix(new_matrix):
    """Saves updated percentage distribution rules into storage tables."""
    conn = sqlite3.connect("matrix_system.db")
    cursor = conn.cursor()
    try:
        keys = ['PERSONAL_UPKEEP', 'CRYPTO_ARBITRAGE', 'FOREX_RESERVE', 'STOCKS_EQUITIES', 'COMMODITIES_GOLD', 'ALT_MARKETS', 'SPORTS_BETTING']
        for idx, k in enumerate(keys):
            new_split_val = new_matrix[k][idx]
            cursor.execute("INSERT OR REPLACE INTO system_metadata (key, value) VALUES (?, ?)", (f"split_{k}", str(new_split_val)))
        conn.commit()
        return True
    except Exception:
        return False
    finally:
        conn.close()

def get_comprehensive_performance_metrics():
    """
    Processes real-time transaction history aggregates, investment asset pools, 
    and systemic connectivity states for Web Display parsing frameworks.
    """
    conn = sqlite3.connect("matrix_system.db")
    cursor = conn.cursor()
    metrics = {}
    
    try:
        # 1. Pull current allocation levels
        cursor.execute("SELECT key, value FROM system_metadata")
        rows = cursor.fetchall()
        meta_dict = {r[0]: r[1] for r in rows}
        
        allocation_keys = ['PERSONAL_UPKEEP', 'CRYPTO_ARBITRAGE', 'FOREX_RESERVE', 'STOCKS_EQUITIES', 'COMMODITIES_GOLD', 'ALT_MARKETS', 'SPORTS_BETTING']
        total_allocated_capital = sum(float(meta_dict.get(k, 0.0)) for k in allocation_keys)
        
        # 2. Extract Processing Volume Totals from Historical Deposits
        cursor.execute("SELECT COUNT(*), SUM(amount) FROM deposits")
        deposit_stats = cursor.fetchone()
        total_deposit_count = deposit_stats[0] if deposit_stats and deposit_stats[0] else 0
        total_volume_processed = deposit_stats[1] if deposit_stats and deposit_stats[1] else 0.0

        metrics = {
            "financial_summary": {
                "gross_volume_processed_ngn": total_volume_processed,
                "total_successful_deposits": total_deposit_count,
                "active_matrix_allocation_pool_ngn": total_allocated_capital,
                "average_ticket_size_ngn": (total_volume_processed / total_deposit_count) if total_deposit_count > 0 else 0.0
            },
            "portfolio_matrix_breakdown": {k: float(meta_dict.get(k, 0.0)) for k in allocation_keys},
            "infrastructure_telemetry": {
                "database_health": "OPTIMAL",
                "storage_sync_state": "CONNECTED" if "settlement_bank" in meta_dict else "PENDING_INITIALIZATION"
            }
        }
    except Exception as e:
        metrics = {
            "status": "ERROR",
            "reason": str(e),
            "financial_summary": {"gross_volume_processed_ngn": 0.0, "total_successful_deposits": 0, "active_matrix_allocation_pool_ngn": 0.0, "average_ticket_size_ngn": 0.0},
            "portfolio_matrix_breakdown": {},
            "infrastructure_telemetry": {"database_health": "CRITICAL_FAULT", "storage_sync_state": "ERROR"}
        }
    finally:
        conn.close()
        
    return metrics
