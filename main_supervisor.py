import subprocess
import threading
import os
import uvicorn
import hmac
import hashlib
import telebot
import time
from fastapi import FastAPI, Request, Response, status
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# Grab credentials from Render environment configs securely
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')

# Initialize components
bot = telebot.TeleBot(TOKEN)
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "online", "mode": "zero_budget_mesh", "timestamp": time.time()}

# --- 1. Paystack Webhook Handler ---
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
                print(f"⚠️ Failed to send Telegram alert via webhook loop: {e}")
            
    return {"status": "success"}

# --- 2. Telegram Bot Command Matrix ---
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

# --- 3. Isolated Background Execution Threads ---
def run_telegram_polling():
    print("💬 [THREAD] Telegram Interface Polling Engine is initiating...")
    try:
        bot.infinity_polling(timeout=10, long_polling_timeout=5)
    except Exception as e:
        print(f"❌ Telegram polling encountered an unhandled crash loop: {e}")

def run_java_execution_engine():
    print("☕ [THREAD] Launching High-Speed Java Execution Block off-heap...")
    # Bound Java memory space footprint explicitly to survive under free hosting limits
    subprocess.run(["java", "-Xmx256m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    print("🚀 [THREAD] Activating Multi-Second Scanners and Keep-Awake Workarounds...")
    import keep_alive
    import asyncio
    asyncio.run(keep_alive.start_parallel_loops())

# --- 4. Main Deployment Boot Orchestrator ---
if __name__ == "__main__":
    # Launch Java engine asynchronously 
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    
    # Launch Telegram bot listeners asynchronously 
    threading.Thread(target=run_telegram_polling, daemon=True).start()
    
    # Launch Keep-alive timer loops asynchronously
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()

    # Bind FastAPI to the final primary thread interface required by Render
    port = int(os.getenv("PORT", 10000))
    print(f"⚡ Master Web Gateway binding to deployment server port: {port}")
    uvicorn.run(app, host="0.0.0.0", port=port)
