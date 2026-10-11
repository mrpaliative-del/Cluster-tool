
"""
Free Arbitrage Mesh — Authorized Price Monitor
Version: 2.2.0

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
from playwright.async_api import (
    async_playwright,
    TimeoutError as PlaywrightTimeoutError,
)

import database


# =========================================================
# 1. CONFIGURATION
# =========================================================

def get_int_env(name, default, minimum=1):
    """Read an integer environment variable safely."""
    raw = os.getenv(name, "").strip()

    if not raw:
        return default

    try:
        value = int(raw)
    except (TypeError, ValueError):
        logging.getLogger("scraper_engine").warning(
            "%s is invalid; using default %s.", name, default
        )
        return default

    if value < minimum:
        logging.getLogger("scraper_engine").warning(
            "%s must be at least %s; using default %s.",
            name,
            minimum,
            default,
        )
        return default

    return value


def get_decimal_env(name, default):
    """Read a finite Decimal environment variable safely."""
    raw = os.getenv(name, "").strip()

    if not raw:
        return Decimal(str(default))

    try:
        value = Decimal(raw)
        if not value.is_finite():
            raise InvalidOperation
        return value
    except (InvalidOperation, ValueError):
        logging.getLogger("scraper_engine").warning(
            "%s is invalid; using default %s.", name, default
        )
        return Decimal(str(default))


LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").strip().upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

logger = logging.getLogger("scraper_engine")

MARKET_PAGE_URL = os.getenv("MARKET_PAGE_URL", "").strip()
PRICE_SELECTOR = os.getenv("PRICE_SELECTOR", "").strip()

PRICE_CURRENCY = (
    os.getenv("PRICE_CURRENCY", "NGN").strip().upper() or "NGN"
)

BASELINE_PRICE_RAW = (
    os.getenv("BASELINE_PRICE", "").strip()
    or os.getenv("BASELINE_RATE_NGN", "").strip()
)

BASELINE_CURRENCY = (
    os.getenv(
        "BASELINE_CURRENCY",
        "NGN" if os.getenv("BASELINE_RATE_NGN", "").strip()
        else PRICE_CURRENCY,
    ).strip().upper()
    or PRICE_CURRENCY
)

SCRAPER_INTERVAL_SECONDS = get_int_env(
    "SCRAPER_INTERVAL_SECONDS", 180, minimum=30
)

NAVIGATION_TIMEOUT_MS = get_int_env(
    "SCRAPER_NAVIGATION_TIMEOUT_MS", 45000, minimum=5000
)

SELECTOR_TIMEOUT_MS = get_int_env(
    "SCRAPER_SELECTOR_TIMEOUT_MS", 10000, minimum=1000
)

MIN_VALID_PRICE = get_decimal_env("MIN_VALID_PRICE", "0.01")
MAX_VALID_PRICE = get_decimal_env("MAX_VALID_PRICE", "1000000000")

if MIN_VALID_PRICE <= 0 or MAX_VALID_PRICE < MIN_VALID_PRICE:
    logger.warning("Invalid price range; using safe defaults.")
    MIN_VALID_PRICE = Decimal("0.01")
    MAX_VALID_PRICE = Decimal("1000000000")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_ADMIN_CHAT_ID = os.getenv("TELEGRAM_ADMIN_CHAT_ID", "").strip()

ALERT_AFTER_FAILURES = get_int_env(
    "ALERT_AFTER_FAILURES", 3, minimum=1
)

ALERT_COOLDOWN_SECONDS = get_int_env(
    "ALERT_COOLDOWN_SECONDS", 900, minimum=60
)


# =========================================================
# 2. VALIDATION AND PRICE PARSING
# =========================================================

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


def get_baseline_price():
    if not BASELINE_PRICE_RAW:
        return None

    try:
        value = Decimal(BASELINE_PRICE_RAW)

        if not value.is_finite() or value <= 0:
            raise ValueError("Baseline must be positive and finite.")

        return value

    except (InvalidOperation, TypeError, ValueError):
        logger.error("Baseline price must be a valid positive number.")
        return None


def normalize_numeric_string(raw: str) -> str:
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
        raise ValueError("Price must be finite.")

    if price < MIN_VALID_PRICE or price > MAX_VALID_PRICE:
        raise ValueError("Price is outside the configured valid range.")

    return price


# =========================================================
# 3. TELEGRAM NOTIFICATIONS
# =========================================================

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


# =========================================================
# 4. PRICE MONITOR
# =========================================================

class PriceMonitor:
    def __init__(self):
        self.consecutive_failures = 0
        self.last_alert_time = 0.0
        self.last_price = None

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
        baseline_price,
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

        difference_pct = difference_pct.quantize(Decimal("0.01"))

        logger.info(
            "Observed price: %s %s | Baseline: %s %s | "
            "Indicative difference: %s%%",
            current_price,
            PRICE_CURRENCY,
            baseline_price,
            BASELINE_CURRENCY,
            difference_pct,
        )

        # Indicative metric only. This does not record income or profit.
        try:
            database.update_ledger_yield(float(difference_pct))
        except Exception:
            logger.exception(
                "Could not update the indicative database metric."
            )

    async def handle_failure(self, reason: str) -> None:
        self.consecutive_failures += 1

        logger.warning(
            "Price monitoring failure %s: %s",
            self.consecutive_failures,
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

            sent = send_telegram(message)

            if sent:
                self.last_alert_time = now

    async def run(self) -> None:
        if not MARKET_PAGE_URL or not is_valid_https_url(MARKET_PAGE_URL):
            logger.error(
                "Set MARKET_PAGE_URL to an authorized HTTPS page."
            )
            return

        if not PRICE_SELECTOR:
            logger.error("PRICE_SELECTOR is not configured.")
            return

        baseline_price = get_baseline_price()

        if (
            baseline_price is not None
            and PRICE_CURRENCY != BASELINE_CURRENCY
        ):
            logger.warning(
                "Baseline currency %s differs from source currency %s. "
                "Comparisons will be skipped.",
                BASELINE_CURRENCY,
                PRICE_CURRENCY,
            )

        try:
            database.init_db()
        except Exception:
            logger.exception("Database initialization failed.")
            return

        logger.info(
            "Price monitor starting: currency=%s interval=%ss",
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
                            price,
                            baseline_price,
                        )

                        if self.last_price is not None:
                            logger.info(
                                "Change since previous observation: %s %s",
                                price - self.last_price,
                                PRICE_CURRENCY,
                            )

                        self.last_price = price

                    except PlaywrightTimeoutError as exc:
                        await self.handle_failure(
                            f"Page or selector timeout: {str(exc)[:400]}"
                        )

                    except Exception as exc:
                        logger.exception("Price observation failed.")
                        await self.handle_failure(
                            f"{type(exc).__name__}: {str(exc)[:400]}"
                        )

                    elapsed = time.monotonic() - cycle_start

                    await asyncio.sleep(
                        max(1.0, SCRAPER_INTERVAL_SECONDS - elapsed)
                    )

            finally:
                await browser.close()


# =========================================================
# 5. ENTRY POINT
# =========================================================

async def main() -> None:
    monitor = PriceMonitor()
    await monitor.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Price monitor stopped.")
