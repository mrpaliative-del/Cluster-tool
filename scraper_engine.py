
import asyncio
import logging
import os
import re
import time
from contextlib import suppress
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import telebot
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

import database


# =========================================================
# CONFIGURATION
# Configure these values in Render Environment Variables.
# =========================================================

MARKET_PAGE_URL = os.getenv("MARKET_PAGE_URL", "").strip()
PRICE_SELECTOR = os.getenv("PRICE_SELECTOR", "").strip()

# Optional baseline. Only calculates an indicative price difference.
BASELINE_RATE_NGN = os.getenv("BASELINE_RATE_NGN", "").strip()

SCAN_INTERVAL_SECONDS = max(
    30, int(os.getenv("SCRAPER_INTERVAL_SECONDS", "180"))
)
NAVIGATION_TIMEOUT_MS = 45000
SELECTOR_TIMEOUT_MS = 10000

MIN_VALID_PRICE = Decimal(
    os.getenv("MIN_VALID_PRICE", "0.01")
)
MAX_VALID_PRICE = Decimal(
    os.getenv("MAX_VALID_PRICE", "1000000000")
)

TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
ADMIN_TELEGRAM_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()

ALERT_AFTER_FAILURES = 3
ALERT_COOLDOWN_SECONDS = 900

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("market-scraper")

alert_bot = (
    telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
    if TELEGRAM_TOKEN
    else None
)

last_alert_time = 0.0


# =========================================================
# CONFIGURATION VALIDATION
# =========================================================

def validate_configuration():
    if not MARKET_PAGE_URL:
        raise RuntimeError(
            "MARKET_PAGE_URL is missing. Configure the exact "
            "market-data page you are authorized to access."
        )

    parsed_url = urlparse(MARKET_PAGE_URL)

    if parsed_url.scheme != "https" or not parsed_url.netloc:
        raise RuntimeError("MARKET_PAGE_URL must be a valid HTTPS URL.")

    if not PRICE_SELECTOR:
        raise RuntimeError(
            "PRICE_SELECTOR is missing. Configure a selector for "
            "one specific price element on the selected page."
        )

    if MIN_VALID_PRICE <= 0 or MAX_VALID_PRICE <= MIN_VALID_PRICE:
        raise RuntimeError("Invalid MIN_VALID_PRICE / MAX_VALID_PRICE.")

    if BASELINE_RATE_NGN:
        try:
            baseline = Decimal(BASELINE_RATE_NGN)
            if not baseline.is_finite() or baseline <= 0:
                raise ValueError
        except (InvalidOperation, ValueError):
            raise RuntimeError(
                "BASELINE_RATE_NGN must be a positive finite number."
            )


# =========================================================
# TELEGRAM ALERTS
# =========================================================

def dispatch_system_alert(error_message: str):
    """Send an infrastructure alert without exposing credentials."""
    global last_alert_time

    now = time.monotonic()

    if now - last_alert_time < ALERT_COOLDOWN_SECONDS:
        return

    if not alert_bot or not ADMIN_TELEGRAM_ID:
        logger.warning(
            "Alert not sent: configure TELEGRAM_BOT_TOKEN and "
            "TELEGRAM_ADMIN_CHAT_ID."
        )
        return

    try:
        alert_bot.send_message(
            chat_id=ADMIN_TELEGRAM_ID,
            text=(
                "INFRASTRUCTURE ALERT\n"
                "Playwright scraper encountered repeated failures.\n\n"
                f"Details: {error_message[:2500]}"
            ),
        )
        last_alert_time = now
    except Exception:
        logger.exception("Could not send Telegram infrastructure alert.")


# =========================================================
# PRICE PARSING AND VALIDATION
# =========================================================

PRICE_PATTERN = re.compile(
    r"(?<![\w.])"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)"
    r"(?:\.\d+)?"
    r"(?![\w.])"
)


