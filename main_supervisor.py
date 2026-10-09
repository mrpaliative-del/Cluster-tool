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

# Grab configurations securely
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://cluster-tool-1.onrender.com")

bot = telebot.TeleBot(TOKEN, threaded=False) # Turned off multi-threading to prevent memory conflicts
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "online", "mode": "zero_budget_mesh", "timestamp": time.time()}

# --- 1. Telegram Webhook Receiver Intake Endpoint ---
@app.post(f"/tg-webhook/{TOKEN}")
async def telegram_webhook_router(request: Request):
    """ Processes incoming Telegram updates directly using Render's web traffic port """
    json_string = await request.json()
    update = Update.de_json(json_string)
    bot.process_new_updates([update])
    return {"status": "ok"}

# --- 2. Paystack Webhook Handler ---
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
                print(f"⚠️ Telegram webhook alert error: {e}")
            
    return {"status": "success"}

# --- 3. Telegram UI Command Matrix ---
@bot.message_handler(commands=['start', 'dashboard'])
def send_welcome(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 View Yields", callback_data="get_yields"),
        InlineKeyboardButton("💳 Add Funds", callback_data="add_funds")
    )
    bot.reply_to(message, "🤖 *Arbitrage System Active.*\nSelect an option to interact with the global scanning grid:", reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    if call.data == "get_yields":
        bot.send_message(call.message.chat.id, "📈 *Performance Output:*\nToday's Yield: `+1.42%` \nTotal Vault Balance: `₦42,500.00`", parse_mode="Markdown")
    elif call.data == "add_funds":
        pay_url = f"https://paystack.com{{\\\"telegram_id\\\":{call.from_user.id}}}"
        bot.send_message(call.message.chat.id, f"💳 Click [here]({pay_url}) to securely deposit funds via Paystack.", parse_mode="Markdown")
    bot.answer_callback_query(call.id)

# --- 4. System Subprocess Lifecycles ---
def run_java_execution_engine():
    print("☕ [THREAD] Launching High-Speed Java Execution Block off-heap...")
    subprocess.run(["java", "-Xmx256m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    print("🚀 [THREAD] Activating Multi-Second Scanners and Keep-Awake Workarounds...")
    import keep_alive
    import asyncio
    asyncio.run(keep_alive.start_parallel_loops())

def setup_webhook_routing():
    """ Registers your live Render URL securely inside Telegram's routing engines """
    time.sleep(3) # Short buffer allowing the primary web server to initialize completely
    webhook_url = f"{RENDER_URL}/tg-webhook/{TOKEN}"
    print(f"🌐 [WEBHOOK] Synchronizing pipeline routing address: {webhook_url}")
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)

if __name__ == "__main__":
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()
    threading.Thread(target=setup_webhook_routing, daemon=True).start()

    # Bind directly to Render's exposed environment port allocation
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
