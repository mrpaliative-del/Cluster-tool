import subprocess
import threading
import os
import uvicorn
import hmac
import hashlib
import telebot
import time
import httpx
from fastapi import FastAPI, Request, Response, status
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update

# Grab configurations securely from Render Environment panel
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://cluster-tool-1.onrender.com")

# Initialize Telebot without multi-threaded polling handlers
bot = telebot.TeleBot(TOKEN, threaded=False)
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "online", "mode": "production_webhook_mesh", "timestamp": time.time()}

# --- 1. Manual Force-Sync Recovery Endpoint ---
@app.get("/force-sync")
def force_sync_webhook():
    """
    Open this endpoint in your mobile browser to hardwire 
    the connection if Telegram stops responding.
    """
    webhook_url = f"{RENDER_URL}/tg-webhook/{TOKEN}"
    try:
        bot.remove_webhook()
        time.sleep(1)
        success = bot.set_webhook(url=webhook_url)
        if success:
            return {"status": "success", "message": f"Pipeline hardwired to: {webhook_url}"}
        return {"status": "failed", "message": "Telegram rejected the endpoint link configuration."}
    except Exception as e:
        return {"status": "error", "message": str(e)}

# --- 2. Telegram Webhook Intake Engine ---
@app.post(f"/tg-webhook/{TOKEN}")
async def telegram_webhook_router(request: Request):
    """ Receives all real-time events directly from Telegram """
    try:
        json_data = await request.json()
        update = Update.de_json(json_data)
        bot.process_new_updates([update])
        return {"status": "processed"}
    except Exception as e:
        print(f"⚠️ Webhook processing breakdown: {e}")
        return {"status": "error", "detail": str(e)}

# --- 3. Paystack Financial Webhook ---
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
                bot.send_message(tg_id, f"✅ *Payment Confirmed!*\nSuccessfully deposited ₦{amount:,.2f} via Paystack.", parse_mode="Markdown")
            except Exception as e:
                print(f"⚠️ Paystack alert delivery failure: {e}")
            
    return {"status": "success"}

# --- 4. Telegram UI Component Logic ---
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
    """ Main intake logic processing button callback events """
    try:
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
        # Inform Telegram the click was intercepted successfully
        bot.answer_callback_query(callback_query_id=call.id)
    except Exception as e:
        print(f"❌ Exception error occurred within button query loop: {e}")

# --- 5. System Subprocesses ---
def run_java_execution_engine():
    print("☕ [THREAD] Launching High-Speed Java Execution Block off-heap...")
    subprocess.run(["java", "-Xmx256m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    print("🚀 [THREAD] Activating Multi-Second Scanners and Keep-Awake Workarounds...")
    import keep_alive
    import asyncio
    asyncio.run(keep_alive.start_parallel_loops())

if __name__ == "__main__":
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()

    # Launch FastAPI portal gateway
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
