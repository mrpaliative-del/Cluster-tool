import os
import telebot

# Retrieve Telegram credentials securely from the environment
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")

# Initialize the bot in non-threaded mode to prevent thread-pooling conflicts with FastAPI
bot = telebot.TeleBot(TOKEN, threaded=False) if TOKEN else None

def send_alert(message: str, parse_mode: str = "Markdown"):
    """
    Sends an instant notification alert to the configured Telegram chat ID.
    Falls back to standard console output if tokens are missing.
    """
    if bot and CHAT_ID:
        try:
            bot.send_message(CHAT_ID, message, parse_mode=parse_mode)
        except Exception as e:
            print(f"[Telegram Alert Error] Failed to dispatch message: {e}")
    else:
        print(f"[Telegram Local Log] {message}")
