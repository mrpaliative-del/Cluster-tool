import asyncio
import os
import time
import telebot
from playwright.async_api import async_playwright
import database

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A").strip()
ADMIN_TELEGRAM_ID = 8608729377  # Receives all telemetry errors automatically

alert_bot = telebot.TeleBot(TOKEN, threaded=False)

def dispatch_system_alert(error_message):
    try:
        alert_bot.send_message(
            chat_id=ADMIN_TELEGRAM_ID,
            text=f"🚨 *[INFRASTRUCTURE ALERT]*\nSystem Engine Failure Detected!\n\n`Error Details:`\n{error_message}",
            parse_mode="Markdown"
        )
    except Exception as ae:
        print(f"❌ Failed to dispatch infrastructure warning alerts to admin channel: {ae}")

async def scrape_exchange_orderbook():
    print("🕷️ [PLAYWRIGHT] Initializing Headless Data Extraction Engine...")
    database.init_db()
    
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True, 
            args=["--no-sandbox", "--disable-setuid-sandbox", "--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        page = await context.new_page()
        
        consecutive_failures = 0
        while True:
            try:
                await page.goto("https://binance.com", timeout=45000, wait_until="domcontentloaded")
                await asyncio.sleep(5)
                
                selectors = [".price-text-selector", "div[class*='price']", "[data-qa='p2p-price-index']"]
                price_text = None
                
                for selector in selectors:
                    element = await page.query_selector(selector)
                    if element:
                        price_text = await element.inner_text()
                        if price_text and any(char.isdigit() for char in price_text):
                            break
                
                if price_text:
                    clean_price = "".join(c for c in price_text if c.isdigit() or c == '.')
                    market_rate = float(clean_price)
                    print(f" Mish-Mesh Data Found: ₦{market_rate:,.2f}")
                    
                    # Compute dynamic yield margins relative to baseline valuation metrics (₦9,500)
                    calculated_yield = round(((market_rate - 9500) / 9500) * 100, 2)
                    
                    # Update SQLite dynamic database variables instantly
                    database.update_ledger_yield(calculated_yield)
                    consecutive_failures = 0  # Clear memory counters on successful iterations
                else:
                    raise ValueError("All interface DOM extraction paths returned blank strings or mismatched objects.")
                    
            except Exception as e:
                consecutive_failures += 1
                error_log = f"[Iteration Failure Count: {consecutive_failures}] Exception mapping web layouts: {str(e)}"
                print(f"⚠️ {error_log}")
                
                # If the crawler encounters 3 consecutive network roadblocks, notify the admin instantly
                if consecutive_failures >= 3:
                    dispatch_system_alert(error_log)
                    consecutive_failures = 0  # Throttle alarms to pass network loop limits
                    
            await asyncio.sleep(180)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_exchange_orderbook())
