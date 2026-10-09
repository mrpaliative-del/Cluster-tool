import subprocess
import threading
import os
import uvicorn
import hmac
import hashlib
import telebot
import time
from fastapi import FastAPI, Request, Response, status
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update

# Deep clean the credentials token input string directly using secure array parameters
RAW_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN").strip()

# Safeguard against logs or dynamic timestamp text appending onto the environment variable string
if "2026-" in RAW_TOKEN:
    TOKEN = RAW_TOKEN.split("2026-")[0].strip()
else:
    TOKEN = RAW_TOKEN

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://cluster-tool-1.onrender.com").strip().rstrip('/')

# Initialize Telebot object engine natively
bot = telebot.TeleBot(TOKEN, threaded=False)
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "online", "mode": "production_webhook_mesh", "timestamp": time.time()}

# --- 1. Fixed Telegram Webhook Ingestion Intake Endpoint ---
@app.post("/tg-backend-intake")
async def telegram_webhook_router(request: Request):
    """ Fixed static route removes dynamic string mutation issues permanently """
    try:
        json_data = await request.json()
        update = Update.de_json(json_data)
        bot.process_new_updates([update])
        return {"status": "processed"}
    except Exception as e:
        print(f"⚠️ Webhook data handler parsing error: {e}")
        return {"status": "error", "detail": str(e)}

# --- 2. Paystack Financial Webhook Portal ---
@app.post("/paystack-webhook")
async def paystack_webhook(request: Request):
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
        if tg_id:
            try:
                bot.send_message(tg_id, f"✅ *Payment Confirmed!*\nSuccessfully deposited ₦{amount:,.2f} via Paystack into your trading ledger.", parse_mode="Markdown")
            except Exception as e:
                print(f"⚠️ Paystack Telegram push connection alert dropped: {e}")
            
    return {"status": "success"}

# --- 3. Telegram UI Command Matrix ---
@bot.message_handler(commands=['start', 'dashboard'])
def send_welcome(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 View Yields", callback_data="get_yields"),
        InlineKeyboardButton("💳 Add Funds", callback_data="add_funds")
    )
    bot.send_message(
        chat_id=message.chat.id,
        text="🤖 *Arbitrage System Active.*\nSelect an option to interact with the global scanning grid:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    """ Handles interface actions passed down via the FastAPI intake endpoint link """
    try:
        # Resolve the loading spinner on the button instantly
        bot.answer_callback_query(callback_query_id=call.id)
        
        if call.data == "get_yields":
            print(f"📊 [UI] Dispatching metrics summary box to user ID: {call.from_user.id}")
            bot.send_message(
                chat_id=call.message.chat.id,
                text="📈 *Performance Output:*\nToday's Yield: `+1.42%` \nTotal Vault Balance: `₦42,500.00`",
                parse_mode="Markdown"
            )
        elif call.data == "add_funds":
            print(f"💳 [UI] Compiling dynamic Paystack token gateway link for user ID: {call.from_user.id}")
            pay_url = f"https://paystack.com{{\"telegram_id\":{call.from_user.id}}}"
            bot.send_message(
                chat_id=call.message.chat.id,
                text=f"💳 Click below to securely deposit funds via Paystack:\n[Secure Gateway Link]({pay_url})",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
    except Exception as e:
        print(f"❌ Error during callback execution processing: {e}")

# --- 4. Subprocess Lifecycles ---
def run_java_execution_engine():
    print("☕ [THREAD] Launching High-Speed Java Execution Block off-heap...")
    subprocess.run(["java", "-Xmx256m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    print("🚀 [THREAD] Activating Multi-Second Scanners and Keep-Awake Workarounds...")
    import keep_alive
    import asyncio
    asyncio.run(keep_alive.start_parallel_loops())

def setup_webhook_routing():
    """ Registers the connection routing parameter explicitly with Telegram's servers """
    time.sleep(6)  # Safe buffer allowing the main framework container to spin up first
    webhook_url = f"{RENDER_URL}/tg-backend-intake"
    
    attempts = 0
    while attempts < 5:
        print(f"🌐 [WEBHOOK REGISTRY] Connection sync attempt #{attempts + 1} mapping to: {webhook_url}")
        try:
            bot.remove_webhook()
            time.sleep(2)
            success = bot.set_webhook(url=webhook_url)
            if success:
                print("🌐 [WEBHOOK REGISTRY] Webhook pipeline linkage confirmed and active!")
                return
        except telebot.apihelper.ApiTelegramException as e:
            if e.error_code == 429:
                print("⚠️ [429 Rate Limit] Telegram is busy. Retrying block link in 10 seconds...")
                time.sleep(10)
            else:
                print(f"❌ Telegram API exception: {e}")
                time.sleep(4)
        except Exception as e:
            print(f"❌ General network sync error: {e}")
            time.sleep(4)
        attempts += 1

if __name__ == "__main__":
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()
    threading.Thread(target=setup_webhook_routing, daemon=True).start()

    # Launch FastAPI portal server framework
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
