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

# --- 2. Safe Sequential Lifespan Manager ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    """ Executes webhook routing setup ONLY after the server port is completely live """
    # Wait 5 seconds for Render to finish dropping old containers
    await asyncio.sleep(5)
    
    webhook_url = f"{RENDER_URL}/tg-backend-intake"
    print(f"🌐 [LIFESPAN PROVISION] Mapping webhook pipeline directly to: {webhook_url}")
    
    try:
        bot.remove_webhook()
        await asyncio.sleep(1)
        success = bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
        if success:
            print("🌐 [LIFESPAN SUCCESS] Webhook pipeline linkage confirmed and active!")
    except Exception as e:
        print(f"❌ [LIFESPAN FAULT] Webhook registration failed: {e}")
    
    yield
    print("⚠️ [LIFESPAN] Application container spinning down.")

app = FastAPI(lifespan=lifespan)

# --- 3. Gateway Routing System ---
@app.get("/")
def home_root():
    return {"status": "online"}

@app.get("/health")
def health_check():
    """ Dedicated health monitoring hook for keep_alive.py """
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
                bot.send_message(tg_id, f"✅ *Payment Confirmed!*\nSuccessfully deposited ₦{amount:,.2f} via Paystack into your ledger.", parse_mode="Markdown")
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
        text="🤖 *Arbitrage System Active.*\nSelect an option to interact with the global scanning grid:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@bot.callback_query_handler(func=lambda call: True)
def callback_inline(call):
    try:
        bot.answer_callback_query(callback_query_id=call.id)
        target_chat_id = call.message.chat.id
        
        if call.data == "get_yields":
            print(f"📊 [UI] Dispatching metrics summary box to Chat ID: {target_chat_id}")
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
        print(f"❌ Error during callback execution processing: {e}")

# --- 5. Subprocess Lifecycles ---
def run_java_execution_engine():
    subprocess.run(["java", "-Xmx256m", "-jar", "engine.jar"])

def run_keep_alive_loops():
    import keep_alive
    asyncio.run(keep_alive.start_parallel_loops())

if __name__ == "__main__":
    threading.Thread(target=run_java_execution_engine, daemon=True).start()
    threading.Thread(target=run_keep_alive_loops, daemon=True).start()

    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
