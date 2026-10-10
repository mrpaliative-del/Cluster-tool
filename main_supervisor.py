import os
import uvicorn
import hmac
import hashlib
import telebot
import asyncio
import requests
import time
import urllib.parse
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import HTMLResponse
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
from contextlib import asynccontextmanager
import database

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A").strip()
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://onrender.com").strip().rstrip('/')

BROKER_API_URL = os.getenv("BROKER_API_URL", "https://yourbroker.com")
BROKER_TOKEN = os.getenv("BROKER_API_TOKEN", "mock_secure_token_xxxx")
LOT_SIZE = 0.1

bot = telebot.TeleBot(TOKEN, threaded=False)

# Track execution alerts for infrastructure performance telemetry metrics
ALERT_COUNTER = 0
LAST_ALERT_TIME = "N/A"

def sync_paystack_settlement_profile():
    """Queries Paystack Business metrics profile parameters to cache local settlement metadata."""
    secret_key = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").strip()
    headers = {"Authorization": f"Bearer {secret_key}"}
    try:
        profile_res = requests.get("https://paystack.co", headers=headers, timeout=10)
        if profile_res.status_code == 200:
            biz_data = profile_res.json().get("data", {})
            bank_name = biz_data.get("settlement_bank", "Unknown Bank")
            account_no = biz_data.get("settlement_account_number", "—")
            account_name = biz_data.get("settlement_account_name", "Mpee global ventures")
            database.update_settlement_account(bank_name, account_no, account_name)
            print(f"💾 Settlement profile updated dynamically: {bank_name} ({account_no})")
    except Exception as e:
        print(f"⚠️ Automated bank settlement profile sync error: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    # 💾 Keep core database seeding on the main path
    database.init_db()
    
    # ⚡ Run the synchronous Paystack API request in a background thread
    # This prevents the network call from blocking Render's health check handshakes
    loop = asyncio.get_event_loop()
    asyncio.ensure_future(loop.run_in_executor(None, sync_paystack_settlement_profile))
    
    await asyncio.sleep(2)
    webhook_url = f"{RENDER_URL}/tg-backend-intake"
    print(f"🌐 Linking Webhook Pipeline to: {webhook_url}")
    
    # Resilient Retry Engine to bypass Telegram 429 Rate Limits
    for attempt in range(1, 6):
        try:
            bot.remove_webhook()
            await asyncio.sleep(2)
            bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
            print("🌐 Webhook linkage active and running!")
            break
        except Exception as e:
            print(f"⚠️ Webhook linkage attempt {attempt}/5 failed: {e}")
            await asyncio.sleep(attempt * 3)
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def operations_web_dashboard(): 
    """
    Compiles and renders a beautiful, accessible real-time web operational dashboard
    displaying systemic performance metrics and transaction velocities.
    """
    perf = database.get_comprehensive_performance_metrics()
    summary = perf.get("financial_summary", {})
    matrix = perf.get("portfolio_matrix_breakdown", {})
    infra = perf.get("infrastructure_telemetry", {})
    
    html_content = f"""
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Mpee Global Ventures - Matrix Ops Board</title>
        <style>
            body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background: #0f172a; color: #f8fafc; margin: 0; padding: 24px; }}
            .container {{ max-width: 1200px; margin: 0 auto; }}
            .header {{ display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #334155; padding-bottom: 16px; margin-bottom: 24px; }}
            h1, h2 {{ margin: 0; color: #38bdf8; }}
            .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; margin-bottom: 24px; }}
            .card {{ background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }}
            .card-title {{ font-size: 14px; text-transform: uppercase; letter-spacing: 0.05em; color: #94a3b8; margin-bottom: 8px; }}
            .card-value {{ font-size: 28px; font-weight: bold; color: #f1f5f9; }}
            .matrix-list {{ list-style: none; padding: 0; margin: 0; }}
            .matrix-item {{ display: flex; justify-content: space-between; border-bottom: 1px solid #334155; padding: 10px 0; font-size: 14px; }}
            .matrix-item:last-child {{ border: none; }}
            .status-badge {{ background: #10b981; color: white; padding: 4px 8px; border-radius: 6px; font-size: 12px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <div>
                    <h1>Mpee Global Ventures</h1>
                    <div style="color: #94a3b8; font-size: 14px; margin-top: 4px;">Automated Allocation Matrix Ops Control Center</div>
                </div>
                <span class="status-badge">ENGINE ONLINE</span>
            </div>
            
            <h2>📊 Operational Financial Performance</h2>
            <div class="grid" style="margin-top: 12px;">
                <div class="card">
                    <div class="card-title">Gross Volume Processed</div>
                    <div class="card-value">₦{summary.get('gross_volume_processed_ngn', 0.0):,.2f}</div>
                </div>
                <div class="card">
                    <div class="card-title">Active Matrix Liquidity Pool</div>
                    <div class="card-value">₦{summary.get('active_matrix_allocation_pool_ngn', 0.0):,.2f}</div>
                </div>
                <div class="card">
                    <div class="card-title">Successful Deposits</div>
                    <div class="card-value">{summary.get('total_successful_deposits', 0)} Transactions</div>
                </div>
            </div>

            <div class="grid" style="grid-template-columns: 2fr 1fr;">
                <div class="card">
                    <h2>🗂️ Asset Class Allocation Balances</h2>
                    <div class="matrix-list" style="margin-top: 12px;">
                        <div class="matrix-item"><span>💳 Personal Upkeep (20%)</span><strong>₦{matrix.get('PERSONAL_UPKEEP', 0.0):,.2f}</strong></div>
                        <div class="matrix-item"><span>🤖 Crypto Arbitrage Core (20%)</span><strong>₦{matrix.get('CRYPTO_ARBITRAGE', 0.0):,.2f}</strong></div>
                        <div class="matrix-item"><span>💱 Forex Allocation Vault (20%)</span><strong>₦{matrix.get('FOREX_RESERVE', 0.0):,.2f}</strong></div>
                        <div class="matrix-item"><span>📈 Stocks & Equities (15%)</span><strong>₦{matrix.get('STOCKS_EQUITIES', 0.0):,.2f}</strong></div>
                        <div class="matrix-item"><span>✨ Commodities & Gold (10%)</span><strong>₦{matrix.get('COMMODITIES_GOLD', 0.0):,.2f}</strong></div>
                        <div class="matrix-item"><span>📊 Alternative Markets (10%)</span><strong>₦{matrix.get('ALT_MARKETS', 0.0):,.2f}</strong></div>
                        <div class="matrix-item"><span>⚽ Sports Betting Vault (5%)</span><strong>₦{matrix.get('SPORTS_BETTING', 0.0):,.2f}</strong></div>
                    </div>
                </div>
                
                <div class="card">
                    <h2>⚡ System Telemetry</h2>
                    <div class="matrix-list" style="margin-top: 12px;">
                        <div class="matrix-item"><span>Database Node</span><span style="color: #10b981; font-weight: bold;">{infra.get('database_health')}</span></div>
                        <div class="matrix-item"><span>Paystack Profile Sync</span><span style="color: #38bdf8; font-weight: bold;">{infra.get('storage_sync_state')}</span></div>
                        <div class="matrix-item"><span>TV Alerts Executed</span><strong>{ALERT_COUNTER}</strong></div>
                        <div class="matrix-item"><span>Last Signal Frame</span><span style="font-family: monospace; font-size: 12px;">{LAST_ALERT_TIME}</span></div>
                    </div>
                </div>
            </div>
        </div>
    </body>
    </html>
    """
    return HTMLResponse(content=html_content, status_code=200)

@app.head("/")
async def home_mesh_head():
    return Response(status_code=200)

@app.get("/health")
def engine_health_check(): 
    return {"status": "ok"}

@app.get("/portfolio-status")
def get_portfolio_status():
    """Exposes structured metric trees for external tooling intakes."""
    return database.get_comprehensive_performance_metrics()

@app.post("/tradingview-alert")
async def tradingview_alert_receiver(request: Request):
    global ALERT_COUNTER, LAST_ALERT_TIME
    try:
        payload = await request.json()
        action = payload.get("action")
        ticker = payload.get("ticker")
        price = payload.get("close_price")
        
        ALERT_COUNTER += 1
        LAST_ALERT_TIME = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())
        
        balances = database.get_ledger_metrics()
        fx_capital = balances.get("FOREX_RESERVE", 0.0)
        if fx_capital <= 0:
            return {"status": "ignored", "reason": "zero_capital"}
            
        if BROKER_TOKEN != "mock_secure_token_xxxx":
            broker_payload = {
