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

redisClient.on('error', (err) => console.error('[Redis Client Error - Non-Fatal]', err.message));
redisClient.connect().then(() => {
  console.log('[Redis] Connected successfully to state store.');
}).catch(err => console.error('[Redis Connection Warning - Operating in Memory Fallback Mode]', err.message));

// ==========================================
// RESILIENT IN-MEMORY FALLBACK LAYER
// ==========================================
let redisDegraded = false;
const memoryQueue = [];
const memoryState = new Map();

async function safeRedisGet(key) {
  if (redisDegraded) return memoryState.get(key) || null;
  try {
    return await redisClient.get(key);
  } catch (err) {
    if (err.message && err.message.includes('max requests limit exceeded')) redisDegraded = true;
    return memoryState.get(key) || null;
  }
}

async function safeRedisSet(key, val) {
  memoryState.set(key, val);
  if (redisDegraded) return;
  try {
    await redisClient.set(key, val);
  } catch (err) {
    if (err.message && err.message.includes('max requests limit exceeded')) redisDegraded = true;
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
    if (err.message && err.message.includes('max requests limit exceeded')) redisDegraded = true;
    memoryQueue.push(payload);
    return memoryQueue.length;
  }
}

async function safeRedisPop(queueName) {
  if (redisDegraded) return memoryQueue.shift() || null;
  try {
    return await redisClient.lPop(queueName);
  } catch (err) {
    if (err.message && err.message.includes('max requests limit exceeded')) redisDegraded = true;
    return memoryQueue.shift() || null;
  }
}

// CONFIG & SECRETS
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';
const CLUSTER_SECRET = process.env.CLUSTER_SECRET || 'your-cluster-hmac-secret';

// RAW BODY CAPTURE FOR PAYSTACK HMAC
app.use('/api/webhook/paystack', express.json({
  verify: (req, res, buf) => { req.rawBody = buf; }
}));

app.use(express.json());

// HEALTH & METRICS ENDPOINT
app.get('/', (req, res) => {
  status: 'online',
  service: '4-Pillar Autonomous Technical Compliance Cluster',
  mode: redisDegraded ? 'In-Memory Fallback Active' : 'Standard Redis Connected',
  timestamp: new Date().toISOString()
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

    console.log(`💰 [Escrow Funded] NGN ${amountPaidNGN} received from ${customerEmail}`);
    const currentBalance = parseFloat(await safeRedisGet('wallet:escrow_balance_ngn') || '0.00');
    await safeRedisSet('wallet:escrow_balance_ngn', (currentBalance + amountPaidNGN).toString());
  }

  res.sendStatus(200);
});

// MULTI-PILLAR BATCH TASK INGESTION ENDPOINT
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
      type: task.type, // affiliate_redirect | seo_og_drift | mixed_content | widget_liveness
      targetUrl: task.targetUrl,
      expectedMarker: task.expectedMarker || null,
      selector: task.selector || null,
      timestamp: Date.now()
    });

    await safeRedisPush('tasks:verified_queue', payload);
    queuedCount++;
  }

  res.status(200).json({ success: true, message: `Successfully queued ${queuedCount} tasks from bundle.` });
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

  return {
    success: true,
    type: 'affiliate_redirect',
    finalUrl,
    finalStatus,
    redirectHopCount: redirectChain.length,
    redirectChain,
    markerValid: markerFound
  };
}

// Pillar 2: Programmatic SEO & OpenGraph Tag Drift Verification
async function auditOpenGraphTags(task, page) {
  const response = await page.goto(task.targetUrl, { waitUntil: 'domcontentloaded', timeout: 15000 });
  const metaTags = await page.evaluate(() => {
    const tags = {};
    document.querySelectorAll('meta').forEach(meta => {
      const prop = meta.getAttribute('property') || meta.getAttribute('name');
      const content = meta.getAttribute('content');
      if (prop) tags[prop] = content;
    });
    return tags;
  });

  const hasOgImage = !!metaTags['og:image'];
  const hasTitle = !!metaTags['og:title'] || !!document.title;

  return {
    success: true,
    type: 'seo_og_drift',
    status: response ? response.status() : 0,
    metaTags,
    hasOgImage,
    hasTitle
  };
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
  return {
    success: true,
    type: 'mixed_content',
    status: response ? response.status() : 0,
    isSecure: insecureRequests.length === 0,
    insecureRequests
  };
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

  return {
    success: mounted,
    type: 'widget_liveness',
    selectorChecked: selector,
    widgetMounted: mounted,
    error: errorMsg
  };
}

// DYNAMIC TASK ROUTER DISPATCHER
async function executeTaskRouter(task, page) {
  switch (task.type) {
    case 'affiliate_redirect':
      return await auditRedirectChain(task, page);
    case 'seo_og_drift':
      return await auditOpenGraphTags(task, page);
    case 'mixed_content':
      return await auditMixedContent(task, page);
    case 'widget_liveness':
      return await auditWidgetSelector(task, page);
    default:
      throw new Error(`Unsupported task type: ${task.type}`);
  }
}

// WORKER SPOOLER LOOP
async function runAuditSpooler() {
  let context = null;
  try {
    let rawTask = await safeRedisPop('tasks:verified_queue');
    if (!rawTask) {
      setTimeout(runAuditSpooler, 4000);
      return;
    }

    const task = JSON.parse(rawTask);
    console.log(`🔍 [Processing Task] ID: ${task.taskId} | Type: ${task.type} | URL: ${task.targetUrl}`);
    
    const browser = await getSharedBrowser();
    context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    });
    const page = await context.newPage();

    const auditResult = await executeTaskRouter(task, page);
    await context.close();

    const receipt = {
      batchId: task.batchId,
      taskId: task.taskId,
      ...auditResult,
      auditTimestamp: new Date().toISOString()
    };

    console.log(`✅ [Audit Receipt Generated] Task ${receipt.taskId} (${receipt.type}) completed successfully.`);
    // TODO: Forward receipt to downstream database or webhook aggregator

  } catch (err) {
    if (context) { try { await context.close(); } catch (e) {} }
    console.error('❌ [Worker Execution Error]', err.message);
  }

  setTimeout(runAuditSpooler, 1000);
}

setTimeout(runAuditSpooler, 2000);

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`4-Pillar Compliance Cluster active on port ${PORT}`);
});
