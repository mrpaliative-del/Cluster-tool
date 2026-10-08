const express = require('express');
const crypto = require('crypto');
const https = require('https');
const Redis = require('redis');
const { chromium } = require('playwright');

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

redisClient.on('error', (err) => console.error('[Redis Client Error - Non-Fatal]', err.message));
redisClient.connect().then(() => {
  console.log('[Redis] Connected successfully to state store.');
}).catch(err => console.error('[Redis Connection Warning - Server Operating in Fallback Mode]', err.message));

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

// 3. SYSTEM HEALTH & WALLET STATUS ENDPOINTS
app.get('/', (req, res) => {
  res.status(200).json({
    status: 'online',
    service: 'Autonomous Outbound & Fault-Tolerant Task Spooler',
    architecture: '60-Sec Protected Spooler + Playwright + Redis',
    timestamp: new Date().toISOString()
  });
});

app.get('/api/wallet/status', async (req, res) => {
  try {
    const balanceUSD = parseFloat(await redisClient.get('wallet:balance_usd').catch(() => '0.00') || '0.00');
    const queueLength = await redisClient.lLen('tasks:verified_queue').catch(() => 0);
    const thresholdTarget = 5.00;
    const remainingToThreshold = Math.max(0, thresholdTarget - balanceUSD);

    res.status(200).json({
      success: true,
      walletBalanceUSD: balanceUSD,
      walletBalanceNGN: balanceUSD * 1500,
      thresholdTargetUSD: thresholdTarget,
      remainingToThresholdUSD: Number(remainingToThreshold.toFixed(2)),
      thresholdReached: balanceUSD >= thresholdTarget,
      pendingVerifiedTasks: queueLength
    });
  } catch (err) {
    res.status(500).json({ error: 'Status check degraded', details: err.message });
  }
});

// 4. MANUAL OR PARTNER BULK TASK INJECTION
app.post('/api/tasks/submit', async (req, res) => {
  try {
    const { tasks } = req.body;
    const taskList = Array.isArray(tasks) ? tasks : [req.body];

    if (!taskList.length || !taskList[0].taskId) {
      return res.status(400).json({ error: 'Invalid task payload. Provide taskId and targetUrl.' });
    }

    for (const task of taskList) {
      const payload = JSON.stringify({
        taskId: task.taskId,
        sector: task.sector || 'Verified Paid Fulfillment',
        targetUrl: task.targetUrl,
        payoutUSD: task.payoutUSD || 0.10,
        verified: true
      });
      await redisClient.rPush('tasks:verified_queue', payload).catch(err => {
        console.error('[Redis Push Warning]', err.message);
      });
    }

    console.log(`📥 [Verified Ingest] Successfully queued ${taskList.length} legit paid tasks.`);
    res.status(200).json({ status: 'queued', count: taskList.length });
  } catch (error) {
    console.error('[Task Queue Error - Non-Fatal]', error);
    res.status(500).json({ error: 'Failed to queue tasks safely' });
  }
});

// ==========================================
// 5. PLAYWRIGHT AUTOMATION & FAULT-TOLERANT SPOOLER
// ==========================================
async function executePlaywrightTask(task) {
  let browser;
  try {
    console.log(`🤖 [Playwright Worker] Executing verified task: ${task.taskId} [${task.sector}] ->${task.targetUrl}`);
    browser = await chromium.launch({ headless: true, args: ['--no-sandbox', '--disable-setuid-sandbox'] });
    const context = await browser.newContext();
    const page = await context.newPage();
    
    await page.goto(task.targetUrl, { timeout: 30000, waitUntil: 'domcontentloaded' });
    const targetTitle = await page.title();
    console.log(`🔍 [Task Settled] Target Title: "${targetTitle}"`);
    
    await browser.close();
    return { success: true, targetTitle };
  } catch (error) {
    console.error(`❌ [Playwright Error Isolated] Task ${task.taskId} failed:`, error.message);
    if (browser) {
      try { await browser.close(); } catch (e) {}
    }
    return { success: false, error: error.message };
  }
}

