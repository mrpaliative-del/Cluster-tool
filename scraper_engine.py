import asyncio
import os
import time
import telebot
from playwright.async_api import async_playwright
import database

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A").strip()
ADMIN_TELEGRAM_ID = 8608729377  # Automatically receives alerts if selectors break

alert_bot = telebot.TeleBot(TOKEN, threaded=False)

def dispatch_system_alert(error_message):
    try:
        alert_bot.send_message(
            chat_id=ADMIN_TELEGRAM_ID,
            text=f"🚨 *[INFRASTRUCTURE ALERT]*\nPlaywright Engine Failure Detected!\n\n`Error Details:`\n{error_message}",
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
                # Target active market liquidity pool page
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
                    print(f"🎯 [PLAYWRIGHT] Extracted target rate: ₦{market_rate:,.2f}")
                    
                    # Calculate dynamic percentage spreads relative to baseline evaluation (₦1,700 base assumption)
                    calculated_yield = round(((market_rate - 1700) / 1700) * 100, 2)
                    
                    # STREAM DIRECTLY TO SQLITE: Update ledger data coordinates natively
                    database.update_ledger_yield(calculated_yield)
                    print(f"💾 [PLAYWRIGHT] Database updated with live yield: +{calculated_yield}%")
                    consecutive_failures = 0  # Reset failure counter on successful data match
                else:
                    raise ValueError("All interface DOM extraction paths returned blank strings or mismatched objects.")
                    
            except Exception as e:
                consecutive_failures += 1
                error_log = f"[Iteration Failure Count: {consecutive_failures}] Exception mapping web layouts: {str(e)}"
                print(f"⚠️ {error_log}")
                
                # If the crawler encounters 3 consecutive network blockers, sound the alarm to your phone
                if consecutive_failures >= 3:
                    dispatch_system_alert(error_log)
                    consecutive_failures = 0  # Throttle alarms to pass network loop limits
                    
            # Check market rate adjustments on a 3-minute interval matrix
            await asyncio.sleep(180)
        await browser.close()

if __name__ == "__main__":
    asyncio.run(scrape_exchange_orderbook())
