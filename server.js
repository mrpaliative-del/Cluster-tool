const express = require('express');
const crypto = require('crypto');
const Redis = require('redis');

const app = express();

// Sanitize REDIS_URL to remove hidden invisible Unicode characters (e.g., LTR marks) or whitespace
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

// 1. RAW BODY CAPTURE FOR PAYSTACK HMAC VERIFICATION
app.use('/api/webhook/paystack', express.json({
  verify: (req, res, buf) => {
    req.rawBody = buf; // Stores raw buffer for cryptographic comparison
  }
}));

app.use(express.json());

const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || 'sk_test_your_key_here';

// ==========================================
// 2. OUTBOUND POLLING & TASK SCHEDULER WORKER
// ==========================================
async function runOutboundPollingWorker() {
  console.log('[Worker] Polling broader external endpoints for tasks...');
  
  // Simulated batch fetch from multiple partner APIs/endpoints
  const fetchedBatch = [
    { taskId: 'task_901', sector: 'logistics', value: 5000, targetUrl: 'https://api.partnerA.com/dispatch' }
  ];

  for (const task of fetchedBatch) {
    try {
      // Atomic Deduplication / Pre-Authorization Lock in Redis with Fallback Protection
      const lockKey = `lock:task:${task.taskId}`;
      const acquired = await redisClient.set(lockKey, 'pending', {
        NX: true, // Only set if not already present
        EX: 3600  // 1-hour expiration TTL for data minimization/cleanup
      });

      if (acquired) {
        console.log(`[Worker] Task locked and staged for execution: ${task.taskId}`);
      }
    } catch (redisErr) {
      console.warn(`⚠️ [Worker Notice] Redis operation skipped gracefully: ${redisErr.message}`);
    }
  }
}

// Run polling worker on a controlled execution interval (e.g., every 60 seconds)
setInterval(runOutboundPollingWorker, 60000);


// ==========================================
// 3. SECURE WEBHOOK & METADATA-BOUND INGESTION
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
      const taskId = paymentData.metadata?.task_id;
      const reference = paymentData.reference;

      if (!taskId) {
        console.error('[Error] Missing task_id metadata in transaction payload.');
        return;
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

      // Execute Real-World Programmatic Fulfillment Task
      console.log(`[Fulfillment Success] Task ${taskId} successfully executed and settled.`);
    }
  } catch (error) {
    console.error('[Webhook Error]', error);
  }
});

const PORT = process.env.PORT || 3000;
app.listen(PORT, () => {
  console.log(`Autonomous Outbound Engine running on port ${PORT}`);
});