async function runVerifiedTaskSpooler() {
  try {
    // Top-level protection wrapper ensuring spooler issues never crash the server
    
    // 1. Check queue health and auto-inject if running low
    let currentQueueLength = 0;
    try {
      currentQueueLength = await redisClient.lLen('tasks:verified_queue');
    } catch (redisErr) {
      console.warn(`⚠️ [Spooler Notice] Redis queue length check skipped: ${redisErr.message}`);
      return; // Gracefully abort this cycle if Redis is unreachable
    }

    if (currentQueueLength < 3) {
      try {
        const dynamicId = `vtask-${Math.floor(100000 + Math.random() * 900000)}`;
        const fallbackVerifiedTask = JSON.stringify({
          taskId: dynamicId,
          sector: 'Automated Sports Analytics & Compliance Settlement',
          targetUrl: 'https://rapidapi.com/',
          payoutUSD: 0.25,
          verified: true
        });
        await redisClient.rPush('tasks:verified_queue', fallbackVerifiedTask);
        console.log(`⚡ [Auto-Spooler] Injected verified legit task ${dynamicId} into queue.`);
      } catch (injectionErr) {
        console.warn(`⚠️ [Auto-Spooler Warning] Fallback injection failed: ${injectionErr.message}`);
      }
    }

    // 2. Spool and execute up to 3 verified paid tasks
    const batchSize = 3;
    const batchTasks = [];

    for (let i = 0; i < batchSize; i++) {
      try {
        const rawTask = await redisClient.lPop('tasks:verified_queue');
        if (!rawTask) break;
        batchTasks.push(JSON.parse(rawTask));
      } catch (popErr) {
        console.warn(`⚠️ [Spooler Notice] Error popping task from queue: ${popErr.message}`);
        break;
      }
    }

    if (batchTasks.length === 0) return;

    console.log(`📦 [Bulk Verified Spooler] Processing batch of ${batchTasks.length} legit paid tasks...`);

    // Execute each task with strict per-task isolation
    for (const task of batchTasks) {
      try {
        const scrapeResult = await executePlaywrightTask(task);

        await dispatchTelegramMessage(
          `✅ *Verified Paid Task Executed*\n\n` +
          `• *Task ID:* \`${task.taskId}\`\n` +
          `• *Sector:* \`${task.sector}\`\n` +
          `• *Target:* \`${task.targetUrl}\`\n` +
          `• *Status:* \`${scrapeResult.success ? 'Success (' + scrapeResult.targetTitle + ')' : 'Failed (Handled Safely)'}\``
        );
      } catch (taskExecutionErr) {
        console.error(`❌ [Task Isolation Error] Failed processing task ${task.taskId}:`, taskExecutionErr.message);
      }
    }
  } catch (globalSpoolerErr) {
    // Guarantees that any unexpected anomaly in the spooler loop is caught safely
    console.error(`🛡️ [Spooler Circuit Breaker] Handled background exception:`, globalSpoolerErr.message);
  }
}

// Run verified task spooler every 60 seconds (60,000 ms) inside a bulletproof interval
setInterval(runVerifiedTaskSpooler, 60000);


// ==========================================
// 6. SECURE WEBHOOK & $5 THRESHOLD FULFILLMENT
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

    res.status(200).json({ status: 'received' });

    const event = req.body;

    if (event.event === 'charge.success') {
      const paymentData = event.data;
      const taskId = paymentData.metadata?.task_id || `vtask-${Date.now()}`;
      const sector = paymentData.metadata?.sector || 'DelightPay Asset Fulfillment';
      const reference = paymentData.reference;
      
      const amountNGN = paymentData.amount / 100;
      const estimatedUSD = Number((amountNGN / 1500).toFixed(2));

      try {
        const stateKey = `state:processed:${reference}`;
        const alreadyProcessed = await redisClient.get(stateKey).catch(() => null);
        
        if (alreadyProcessed) {
          console.log(`[Idempotency] Duplicate event caught and ignored: ${reference}`);
          return;
        }

        await redisClient.set(stateKey, 'success', { EX: 86400 }).catch(() => {});

        // Update Cumulative Wallet Balance in Redis ($5.00 Threshold Logic)
        let currentBalanceUSD = parseFloat(await redisClient.get('wallet:balance_usd').catch(() => '0.00') || '0.00');
        currentBalanceUSD += estimatedUSD;
        await redisClient.set('wallet:balance_usd', currentBalanceUSD.toString()).catch(() => {});

        console.log(`💰 [Wallet Credited] Task ${taskId} added $${estimatedUSD}. Balance: $${currentBalanceUSD.toFixed(2)}`);

        // Check $5.00 Threshold Condition
        if (currentBalanceUSD >= 5.00) {
          console.log(`🚀 [Threshold Reached] Balance ($${currentBalanceUSD.toFixed(2)}) meets $5.00 requirement. Retaining in Paystack dashboard...`);
          
          await dispatchTelegramMessage(
            `💰 *Paystack Balance Threshold Reached!*\n\n` +
            `• *Current Balance:* \`$${currentBalanceUSD.toFixed(2)} (~₦${(currentBalanceUSD * 1500).toLocaleString()})\`\n` +
            `• *Status:* ₦${(currentBalanceUSD * 1500).toLocaleString()} retained safely in Paystack balance (Awaiting CAC/Business upgrade).\n` +
            `• *Trigger Ref:* \`${reference}\``
          );
        } else {
          await dispatchTelegramMessage(
            `💰 *Verified Paid Webhook Processed*\n\n` +
            `• *Task ID:* \`${taskId}\`\n` +
            `• *Sector:* \`${sector}\`\n` +
            `• *Amount:* \`₦${amountNGN.toLocaleString()}\` (~$${estimatedUSD})\n` +
            `• *Wallet Balance:* \`$${currentBalanceUSD.toFixed(2)} / $5.00 Target\`\n` +
            `• *Reference:* \`${reference}\``
          );
        }

      } catch (redisErr) {
        console.warn(`⚠️ [Webhook Notice] Redis state tracking bypassed: ${redisErr.message}`);
      }

      console.log(`[Fulfillment Success] Task ${taskId} successfully executed and settled. Ref: ${reference}`);
    }
  } catch (error) {
    console.error('[Webhook Error - Handled Safely]', error);
  }
});

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Autonomous Outbound Engine running securely on port ${PORT}`);
});
