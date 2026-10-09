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

# Grab configurations securely from Render Environment panel
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://onrender.com")

# Initialize Telebot without multi-threaded polling handlers
bot = telebot.TeleBot(TOKEN, threaded=False)
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "online", "mode": "production_webhook_mesh", "timestamp": time.time()}

# --- 1. Telegram Webhook Intake Engine ---
@app.post(f"/tg-webhook/{TOKEN}")
async def telegram_webhook_router(request: Request):
    """
    Receives all real-time events (text, button presses) from Telegram's 
    servers and forces Python to process them immediately.
    """
    try:
        json_data = await request.json()
        # Decode raw payload straight into a structured Telebot object
        update = Update.de_json(json_data)
        
        # CRITICAL FIX: Explicitly tell your bot instance to process this update string
        bot.process_new_updates([update])
        return {"status": "processed"}
    except Exception as e:
        print(f"⚠️ Webhook processing anomaly: {e}")
        return {"status": "error", "detail": str(e)}

# --- 2. Paystack Financial Webhook ---
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
                print(f"⚠️ Paystack Telegram alert delivery failure: {e}")
            
    return {"status": "success"}

# --- 3. Telegram UI Component Logic ---
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
    """ Processes the button clicks passed via the FastAPI intake valve """
    try:
        if call.data == "get_yields":
            bot.send_message(
                chat_id=call.message.chat.id,
                text="📈 *Performance Output:*\nToday's Yield: `+1.42%` \nTotal Vault Balance: `₦42,500.00`",
                parse_mode="Markdown"
            )
        elif call.data == "add_funds":
            pay_url = f"https://paystack.com{{\\\"telegram_id\\\":{call.from_user.id}}}"
            bot.send_message(
                chat_id=call.message.chat.id,
                text=f"💳 Click [here]({pay_url}) to securely deposit funds via Paystack.",
                parse_mode="Markdown"
            )
        
        # Always answer the callback query to stop the loading spinner on the button
        bot.answer_callback_query(call.id)
    except Exception as e:
        print(f"⚠️ Error inside callback query handler: {e}")

# --- 4. System Subprocesses ---
def run_java_execution_engine():
    print("☕ [THREAD] Launching High-Speed Java Execution Block off-heap...")
    subprocess.run(["java", "-Xmx256m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    print("🚀 [THREAD] Activating Multi-Second Scanners and Keep-Awake Workarounds...")
    import keep_alive
    import asyncio
    asyncio.run(keep_alive.start_parallel_loops())

def setup_webhook_routing():
    """ Safely links Telegram's core events directly to your Render URL """
    time.sleep(5) # Give the web server plenty of time to boot up first
    webhook_url = f"{RENDER_URL}/tg-webhook/{TOKEN}"
    print(f"🌐 [WEBHOOK CONNECTION] Synchronizing endpoint URL: {webhook_url}")
    try:
        bot.remove_webhook()
        # Points Telegram explicitly to our special webhook endpoint path
        bot.set_webhook(url=webhook_url)
        print("🌐 [WEBHOOK CONNECTION] Synchronization completed successfully.")
    except Exception as e:
        print(f"❌ Failed to set webhook routing line: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()
    threading.Thread(target=setup_webhook_routing, daemon=True).start()

    # Launch FastAPI on Render's required environment port assignment
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
