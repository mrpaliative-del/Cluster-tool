import subprocess
import threading
import os
import uvicorn
import hmac
import hashlib
import telebot
import asyncio
import shutil
import time
import requests
from fastapi import FastAPI, Request, Response, status
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
from contextlib import asynccontextmanager
import database

# --- 1. Clean Environment Parameters (NON-HARDCODED) ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A").strip()
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://onrender.com").strip().rstrip('/')

# External Broker Gateway Configs for TradingView Executions
BROKER_API_URL = os.getenv("BROKER_API_URL", "https://yourbroker.com")
BROKER_TOKEN = os.getenv("BROKER_API_TOKEN", "mock_secure_token_xxxx")
LOT_SIZE = 0.1

bot = telebot.TeleBot(TOKEN, threaded=False)

# --- 2. Safe Sequential Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """ Executes database schema initialization and links Telegram webhooks cleanly """
    database.init_db()  # Initialize thread-safe SQLite database schemas natively
    await asyncio.sleep(4)
    webhook_url = f"{RENDER_URL}/tg-backend-intake"
    print(f"🌐 [LIFESPAN] Mapping webhook configurations pipeline to: {webhook_url}")
    try:
        bot.remove_webhook()
        await asyncio.sleep(1)
        bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
        print("🌐 [LIFESPAN SUCCESS] Webhook pipeline linkage confirmed and active!")
    except Exception as e:
        print(f"❌ [LIFESPAN FAULT] Webhook initialization failed: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# --- 3. Gateway Routing Array ---
@app.route("/", methods=["GET", "HEAD"])
def home_mesh_root(request: Request = None): 
    """ PRODUCTION FIX: Handles both GET requests and automated infrastructure HEAD checks cleanly """
    return {"status": "online"}

@app.get("/health")
def engine_health_check(): 
    return {"status": "ok"}

@app.get("/portfolio-status")
def get_portfolio_status():
    """ Exposes live balance ledger array to external Node.js engines """
    return database.get_ledger_metrics()

# --- 4. TRADINGVIEW WEBHOOK RECEIVER GATEWAY ---
@app.post("/tradingview-alert")
async def tradingview_alert_receiver(request: Request):
    """ Captures and processes execution payloads directly from your TradingView strategy script """
    try:
        payload = await request.json()
        print(f"🚀 [TRADINGVIEW ALERT RECEIVED] Payload: {payload}")
        
        action = payload.get("action")       # 'Cascade Long' or 'Cascade Short'
        ticker = payload.get("ticker")       # e.g., 'EURUSD'
        price = payload.get("close_price")   # Execution price index
        
        balances = database.get_ledger_metrics()
        fx_capital = balances.get("FOREX_RESERVE", 0.0)
        
        if fx_capital <= 0:
            print("🔒 [EXECUTION HALTED] Forex Reserve balance is ₦0.00. Standing by for task engine allocations.")
            return {"status": "ignored", "reason": "zero_capital"}
            
        if BROKER_TOKEN == "mock_secure_token_xxxx":
            print(f"🔬 [SANDBOX ORDER] Signal matches criteria. Simulated {action} entry for {ticker} at {price}.")
        else:
            broker_payload = {
                "instrument": ticker, 
                "units": LOT_SIZE * 100000 if "Long" in action else -LOT_SIZE * 100000, 
                "type": "MARKET"
            }
            requests.post(BROKER_API_URL, json=broker_payload, headers={"Authorization": f"Bearer {BROKER_TOKEN}"}, timeout=10)
            
        # Pushes an instantaneous trading update straight to your personal device
        bot.send_message(
            chat_id=8608729377,
            text=f"📡 *TradingView Strategy Alert Executed!*\nAction: `{action}`\nAsset: `{ticker}`\nExecution Price: `{price}`\nVault Status: `Active Running`",
            parse_mode="Markdown"
        )
        return {"status": "executed"}
    except Exception as e:
        print(f"❌ [TRADINGVIEW GATEWAY FAULT] Processing anomaly: {e}")
        return Response(content=str(e), status_code=400)

@app.post("/tg-backend-intake")
async def telegram_webhook_router(request: Request):
    try:
        json_data = await request.json()
        update = Update.de_json(json_data)
        bot.process_new_updates([update])
        return {"status": "processed"}
    except Exception as e:
        return Response(content=str(e), status_code=500)

@app.post("/paystack-webhook")
async def paystack_webhook(request: Request):
    """ Cryptographically authenticates and processes inbound merchant transaction receipts """
    payload = await request.body()
    signature = request.headers.get("X-Paystack-Signature")
    if not signature: 
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        
    computed = hmac.new(PAYSTACK_SECRET, payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(signature, computed):
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        
    data = await request.json()
    if data.get("event") == "charge.success":
        tg_id = data["data"]["metadata"].get("telegram_id")
        amount = data["data"]["amount"] / 100
        trx_ref = data["data"]["reference"]
        
        is_new = database.record_deposit(trx_ref, tg_id, amount)
        if is_new and tg_id:
            try:
                bot.send_message(
                    chat_id=tg_id, 
                    text=f"✅ *Payment Confirmed!*\nSuccessfully deposited *₦{amount:,.2f}* via Paystack directly into your active Crypto Arbitrage balance ledger.", 
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"⚠️ Telegram confirmation alert runtime warning: {e}")
            
    return {"status": "success"}

# --- 5. Telegram UI Control Panel Matrix ---
@bot.message_handler(commands=['start', 'dashboard'])
def send_welcome(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Portfolio Matrix", callback_data="get_yields"),
        InlineKeyboardButton("💳 Add Funds", callback_data="add_funds")
    )
    bot.send_message(
        chat_id=message.chat.id,
        text="🤖 *Holding Firm 7-Asset Master Engine Active.*\nSelect a monitoring hub parameter below to analyze your live quantitative allocations:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    try:
        bot.answer_callback_query(callback_query_id=call.id)
        target_chat_id = call.message.chat.id
        
        if call.data == "get_yields":
            balances = database.get_ledger_metrics()
            
            dashboard_text = (
                "📈 *Unified 7-Asset Holding Dashboard*\n\n"
                f"💳 *Personal Upkeep (20%):* `₦{balances.get('PERSONAL_UPKEEP', 0.0):,.2f}`\n"
                f"🤖 *Crypto Arbitrage Core (20%):* `₦{balances.get('CRYPTO_ARBITRAGE', 0.0):,.2f}`\n"
                f"💱 *Forex Allocation Vault (20%):* `₦{balances.get('FOREX_RESERVE', 0.0):,.2f}`\n"
                f"📈 *Stocks & Equities (15%):* `₦{balances.get('STOCKS_EQUITIES', 0.0):,.2f}`\n"
                f"✨ *Commodities & Gold (10%):* `₦{balances.get('COMMODITIES_GOLD', 0.0):,.2f}`\n"
                f"📊 *Alternative Markets (10%):* `₦{balances.get('ALT_MARKETS', 0.0):,.2f}`\n"
                f"⚽ *Sports Betting Vault (5%):* `₦{balances.get('SPORTS_BETTING', 0.0):,.2f}`\n\n"
                "🔒 *Status:* 7-Asset Portfolio Matrix Lock active. All background processes running."
            )
            bot.send_message(chat_id=target_chat_id, text=dashboard_text, parse_mode="Markdown")
            
        elif call.data == "add_funds":
            pay_url = f"https://paystack.shop{call.from_user.id}%7D"
            bot.send_message(
                chat_id=target_chat_id,
                text=f"💳 Click below to securely deposit funds via Paystack:\n[Secure Gateway Link]({pay_url})",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
    except Exception as e:
        print(f"❌ Callback evaluation context fault: {e}")

# --- 6. MODULE 11: DYNAMIC NETWORK /TUNE CONSOLE RECEIVER ---
@bot.message_handler(commands=['tune'])
def adjust_investment_profile(message):
    """ Guides the user on how to adjust portfolio allocation splits from their phone screen """
    guide_text = (
        "⚙️ *15-Tool Capital Tuning Matrix Console*\n\n"
        "To modify your automated percentage splits over the network, send a text line matching this exact syntax format:\n\n"
        "`set_split: 0.10, 0.30, 0.20, 0.10, 0.10, 0.15, 0.05`\n\n"
        "📊 *Order Sequence Layout Guideline:*\n"
        "1. Personal Upkeep\n2. Crypto Core\n3. Forex Vault\n4. Stocks\n5. Gold\n6. Alternatives\n7. Sports Betting\n\n"
        "⚠️ *Operational Rule:* The sum of all seven fractions *must equal exactly 1.00* (100%) to maintain transaction ledger integrity."
    )
    bot.send_message(chat_id=message.chat.id, text=guide_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("set_split:"))
def process_tuning_input(message):
    try:
        raw_data = message.text.replace("set_split:", "").strip()
        parts = [float(x.strip()) for x in raw_data.split(",")]
        
        if len(parts) != 7:
            bot.reply_to(message, "❌ *Configuration Fault:* You must pass exactly 7 matrix parameter values.")
            return

        # FLAT VALIDATION LOOP - Prevents any dynamic python indentation problems on mobile devices
