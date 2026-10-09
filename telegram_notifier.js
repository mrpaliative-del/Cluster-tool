const BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const CHAT_ID = process.env.TELEGRAM_CHAT_ID;

async function sendTelegramAlert(message) {
  if (!BOT_TOKEN || !CHAT_ID) {
    console.log('[Telegram Alert Skipped] Missing live credentials.');
    return;
  }

  try {
    const url = `https://api.telegram.org/bot${BOT_TOKEN}/sendMessage`;
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: CHAT_ID,
        text: message,
        parse_mode: 'Markdown'
      })
    });

    if (!response.ok) {
      const errorData = await response.json();
      console.error('[Telegram Error] API rejected message:', errorData);
    }
  } catch (err) {
    console.error('[Telegram Network Error] Failed to send alert:', err.message);
  }
}

module.exports = { sendTelegramAlert };
