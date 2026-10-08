const express = require('express');
const crypto = require('crypto');
const Redis = require('redis');
const { chromium } = require('playwright');

const app = express();

// Sanitize REDIS_URL
const rawRedisUrl = process.env.REDIS_URL || 'redis://localhost:6379';
const sanitizedRedisUrl = rawRedisUrl.replace(/^[\s\u200e\u200f\u202a-\u202e]+/, '').trim();

const redisClient = Redis.createClient({ 
  url: sanitizedRedisUrl,
  socket: {
    tls: sanitizedRedisUrl.startsWith('rediss://'),
    rejectUnauthorized: false
  }
});

let redisDegraded = false;

redisClient.on('error', (err) => {
  if (err.message && (err.message.includes('max requests limit exceeded') || err.message.includes('OOM'))) {
    redisDegraded = true;
  }
  console.error('[Redis Client Error]', err.message);
});

redisClient.connect().then(() => {
  console.log('[Redis] Connected successfully to state store.');
}).catch(err => {
  redisDegraded = true;
  console.error('[Redis Connection Warning - Operating in Memory Fallback Mode]', err.message);
});

// ==========================================
// RESILIENT IN-MEMORY FALLBACK LAYER
// ==========================================
const memoryQueue = [];
const memoryState = new Map();

async function safeRedisGet(key) {
  if (redisDegraded) return memoryState.get(key) || null;
  try {
    return await redisClient.get(key);
  } catch (err) {
    redisDegraded = true;
    return memoryState.get(key) || null;
  }
}

async function safeRedisSet(key, val) {
  memoryState.set(key, val);
  if (redisDegraded) return;
  try {
    await redisClient.set(key, val);
  } catch (err) {
    redisDegraded = true;
  }
}

async function safeRedisPush(queueName, payload) {
  if (redisDegraded) {
    memoryQueue.push(payload);
    return memoryQueue.length;
  }
  try {
    return await redisClient.rPush(queueName, payload);
  } catch (err) {
    redisDegraded = true;
    memoryQueue.push(payload);
    return memoryQueue.length;
  }
}

async function safeRedisPop(queueName) {
  if (redisDegraded) return memoryQueue.shift() || null;
  try {
    return await redisClient.lPop(queueName);
  } catch (err) {
    redisDegraded = true;
    return memoryQueue.shift() || null;
  }
}

// CONFIG & SECRETS
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';
const CLUSTER_SECRET = process.env.CLUSTER_SECRET || 'your-cluster-hmac-secret';
const TARGET_SITEMAP_URL = process.env.TARGET_SITEMAP_URL || '';
const PRODUCTION_BASE_URL = process.env.PRODUCTION_BASE_URL || process.env.RENDER_EXTERNAL_URL || 'https://cluster-tool.onrender.com';
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '';

// TELEGRAM ALERT HELPER
async function sendTelegramAlert(text) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  try {
    const url = `https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`;
    await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        chat_id: TELEGRAM_CHAT_ID,
        text: text,
        parse_mode: 'Markdown'
      })
    });
  } catch (err) {
    console.error('❌ [Telegram Alert Error]', err.message);
  }
}

// RAW BODY CAPTURE FOR PAYSTACK HMAC
app.use('/api/webhook/paystack', express.json({
  verify: (req, res, buf) => { req.rawBody = buf; }
}));

app.use(express.json());

// HEALTH & METRICS ENDPOINT
app.get('/', (req, res) => {
  res.status(200).json({
    status: 'online',
    service: 'Strictly Real-World Production Compliance Cluster',
    mode: redisDegraded ? 'In-Memory Fallback Active' : 'Standard Redis Connected',
    timestamp: new Date().toISOString()
  });
});

// PAYSTACK ESCROW FUNDING WEBHOOK
app.post('/api/webhook/paystack', async (req, res) => {
  const hash = crypto.createHmac('sha512', PAYSTACK_SECRET_KEY)
    .update(req.rawBody || Buffer.from(''))
    .digest('hex');

  if (hash !== req.headers['x-paystack-signature']) {
    return res.status(401).json({ success: false, error: 'Invalid Paystack Signature' });
  }

  const event = req.body;
  if (event && event.event === 'charge.success') {
    const data = event.data;
    const amountPaidNGN = data.amount / 100;
    const customerEmail = data.customer.email;

    console.log(`💰 [Escrow Funded] NGN ${amountPaidNGN} received from${customerEmail}`);
    const currentBalance = parseFloat(await safeRedisGet('wallet:escrow_balance_ngn') || '0.00');
    await safeRedisSet('wallet:escrow_balance_ngn', (currentBalance + amountPaidNGN).toString());
    
    await sendTelegramAlert(`💰 *Escrow Funded*\nReceived NGN ${amountPaidNGN} from \`${customerEmail}\``);
  }

  res.sendStatus(200);
});

