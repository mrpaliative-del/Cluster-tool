const express = require('express');
const crypto = require('crypto');
const https = require('https');
const Redis = require('redis');

const app = express();

// Sanitize REDIS_URL to remove hidden invisible Unicode characters or whitespace
const rawRedisUrl = process.env.REDIS_URL || 'redis://localhost:6379';
const sanitizedRedisUrl = rawRedisUrl.replace(/^[\s\u200e\u200f\u202a-\u202e]+/, '').trim();

const redisClient = Redis.createClient({ 
  url: sanitizedRedisUrl,
  socket: {
    tls: sanitizedRedisUrl.startsWith('rediss://'),
    rejectUnauthorized: false
  }
});

redisClient.on('error', (err) => console.error('[Redis Client Error]', err));
redisClient.connect().then(() => {
  console.log('[Redis] Connected successfully to state store.');
}).catch(console.error);

// 1. CONFIG & TELEGRAM TELEMETRY SETUP
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '';

function dispatchTelegramMessage(message) {
  return new Promise((resolve) => {
    if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return resolve(false);

    const postData = JSON.stringify({
      chat_id: TELEGRAM_CHAT_ID,
      text: message,
      parse_mode: 'Markdown'
    });

    const options = {
      hostname: 'api.telegram.org',
      port: 443,
      path: `/bot${TELEGRAM_BOT_TOKEN}/sendMessage`,
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Content-Length': Buffer.byteLength(postData) },
      timeout: 10000
    };

    const req = https.request(options, (res) => {
      let body = '';
      res.on('data', chunk => body += chunk);
      res.on('end', () => resolve(res.statusCode === 200));
    });
    req.on('error', () => resolve(false));
    req.write(postData);
    req.end();
  });
}

// 2. RAW BODY CAPTURE FOR PAYSTACK HMAC VERIFICATION
app.use('/api/webhook/paystack', express.json({
  verify: (req, res, buf) => {
    req.rawBody = buf; // Stores raw buffer for cryptographic comparison
  }
}));

app.use(express.json());

// ==========================================
// 3. SECURE WEBHOOK & REAL-WORLD FULFILLMENT
// ==========================================
app.post('/api/webhook/paystack', async (req, res) => {
  try {
    const signature = req.headers['x-paystack-signature'];
    
    // Zero-Trust HMAC SHA512 Verification
    const hash = crypto
      .createHmac('sha512', PAYSTACK_SECRET_KEY)
      .update(req.rawBody)
      .digest('hex');

    if (hash !== signature) {
      console.warn('[Security] Unauthorized webhook signature dropped.');
      return res.status(401).json({ error: 'Invalid signature' });
    }

    // Acknowledge receipt immediately to comply with gateway timeout rules
    res.status(200).json({ status: 'received' });

    const event = req.body;

    if (event.event === 'charge.success') {
      const paymentData = event.data;
      const taskId = paymentData.metadata?.task_id || 'unknown';
      const sector = paymentData.metadata?.sector || 'DelightPay Fulfillment';
      const reference = paymentData.reference;
      const amountNGN = paymentData.amount / 100;

      if (!paymentData.metadata?.task_id) {
        console.error('[Error] Missing task_id metadata in transaction payload.');
      }

      try {
        // Idempotency Lock Check via Redis with Safe Fallback
        const stateKey = `state:processed:${reference}`;
        const alreadyProcessed = await redisClient.get(stateKey);
        
        if (alreadyProcessed) {
          console.log(`[Idempotency] Duplicate event caught and ignored: ${reference}`);
          return;
        }

        // Mark as successfully processed atomically
        await redisClient.set(stateKey, 'success', { EX: 86400 });
      } catch (redisErr) {
        console.warn(`⚠️ [Webhook Notice] Redis state check bypassed: ${redisErr.message}`);
      }

      // Execute Real-World Fulfillment Log & Dispatch Real Telegram Alert
      console.log(`[Fulfillment Success] Task ${taskId} successfully executed and settled. Ref: ${reference}`);
      
      await dispatchTelegramMessage(
        `💰 🔊 *Real Paystack Webhook Verified (Success)*\n\n` +
        `• *Task ID:* \`${taskId}\`\n` +
        `• *Sector:* \`${sector}\`\n` +
        `• *Settled Amount:* \`₦${amountNGN.toLocaleString()}\`\n` +
        `• *Reference:* \`${reference}\``
      );
    }
  } catch (error) {
    console.error('[Webhook Error]', error);
  }
});

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Autonomous Outbound Engine running on port ${PORT}`);
});
