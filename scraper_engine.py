
"""
Free Arbitrage Mesh — Authorized Price Monitor
Version: 2.1.0

Monitors a configured HTTPS webpage and records indicative price
movement. It does not execute trades or establish realized profit.
"""

import asyncio
import logging
import os
import re
import time
from decimal import Decimal, InvalidOperation
from urllib.parse import urlparse

import requests
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

import database


# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------

MARKET_PAGE_URL = os.getenv("MARKET_PAGE_URL", "").strip()
PRICE_SELECTOR = os.getenv("PRICE_SELECTOR", "").strip()

PRICE_CURRENCY = os.getenv("PRICE_CURRENCY", "NGN").strip().upper()
BASELINE_PRICE_RAW = (
    os.getenv("BASELINE_PRICE", "").strip()
    or os.getenv("BASELINE_RATE_NGN", "").strip()
)
BASELINE_CURRENCY = os.getenv(
    "BASELINE_CURRENCY",
    "NGN" if os.getenv("BASELINE_RATE_NGN") else PRICE_CURRENCY,
).strip().upper()

SCRAPER_INTERVAL_SECONDS = max(
    30, int(os.getenv("SCRAPER_INTERVAL_SECONDS", "180"))
)
NAVIGATION_TIMEOUT_MS = max(
    5000, int(os.getenv("SCRAPER_NAVIGATION_TIMEOUT_MS", "45000"))
)
SELECTOR_TIMEOUT_MS = max(
    1000, int(os.getenv("SCRAPER_SELECTOR_TIMEOUT_MS", "10000"))
)