def parse_price(text: str) -> Decimal:
    """
    Parse the first numeric value from a narrowly targeted price element.
    Configure PRICE_SELECTOR to match a single price, not a whole page.
    """
    if not text:
        raise ValueError("The selected price element is empty.")

    match = PRICE_PATTERN.search(text.strip())

    if not match:
        raise ValueError("No valid numeric price found in the selected element.")

    try:
        price = Decimal(match.group(0).replace(",", ""))
    except InvalidOperation as exc:
        raise ValueError("Price could not be parsed.") from exc

    if not price.is_finite():
        raise ValueError("Price is not finite.")

    if price < MIN_VALID_PRICE or price > MAX_VALID_PRICE:
        raise ValueError(
            f"Price {price} is outside the configured safety limits."
        )

    return price


def calculate_indicative_difference(price: Decimal):
    """
    This is a comparison with a configured baseline, NOT verified profit.
    """
    if not BASELINE_RATE_NGN:
        return None

    baseline = Decimal(BASELINE_RATE_NGN)
    return ((price - baseline) / baseline) * Decimal("100")


# =========================================================
# SCRAPER ENGINE
# =========================================================

async def scrape_exchange_orderbook():
    validate_configuration()

    logger.info("Starting Playwright market-data scraper.")

    await asyncio.to_thread(database.init_db)

    consecutive_failures = 0

    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--no-sandbox"],
        )

        try:
            context = await browser.new_context(
                locale="en-US",
                viewport={"width": 1365, "height": 900},
            )

            page = await context.new_page()
            page.set_default_navigation_timeout(
                NAVIGATION_TIMEOUT_MS
            )
            page.set_default_timeout(SELECTOR_TIMEOUT_MS)

            while True:
                try:
                    response = await page.goto(
                        MARKET_PAGE_URL,
                        wait_until="domcontentloaded",
                        timeout=NAVIGATION_TIMEOUT_MS,
                    )

                    if response and response.status >= 400:
                        raise RuntimeError(
                            f"Market page returned HTTP {response.status}."
                        )

                    # Wait for the specifically configured price element.
                    price_element = page.locator(PRICE_SELECTOR).first
                    price_text = await price_element.inner_text(
                        timeout=SELECTOR_TIMEOUT_MS
                    )

                    market_rate = parse_price(price_text)

                    difference = calculate_indicative_difference(
                        market_rate
                    )

                    logger.info(
                        "Market price extracted: %s; source=%s",
                        market_rate,
                        urlparse(MARKET_PAGE_URL).netloc,
                    )

                    if difference is None:
                        logger.info(
                            "No baseline configured. Price extracted, "
                            "but no yield comparison or ledger update made."
                        )
                    else:
                        # Keep the existing database function, but only
                        # after a valid price and explicit baseline exist.
                        await asyncio.to_thread(
                            database.update_ledger_yield,
                            float(difference.quantize(Decimal("0.01"))),
                        )

                        logger.info(
                            "Indicative price difference: %s%%. "
                            "This is not realized profit.",
                            difference.quantize(Decimal("0.01")),
                        )

                    consecutive_failures = 0

                except asyncio.CancelledError:
                    raise

                except (
                    PlaywrightTimeoutError,
                    ValueError,
                    RuntimeError,
                ) as exc:
                    consecutive_failures += 1

                    logger.warning(
                        "Scrape failed (%s consecutive failures): %s",
                        consecutive_failures,
                        str(exc)[:1000],
                    )

                    if consecutive_failures >= ALERT_AFTER_FAILURES:
                        # Telegram's synchronous client must not block
                        # the asynchronous browser loop.
                        await asyncio.to_thread(
                            dispatch_system_alert,
                            str(exc),
                        )
                        consecutive_failures = 0

                except Exception as exc:
                    consecutive_failures += 1

                    logger.exception(
                        "Unexpected scraper failure (%s consecutive).",
                        consecutive_failures,
                    )

                    if consecutive_failures >= ALERT_AFTER_FAILURES:
                        await asyncio.to_thread(
                            dispatch_system_alert,
                            f"Unexpected scraper error: {str(exc)[:1500]}",
                        )
                        consecutive_failures = 0

                await asyncio.sleep(SCAN_INTERVAL_SECONDS)

        finally:
            await browser.close()
            logger.info("Playwright browser closed.")


if __name__ == "__main__":
    try:
        asyncio.run(scrape_exchange_orderbook())
    except KeyboardInterrupt:
        logger.info("Scraper stopped by shutdown request.")
    except Exception:
        logger.exception("Scraper terminated during startup or execution.")
        raise