// MANUAL/EXTERNAL BATCH TASK INGESTION ENDPOINT
app.post('/api/tasks/submit-bundle', async (req, res) => {
  const signature = req.headers['x-escrow-signature'];
  const computedSig = crypto.createHmac('sha256', CLUSTER_SECRET)
    .update(JSON.stringify(req.body))
    .digest('hex');

  if (signature !== computedSig) {
    return res.status(403).json({ success: false, error: 'Unauthorized: Invalid Escrow Signature' });
  }

  const { batchId, tasks } = req.body;
  if (!Array.isArray(tasks) || tasks.length === 0) {
    return res.status(400).json({ success: false, error: 'Invalid or empty task bundle array' });
  }

  let queuedCount = 0;
  for (const task of tasks) {
    if (!task.taskId || !task.type || !task.targetUrl) continue;
    
    const payload = JSON.stringify({
      batchId: batchId || 'adhoc_batch',
      taskId: task.taskId,
      type: task.type,
      targetUrl: task.targetUrl,
      expectedMarker: task.expectedMarker || null,
      selector: task.selector || null,
      timestamp: Date.now()
    });

    await safeRedisPush('tasks:verified_queue', payload);
    queuedCount++;
  }

  res.status(200).json({ success: true, message: `Successfully queued ${queuedCount} real tasks from bundle.` });
});

// ==========================================
// PLAYWRIGHT 4-PILLAR EXECUTION ROUTINES
// ==========================================

let sharedBrowser = null;
async function getSharedBrowser() {
  if (!sharedBrowser || !sharedBrowser.isConnected()) {
    sharedBrowser = await chromium.launch({
      headless: true,
      args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
    });
  }
  return sharedBrowser;
}

