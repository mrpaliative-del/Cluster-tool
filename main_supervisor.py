import subprocess
import threading
import os
import uvicorn
import hmac
import hashlib
import telebot
import asyncio
from fastapi import FastAPI, Request, Response, status
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
from contextlib import asynccontextmanager

# --- 1. Clean Environment Parameters ---
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A").strip()
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://cluster-tool-1.onrender.com").strip().rstrip('/')

# Initialize single-threaded Telebot instance natively
bot = telebot.TeleBot(TOKEN, threaded=False)

# --- 2. Non-Blocking Lifespan Architecture ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """ Executes webhook link registrations after Uvicorn is bound cleanly """
    # Let the server clear routing cache pools first
    await asyncio.sleep(4)
    
    webhook_url = f"{RENDER_URL}/tg-backend-intake"
    print(f"🌐 [LIFESPAN] Registering webhook endpoint to: {webhook_url}")
    
    try:
        bot.remove_webhook()
        await asyncio.sleep(1)
        # Register both inbound text strings and interface button callbacks explicitly
        success = bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
        if success:
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
    """ Explicit GET route endpoint unblocks keep_alive loopback connections """
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
                print(f"⚠️ Paystack Telegram notification error: {e}")
            
    return {"status": "success"}

# --- 4. Bot User Interface Layout Matrix ---
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
    """ Captures event queries immediately from the FastAPI router engine """
    try:
        # Acknowledge the interaction to instantly stop the user interface loading spinner
        bot.answer_callback_query(callback_query_id=call.id)
        target_chat_id = call.message.chat.id
        
        if call.data == "get_yields":
            print(f"📊 [UI EVENT] Dispatching metrics summary box to Chat ID: {target_chat_id}")
            bot.send_message(
                chat_id=target_chat_id,
                text="📈 *Performance Output:*\nToday's Yield: `+1.42%` \nTotal Vault Balance: `₦42,500.00`",
                parse_mode="Markdown"
            )
        elif call.data == "add_funds":
            pay_url = f"https://paystack.com{call.from_user.id}%7D"
            bot.send_message(
                chat_id=target_chat_id,
                text=f"💳 Click below to securely deposit funds via Paystack:\n[Secure Gateway Link]({pay_url})",
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
    except Exception as e:
        print(f"❌ Critical exception inside callback query context handler: {e}")

# --- 5. Clean Process Spawning Core ---
def run_java_execution_engine():
    print("☕ [THREAD] Spawning non-blocking Java Hot-Path Subprocess...")
    # Using Popen prevents the engine jar execution from hijacking the primary process thread
    subprocess.Popen(["java", "-Xmx192m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    import keep_alive
    asyncio.run(keep_alive.start_parallel_loops())

if __name__ == "__main__":
    # Launch concurrent infrastructure threads cleanly alongside primary context
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()

    # Bind Uvicorn server gateway loop explicitly
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
