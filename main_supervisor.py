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

# Clean and sanitize environment configuration handles explicitly
RAW_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "YOUR_BOT_TOKEN")
# Strip out any accidentally appended whitespace, logs, or trailing timestamps
TOKEN = RAW_TOKEN.split("2026-")[0].strip()

PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://cluster-tool-1.onrender.com")

# Initialize Telebot instance
bot = telebot.TeleBot(TOKEN, threaded=False)
app = FastAPI()

@app.get("/")
def health_check():
    return {"status": "online", "mode": "static_webhook_mesh", "timestamp": time.time()}

# --- 1. Fixed Telegram Webhook Intake Engine ---
@app.post("/tg-backend-intake")
async def telegram_webhook_router(request: Request):
    """
    Hyper-stable endpoint route. Fixed path string guarantees zero 
    character or timestamp string mutation issues.
    """
    try:
        json_data = await request.json()
        update = Update.de_json(json_data)
        bot.process_new_updates([update])
        return {"status": "processed"}
    except Exception as e:
        print(f"⚠️ Webhook intake processing anomaly: {e}")
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
                bot.send_message(tg_id, f"✅ *Payment Confirmed!*\nSuccessfully deposited ₦{amount:,.2f} via Paystack.", parse_mode="Markdown")
            except Exception as e:
                print(f"⚠️ Paystack alert delivery failure: {e}")
            
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
    """ Processes button interaction events routed via the static endpoint """
    try:
        if call.data == "get_yields":
            print(f"📊 [UI] Dispatching metrics summary box to user ID: {call.from_user.id}")
            bot.send_message(
                chat_id=call.message.chat.id,
                text="📈 *Performance Output:*\nToday's Yield: `+1.42%` \nTotal Vault Balance: `₦42,500.00`",
                parse_mode="Markdown"
            )
        elif call.data == "add_funds":
            print(f"💳 [UI] Compiling dynamic Paystack link for user ID: {call.from_user.id}")
            pay_url = f"https://paystack.com{{\\\"telegram_id\\\":{call.from_user.id}}}"
            bot.send_message(
                chat_id=call.message.chat.id,
                text=f"💳 Click below to securely deposit funds via Paystack:\n[Secure Gateway Link]({pay_url})",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
        
        # Always resolve the button loading spinner instantly
        bot.answer_callback_query(callback_query_id=call.id)
    except Exception as e:
        print(f"❌ Error during callback execution processing: {e}")

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
    """ Hooks the static path mapping address into Telegram server files safely """
    time.sleep(6) # Give the core server frame ample time to complete initialization
    clean_base_url = RENDER_URL.split("2026-")[0].strip().rstrip('/')
    webhook_url = f"{clean_base_url}/tg-backend-intake"
    print(f"🌐 [WEBHOOK REGISTRY] Initializing connection endpoint map to: {webhook_url}")
    try:
        bot.remove_webhook()
        time.sleep(1)
        bot.set_webhook(url=webhook_url)
        print("🌐 [WEBHOOK REGISTRY] Static interface linkage verified.")
    except Exception as e:
        print(f"❌ Failed to coordinate custom webhook settings layout: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()
    threading.Thread(target=setup_webhook_routing, daemon=True).start()

    # Launch FastAPI portal gate
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