// Pillar 1: Affiliate & Deep-Link Redirect Chain Auditing
async function auditRedirectChain(task, page) {
  const redirectChain = [];
  page.on('response', response => {
    const req = response.request();
    if (req.isNavigationRequest()) {
      redirectChain.push({ url: response.url(), status: response.status() });
    }
  });

  const response = await page.goto(task.targetUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
  const finalUrl = page.url();
  const finalStatus = response ? response.status() : 0;
  
  let markerFound = true;
  if (task.expectedMarker) {
    const content = await page.content();
    markerFound = content.includes(task.expectedMarker);
  }

  const isHealthy = finalStatus < 400 && markerFound;
  return { success: isHealthy, type: 'affiliate_redirect', finalUrl, finalStatus, redirectHopCount: redirectChain.length, redirectChain, markerValid: markerFound };
}

// Pillar 2: Programmatic SEO & OpenGraph Tag Drift Verification
async function auditOpenGraphTags(task, page) {
  const response = await page.goto(task.targetUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
  
  const evaluation = await page.evaluate(() => {
    const tags = {};
    document.querySelectorAll('meta').forEach(meta => {
      const prop = meta.getAttribute('property') || meta.getAttribute('name');
      const content = meta.getAttribute('content');
      if (prop) tags[prop] = content;
    });
    return {
      metaTags: tags,
      pageTitle: document.title || ''
    };
  });

  const hasOgImage = !!evaluation.metaTags['og:image'];
  const hasTitle = !!evaluation.metaTags['og:title'] || !!evaluation.pageTitle;
  const isHealthy = hasOgImage && hasTitle;

  return { success: isHealthy, type: 'seo_og_drift', status: response ? response.status() : 0, metaTags: evaluation.metaTags, hasOgImage, hasTitle };
}

// Pillar 3: Mixed Content & Secure Asset Compliance Scans
async function auditMixedContent(task, page) {
  const insecureRequests = [];
  page.on('request', request => {
    const url = request.url();
    if (task.targetUrl.startsWith('https://') && url.startsWith('http://')) {
      insecureRequests.push(url);
    }
  });

  const response = await page.goto(task.targetUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
  const isSecure = insecureRequests.length === 0;

  return { success: isSecure, type: 'mixed_content', status: response ? response.status() : 0, isSecure, insecureRequests };
}

// Pillar 4: Third-Party Widget & Payment Gateway DOM Liveness
async function auditWidgetSelector(task, page) {
  const selector = task.selector || 'iframe';
  let mounted = false;
  let errorMsg = null;
  try {
    await page.goto(task.targetUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
    await page.waitForSelector(selector, { timeout: 6000 });
    mounted = true;
  } catch (err) {
    errorMsg = err.message;
  }
  return { success: mounted, type: 'widget_liveness', selectorChecked: selector, widgetMounted: mounted, error: errorMsg };
}

async function executeTaskRouter(task, page) {
  switch (task.type) {
    case 'affiliate_redirect': return await auditRedirectChain(task, page);
    case 'seo_og_drift': return await auditOpenGraphTags(task, page);
    case 'mixed_content': return await auditMixedContent(task, page);
    case 'widget_liveness': return await auditWidgetSelector(task, page);
    default: throw new Error(`Unsupported task type: ${task.type}`);
  }
}

// ==========================================
// STRICTLY REAL PRODUCTION FEEDER
// ==========================================
async function runSelfDiscoveryFeeder() {
  try {
    let discoveredUrls = [];

    // 1. Pull exclusively from real Sitemap if configured
    if (TARGET_SITEMAP_URL) {
      try {
        const res = await fetch(TARGET_SITEMAP_URL);
        const xmlText = await res.text();
        const matches = xmlText.match(/<loc>(.*?)<\/loc>/g);
        if (matches && matches.length > 0) {
          discoveredUrls = matches.map(m => m.replace(/<\/?loc>/g, '')).slice(0, 10);
        }
      } catch (e) {
        console.error('❌ [Sitemap Fetch Error]', e.message);
      }
    }

    // 2. Otherwise, strictly target the actual live base URL root
    if (discoveredUrls.length === 0 && PRODUCTION_BASE_URL) {
      discoveredUrls = [PRODUCTION_BASE_URL];
    }

    if (discoveredUrls.length > 0) {
      for (const url of discoveredUrls) {
        const task = {
          batchId: `live_real_${Date.now()}`,
          taskId: `real_${Math.random().toString(36).substring(7)}`,
          type: 'mixed_content',
          targetUrl: url,
          expectedMarker: null,
          selector: null,
          timestamp: Date.now()
        };
        await safeRedisPush('tasks:verified_queue', JSON.stringify(task));
      }
      console.log(`🌐 [Feeder] Dispatched ${discoveredUrls.length} strictly real production audit targets.`);
    }
  } catch (err) {
    console.error('❌ [Production Feeder Error]', err.message);
  }

  // Check every 60 seconds
  setTimeout(runSelfDiscoveryFeeder, 60 * 1000);
}

// WORKER SPOOLER LOOP
async function runAuditSpooler() {
  let context = null;
  try {
    let rawTask = await safeRedisPop('tasks:verified_queue');
    if (!rawTask) {
      setTimeout(runAuditSpooler, 3000);
      return;
    }

    const task = JSON.parse(rawTask);
    console.log(`🔍 [Processing Real Production Task] ID: ${task.taskId} | Type: ${task.type} \vert{} URL:${task.targetUrl}`);
    
    const browser = await getSharedBrowser();
    context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    });
    const page = await context.newPage();

    const auditResult = await executeTaskRouter(task, page);
    await context.close();

    if (!auditResult.success) {
      console.warn(`⚠️ [Real-World Compliance Failure] Task ${task.taskId} (${task.type}) failed verification.`);
      await sendTelegramAlert(
        `🚨 *Real-World Compliance Failure*\n\n` +
        `• *Pillar:* \`${task.type}\`\n` +
        `• *Target:* \`${task.targetUrl}\`\n` +
        `• *Task ID:* \`${task.taskId}\`\n` +
        `• *Status:* \`Failed / Non-Compliant\``
      );
    } else {
      console.log(`✅ [Audit Passed] Real production task ${task.taskId} (${task.type}) verified successfully.`);
    }

  } catch (err) {
    if (context) { try { await context.close(); } catch (e) {} }
    console.error('❌ [Worker Execution Error]', err.message);
  }

  setTimeout(runAuditSpooler, 1000);
}

// Kick off loops on boot
setTimeout(runSelfDiscoveryFeeder, 5000);
setTimeout(runAuditSpooler, 2000);

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Strictly Real-World Production Compliance Cluster active on port ${PORT}`);
});
