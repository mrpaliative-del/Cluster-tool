import subprocess
import threading
import os
import uvicorn
import hmac
import hashlib
import telebot
import asyncio
import json
import time
from fastapi import FastAPI, Request, Response, status
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
from contextlib import asynccontextmanager

# --- 1. Clean Environment Parameters ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A").strip()
# Swap SK_LIVE inside your Render Dashboard settings panel when pushing production live strings
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://onrender.com").strip().rstrip('/')
LEDGER_PATH = "ledger_store.json"

bot = telebot.TeleBot(TOKEN, threaded=False)

# --- 2. Safe Sequential Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """ Executes webhook link registrations after Uvicorn is bound cleanly """
    await asyncio.sleep(4)
    webhook_url = f"{RENDER_URL}/tg-backend-intake"
    print(f"🌐 [LIFESPAN] Registering webhook endpoint to: {webhook_url}")
    try:
        bot.remove_webhook()
        await asyncio.sleep(1)
        bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
        print("🌐 [LIFESPAN SUCCESS] Webhook pipeline linkage confirmed and active!")
    except Exception as e:
        print(f"❌ [LIFESPAN FAULT] Webhook setup failed: {e}")
    yield

app = FastAPI(lifespan=lifespan)

# --- 3. Gateway Routing Array ---
@app.get("/")
def home_mesh_root():
    return {"status": "online"}

@app.get("/health")
def engine_health_check():
    return {"status": "ok"}

@app.post("/tg-backend-intake")
async def telegram_webhook_router(request: Request):
    try:
        json_data = await request.json()
        update = Update.de_json(json_data)
        bot.process_new_updates([update])
        return {"status": "processed"}
    except Exception as e:
        print(f"⚠️ Webhook data handler parsing error: {e}")
        return Response(content=str(e), status_code=500)

@app.post("/paystack-webhook")
async def paystack_webhook(request: Request):
    """ SECURE MATRIX: Verifies inbound Paystack transaction alerts using SHA512 HMAC signatures """
    payload = await request.body()
    signature = request.headers.get("X-Paystack-Signature")
    
    if not signature:
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        
    computed = hmac.new(PAYSTACK_SECRET, payload, hashlib.sha512).hexdigest()
    if not hmac.compare_digest(signature, computed):
        print("⚠️ [SECURITY] Unauthorized Paystack signature hash collision dropped!")
        return Response(status_code=status.HTTP_401_UNAUTHORIZED)
        
    data = await request.json()
    if data.get("event") == "charge.success":
        tg_id = data["data"]["metadata"].get("telegram_id")
        amount = data["data"]["amount"] / 100 # Paystack counts transaction amounts in kobo
        
        print(f"💳 [PAYSTACK Webhook] Confirmed inbound capture of ₦{amount:,.2f} for User ID: {tg_id}")
        
        # Credit the balance directly into the shared file data models dynamically
        if os.path.exists(LEDGER_PATH):
            with open(LEDGER_PATH, "r+") as f:
                ledger = json.load(f)
                ledger["total_vault_balance"] += amount
                ledger["last_updated"] = time.time()
                f.seek(0)
                json.dump(ledger, f, indent=2)
                f.truncate()
        
        if tg_id:
            try:
                bot.send_message(tg_id, f"✅ *Payment Confirmed!*\nSuccessfully deposited *₦{amount:,.2f}* via Paystack directly into your active trading balance ledger.", parse_mode="Markdown")
            except Exception as e:
                print(f"⚠️ Paystack Telegram notification error: {e}")
            
    return {"status": "success"}

# --- 4. Telegram UI Command Matrix ---
@bot.message_handler(commands=['start', 'dashboard'])
def send_welcome(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 View Yields", callback_data="get_yields"),
        InlineKeyboardButton("💳 Add Funds", callback_data="add_funds")
    )
    bot.send_message(
        chat_id=message.chat.id,
        text="🤖 *Arbitrage Core Engine Active.*\nSelect an operational parameters lane below to scan live liquidity matrices:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    """ Evaluates real-time values from the dynamic json ledger file models """
    try:
        bot.answer_callback_query(callback_query_id=call.id)
        target_chat_id = call.message.chat.id
        
        # Load the latest values computed by your Java and Playwright modules
        vault_bal, current_yield = 42500.00, 1.42
        if os.path.exists(LEDGER_PATH):
            with open(LEDGER_PATH, "r") as f:
                ledger_data = json.load(f)
                vault_bal = ledger_data.get("total_vault_balance", 42500.00)
                current_yield = ledger_data.get("today_yield", 1.42)

        if call.data == "get_yields":
            bot.send_message(
                chat_id=target_chat_id,
                text=f"📈 *Live Performance Output:*\nToday's Yield: `+{current_yield}%` \nTotal Vault Balance: `₦{vault_bal:,.2f}`",
                parse_mode="Markdown"
            )
        elif call.data == "add_funds":
            # Dynamic link generator passes the user's Telegram ID straight to Paystack metadata parameters
            pay_url = f"https://paystack.com{call.from_user.id}%7D"
            bot.send_message(
                chat_id=target_chat_id,
                text=f"💳 Click below to securely deposit funds via Paystack:\n[Secure Gateway Link]({pay_url})",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
    except Exception as e:
        print(f"❌ Error during callback execution processing: {e}")

# --- 5. Clean Process Spawning Core ---
def run_java_execution_engine():
    print("☕ [THREAD] Spawning background Java Hot-Path Subprocess...")
    subprocess.Popen(["java", "-Xmx192m", "-jar", "engine.jar"])

def run_playwright_scraper_engine():
    print("🕷️ [THREAD] Spawning background Playwright Web Extraction Subprocess...")
    subprocess.Popen(["python", "scraper_engine.py"])

def run_keep_alive_loops():
    import keep_alive
    asyncio.run(keep_alive.start_parallel_loops())

if __name__ == "__main__":
    # Launch concurrent infrastructure threads cleanly alongside primary context
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_playwright_scraper_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()

    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