MIN_VALID_PRICE = Decimal(os.getenv("MIN_VALID_PRICE", "0.01"))
MAX_VALID_PRICE = Decimal(os.getenv("MAX_VALID_PRICE", "1000000000"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()

ALERT_AFTER_FAILURES = max(
    1, int(os.getenv("ALERT_AFTER_FAILURES", "3"))
)
ALERT_COOLDOWN_SECONDS = max(
    60, int(os.getenv("ALERT_COOLDOWN_SECONDS", "900"))
)

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("scraper_engine")


# ---------------------------------------------------------
# Validation and price parsing
# ---------------------------------------------------------

def is_valid_https_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        return (
            parsed.scheme.lower() == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
        )
    except (TypeError, ValueError):
        return False


def get_baseline_price() -> Decimal | None:
    if not BASELINE_PRICE_RAW:
        return None

    try:
        value = Decimal(BASELINE_PRICE_RAW)
        if value <= 0:
            raise ValueError("Baseline price must be greater than zero.")
        return value
    except (InvalidOperation, ValueError):
        logger.error("BASELINE_PRICE must be a valid positive number.")
        return None


def normalize_numeric_string(raw: str) -> str:
    """
    Normalize common number formats:
    1,234.56 -> 1234.56
    1.234,56 -> 1234.56
    1234,56  -> 1234.56
    1,234    -> 1234

    A single separator followed by exactly three digits is treated
    as a thousands separator. Ambiguous source formats should be
    normalized at the source or handled with a provider-specific parser.
    """
    value = raw.strip().replace(" ", "").replace("\u00a0", "")

    if "," in value and "." in value:
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        parts = value.split(",")
        if len(parts) == 2 and len(parts[1]) != 3:
            value = value.replace(",", ".")
        else:
            value = value.replace(",", "")
    elif value.count(".") > 1:
        parts = value.split(".")
        if len(parts[-1]) in (1, 2):
            value = "".join(parts[:-1]) + "." + parts[-1]
        else:
            value = "".join(parts)

    return value


def parse_price(text: str) -> Decimal:
    """
    Extract the first numeric price from visible text.
    Configure a narrow PRICE_SELECTOR to avoid selecting unrelated numbers.
    """
    if not text:
        raise ValueError("Price element is empty.")

    matches = re.findall(r"[-+]?\d[\d\s.,]*", text)
    if not matches:
        raise ValueError("No numeric price was found.")

    candidate = normalize_numeric_string(matches[0])

    try:
        price = Decimal(candidate)
    except InvalidOperation as exc:
        raise ValueError("Could not parse the visible price.") from exc

    if not price.is_finite():
        raise ValueError("Price must be a finite number.")

    if price < MIN_VALID_PRICE or price > MAX_VALID_PRICE:
        raise ValueError("Price is outside the configured valid range.")

    return price


# ---------------------------------------------------------
# Notifications
# ---------------------------------------------------------

def send_telegram(message: str) -> bool:
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_ADMIN_CHAT_ID:
        logger.info("Telegram is not configured; alert not sent.")
        return False

    endpoint = (
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = requests.post(
            endpoint,
            json={
                "chat_id": TELEGRAM_ADMIN_CHAT_ID,
                "text": message[:4000],
                "disable_web_page_preview": True,
            },
            timeout=15,
        )
        response.raise_for_status()
        result = response.json()
        return isinstance(result, dict) and result.get("ok") is True
    except (requests.RequestException, ValueError):
        logger.exception("Telegram alert failed.")
        return False


# ---------------------------------------------------------
# Browser monitor
# ---------------------------------------------------------

class PriceMonitor:
    def __init__(self):
        self.consecutive_failures = 0
        self.last_alert_time = 0.0
        self.last_price: Decimal | None = None

    async def read_price(self, page) -> Decimal:
        await page.goto(
            MARKET_PAGE_URL,
            wait_until="domcontentloaded",
            timeout=NAVIGATION_TIMEOUT_MS,
        )

        element = page.locator(PRICE_SELECTOR).first
        await element.wait_for(
            state="visible",
            timeout=SELECTOR_TIMEOUT_MS,
        )

        visible_text = (await element.inner_text()).strip()
        return parse_price(visible_text)

    def record_indicative_difference(
        self,
        current_price: Decimal,
        baseline_price: Decimal | None,
    ) -> None:
        if baseline_price is None:
            logger.info(
                "Observed price: %s %s; no baseline configured.",
                current_price,
                PRICE_CURRENCY,
            )
            return

        if PRICE_CURRENCY != BASELINE_CURRENCY:
            logger.error(
                "Currency mismatch: observed %s, baseline %s. "
                "Difference will not be calculated.",
                PRICE_CURRENCY,
                BASELINE_CURRENCY,
            )
            return

        difference_pct = (
            (current_price - baseline_price) / baseline_price
        ) * Decimal("100")

        logger.info(
            "Observed price: %s %s | Baseline: %s %s | "
            "Indicative difference: %s%%",
            current_price,
            PRICE_CURRENCY,
            baseline_price,
            BASELINE_CURRENCY,
            difference_pct.quantize(Decimal("0.01")),
        )

        # This stores an indicative metric only. It is not a trade,
        # a realized return, or verified revenue.
        try:
            database.update_ledger_yield(float(
                difference_pct.quantize(Decimal("0.01"))
            ))
        except Exception:
            logger.exception("Could not update indicative database metric.")

    async def handle_failure(self, reason: str) -> None:
        self.consecutive_failures += 1
        logger.warning(
            "Price monitoring failure %d/%d: %s",
            self.consecutive_failures,
            ALERT_AFTER_FAILURES,
            reason,
        )

        now = time.time()
        should_alert = (
            self.consecutive_failures >= ALERT_AFTER_FAILURES
            and now - self.last_alert_time >= ALERT_COOLDOWN_SECONDS
        )

        if should_alert:
            message = (
                "Free Arbitrage Mesh — Price Monitor Alert\n\n"
                f"Source: {MARKET_PAGE_URL or 'Not configured'}\n"
                f"Consecutive failures: {self.consecutive_failures}\n"
                f"Latest issue: {reason[:500]}\n\n"
                "Check the source page, selector, network, and provider terms."
            )
            send_telegram(message)
            self.last_alert_time = now

    async def run(self) -> None:
        if not MARKET_PAGE_URL or not is_valid_https_url(MARKET_PAGE_URL):
            logger.error(
                "Set MARKET_PAGE_URL to an authorized, valid HTTPS page."
            )
            return

        if not PRICE_SELECTOR:
            logger.error("PRICE_SELECTOR is not configured.")
            return

        baseline_price = get_baseline_price()

        if baseline_price is not None and PRICE_CURRENCY != BASELINE_CURRENCY:
            logger.warning(
                "Baseline currency %s differs from source currency %s. "
                "Configure matching currencies before comparing prices.",
                BASELINE_CURRENCY,
                PRICE_CURRENCY,
            )

        try:
            database.init_db()
        except Exception:
            logger.exception("Database initialization failed.")
            return

        logger.info(
            "Price monitor started. Currency=%s, interval=%ss",
            PRICE_CURRENCY,
            SCRAPER_INTERVAL_SECONDS,
        )

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)

            try:
                page = await browser.new_page()
                page.set_default_timeout(SELECTOR_TIMEOUT_MS)

                while True:
                    cycle_start = time.monotonic()

                    try:
                        price = await self.read_price(page)
                        self.consecutive_failures = 0

                        self.record_indicative_difference(
                            price, baseline_price
                        )

                        if self.last_price is not None:
                            logger.info(
                                "Change since previous observation: %s %s",
                                price - self.last_price,
                                PRICE_CURRENCY,
                            )

                        self.last_price = price

                    except PlaywrightTimeoutError:
                        await self.handle_failure(
                            "Timed out loading the page or price element."
                        )
                    except (ValueError, Exception) as exc:
                        await self.handle_failure(
                            f"{type(exc).__name__}: {str(exc)[:400]}"
                        )

                    elapsed = time.monotonic() - cycle_start
                    await asyncio.sleep(
                        max(1, SCRAPER_INTERVAL_SECONDS - int(elapsed))
                    )

            finally:
                await browser.close()


async def main() -> None:
    monitor = PriceMonitor()
    await monitor.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Price monitor stopped.")
