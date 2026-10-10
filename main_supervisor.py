import os
import uvicorn
import hmac
import hashlib
import telebot
import asyncio
import requests
import urllib.parse
from fastapi import FastAPI, Request, Response, status
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, Update
from contextlib import asynccontextmanager
import database

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A").strip()
PAYSTACK_SECRET = os.getenv("PAYSTACK_SECRET_KEY", "sk_live_xxxx").encode('utf-8')
RENDER_URL = os.getenv("RENDER_EXTERNAL_URL", "https://onrender.com").strip().rstrip('/')

BROKER_API_URL = os.getenv("BROKER_API_URL", "https://yourbroker.com")
BROKER_TOKEN = os.getenv("BROKER_API_TOKEN", "mock_secure_token_xxxx")
LOT_SIZE = 0.1

bot = telebot.TeleBot(TOKEN, threaded=False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    await asyncio.sleep(2)
    webhook_url = f"{RENDER_URL}/tg-backend-intake"
    print(f"🌐 Linking Webhook Pipeline to: {webhook_url}")
    
    # Resilient Retry Engine to bypass Telegram 429 Rate Limits
    for attempt in range(1, 6):
        try:
            bot.remove_webhook()
            await asyncio.sleep(2)
            bot.set_webhook(url=webhook_url, allowed_updates=["message", "callback_query"])
            print("🌐 Webhook linkage active and running!")
            break
        except Exception as e:
            print(f"⚠️ Webhook linkage attempt {attempt}/5 failed: {e}")
            if "Too Many Requests" in str(e) or "429" in str(e):
                wait_time = attempt * 5
                print(f"⏳ Rate limit triggered. Backing off for {wait_time} seconds...")
                await asyncio.sleep(wait_time)
            else:
                await asyncio.sleep(2)
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/")
async def home_mesh_root(): 
    return {"status": "online"}

@app.head("/")
async def home_mesh_head():
    return Response(status_code=200)

@app.get("/health")
def engine_health_check(): 
    return {"status": "ok"}

@app.get("/portfolio-status")
def get_portfolio_status():
    return database.get_ledger_metrics()

@app.post("/tradingview-alert")
async def tradingview_alert_receiver(request: Request):
    try:
        payload = await request.json()
        action = payload.get("action")
        ticker = payload.get("ticker")
        price = payload.get("close_price")
        balances = database.get_ledger_metrics()
        fx_capital = balances.get("FOREX_RESERVE", 0.0)
        if fx_capital <= 0:
            return {"status": "ignored", "reason": "zero_capital"}
        if BROKER_TOKEN == "mock_secure_token_xxxx":
            print(f"🔬 Simulated {action} entry for {ticker} at {price}.")
        else:
            broker_payload = {
                "instrument": ticker, 
                "units": LOT_SIZE * 100000 if "Long" in action else -LOT_SIZE * 100000, 
                "type": "MARKET"
            }
            requests.post(BROKER_API_URL, json=broker_payload, headers={"Authorization": f"Bearer {BROKER_TOKEN}"}, timeout=10)
        bot.send_message(
            chat_id=8608729377,
            text=f"📡 *Alert Executed!*\nAction: `{action}`\nAsset: `{ticker}`\nPrice: `{price}`",
            parse_mode="Markdown"
        )
        return {"status": "executed"}
    except Exception as e:
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
                    text=f"✅ *Payment Confirmed!*\nSuccessfully deposited *₦{amount:,.2f}*.", 
                    parse_mode="Markdown"
                )
            except Exception as e:
                print(f"⚠️ Telegram alert error: {e}")
    return {"status": "success"}

@bot.message_handler(commands=['start', 'dashboard'])
def send_welcome(message):
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton("📊 Portfolio Matrix", callback_data="get_yields"),
        InlineKeyboardButton("💳 Add Funds", callback_data="add_funds")
    )
    bot.send_message(
        chat_id=message.chat.id,
        text="🤖 *Holding Master Engine Active.*\nSelect a monitoring hub parameter:",
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
                f"⚽ *Sports Betting Vault (5%):* `₦{balances.get('SPORTS_BETTING', 0.0):,.2f}`"
            )
            bot.send_message(chat_id=target_chat_id, text=dashboard_text, parse_mode="Markdown")
            
        elif call.data == "add_funds":
            user_string = str(call.from_user.id)
            
            # Isolated components ensure no character fragmentation can occur at runtime
            base_endpoint = "https://paystack.shop"
            tracking_payload = f"?metadata=%7B%22telegram_id%22%3A{user_string}%7D"
            pay_url = f"{base_endpoint}{tracking_payload}"
            
            text_reply = (
                "💳 <b>Paystack Secure Gateway Ready</b>\n\n"
                "Tap your payment link below to securely fund your automated matrix via Mpee global ventures:\n\n"
                f'🔗 <a href="{pay_url}">Proceed to Secure Checkout</a>\n\n'
                f"<code>{pay_url}</code>"
            )
            
            bot.send_message(
                chat_id=target_chat_id,
                text=text_reply,
                parse_mode="HTML",
                disable_web_page_preview=True
            )
    except Exception as e:
        bot.send_message(
            chat_id=call.message.chat.id, 
            text=f"⚠️ *Internal Execution Error:* `{str(e)}`", 
            parse_mode="Markdown"
        )

@bot.message_handler(commands=['tune'])
def adjust_investment_profile(message):
    guide_text = (
        "⚙️ *15-Tool Tuning Console*\n\n"
        "Send a line matching this exact format to update splits:\n\n"
        "`set_split: 0.10, 0.30, 0.20, 0.10, 0.10, 0.15, 0.05`"
    )
    bot.send_message(chat_id=message.chat.id, text=guide_text, parse_mode="Markdown")

@bot.message_handler(func=lambda msg: msg.text and msg.text.startswith("set_split:"))
def process_tuning_input(message):
    try:
        raw_data = message.text.replace("set_split:", "").strip()
        parts = [float(x.strip()) for x in raw_data.split(",")]
        if len(parts) != 7:
            bot.reply_to(message, "❌ *Configuration Fault:* Pass exactly 7 parameter values.")
            return
        total_sum = sum(parts)
        if abs(total_sum - 1.0) > 1e-4:
            bot.reply_to(message, f"❌ *Validation Fault:* Sum total must equal exactly 1.0.")
            return
        new_matrix = {
            "PERSONAL_UPKEEP": parts,
            "CRYPTO_ARBITRAGE": parts,
            "FOREX_RESERVE": parts,
            "STOCKS_EQUITIES": parts,
            "COMMODITIES_GOLD": parts,
            "ALT_MARKETS": parts,
            "SPORTS_BETTING": parts
        }
        success = database.update_tuning_matrix(new_matrix)
        if success:
            bot.reply_to(message, "🚀 *Allocation splits updated successfully!*")
            return
        bot.reply_to(message, "❌ Core database write-lock timeout error.")
    except Exception as error:
        bot.reply_to(message, f"❌ *Parsing Abnormality:* Error: {error}")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port)
