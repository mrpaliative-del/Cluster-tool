const express = require('express');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const app = express();

// ==========================================
// CONFIG & SECRETS (Loaded from Environment)
// ==========================================
const CLUSTER_SECRET = process.env.CLUSTER_SECRET || 'fallback-secret';
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '';
const AFFILIATE_MARKER = process.env.TRAVELPAYOUTS_MARKER || 'default_marker';

// ==========================================
// LOCAL PERSISTENCE STORAGE LAYER
// ==========================================
const STORAGE_FILE = path.join(__dirname, 'cluster_state.json');

let localData = {
  queue: [],
  state: {}
};

function loadLocalStore() {
  try {
    if (fs.existsSync(STORAGE_FILE)) {
      const raw = fs.readFileSync(STORAGE_FILE, 'utf8');
      localData = JSON.parse(raw);
      if (!Array.isArray(localData.queue)) localData.queue = [];
      if (!localData.state || typeof localData.state !== 'object') localData.state = {};
      console.log(`[Cluster] Loaded state store (${localData.queue.length} targets queued).`);
    }
  } catch (err) {
    console.error('❌ [Storage Error]', err.message);
  }
}

function saveLocalStore() {
  try {
    fs.writeFileSync(STORAGE_FILE, JSON.stringify(localData, null, 2), 'utf8');
  } catch (err) {
    console.error('❌ [Storage Error]', err.message);
  }
}

loadLocalStore();

async function storePush(payload) { 
  localData.queue.push(payload); 
  saveLocalStore(); 
  return localData.queue.length; 
}

async function storePop() { 
  const item = localData.queue.shift() || null; 
  if (item) saveLocalStore(); 
  return item; 
}

// TELEGRAM TELEMETRY ALERT DISPATCHER
async function sendTelegramAlert(text) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text: text, parse_mode: 'Markdown' })
    });
  } catch (err) {}
}

app.use(express.json());

// HEALTH CHECK ENDPOINT
app.get('/', (req, res) => {
  res.status(200).json({
    status: 'online',
    service: 'Autonomous Headless Arbitrage Cluster',
    activeMarker: AFFILIATE_MARKER ? 'Configured & Secured' : 'Missing Marker',
    queueLength: localData.queue.length,
    timestamp: new Date().toISOString()
  });
});

// ==========================================
// AUTONOMOUS TARGET DISCOVERY ENGINE
// ==========================================
async function runAutonomousDiscovery() {
  try {
    console.log(`📡 [Discovery Engine] Scanning public domain vectors for affiliate opportunities...`);
    
    // Inject dynamic search & partner audit flows using your real affiliate marker
    const generatedTargets = [
      {
        targetUrl: `https://www.aviasales.com/search/LOS0112ABV1?marker=${AFFILIATE_MARKER}`,
        requiredMarker: AFFILIATE_MARKER,
        estimatedValueUSD: 85
      }
    ];

    for (const t of generatedTargets) {
      const exists = localData.queue.some(item => item.includes(t.targetUrl));
      if (!exists && localData.queue.length < 30) {
        const task = {
          batchId: `auto_${Date.now()}`,
          taskId: `arb_${Math.random().toString(36).substring(7)}`,
          type: 'affiliate_arbitrage_audit',
          targetUrl: t.targetUrl,
          requiredMarker: t.requiredMarker,
          estimatedValueUSD: t.estimatedValueUSD,
          timestamp: Date.now()
        };
        await storePush(JSON.stringify(task));
      }
    }
  } catch (err) {
    console.error('❌ [Discovery Error]', err.message);
  }

  // Run autonomous discovery cycle every 30 minutes
  setTimeout(runAutonomousDiscovery, 30 * 60 * 1000);
}

// ==========================================
// PLAYWRIGHT HEADLESS WORKER ENGINE
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

async function auditArbitrageTarget(task, page) {
  const hopChain = [];
  page.on('response', response => {
    const req = response.request();
    if (req.isNavigationRequest()) {
      hopChain.push({ url: response.url(), status: response.status() });
    }
  });

  const response = await page.goto(task.targetUrl, { waitUntil: 'domcontentloaded', timeout: 20000 });
  const finalUrl = page.url();
  const finalStatus = response ? response.status() : 0;

  let markerSurvived = true;
  if (task.requiredMarker) {
    markerSurvived = finalUrl.includes(task.requiredMarker);
  }

  const isHealthy = finalStatus < 400 && markerSurvived;

  return {
    success: isHealthy,
    finalUrl,
    finalStatus,
    hopCount: hopChain.length,
    markerSurvived,
    estimatedValueUSD: task.estimatedValueUSD
  };
}

async function runArbitrageWorker() {
  let context = null;
  try {
    let rawTask = await storePop();
    if (!rawTask) {
      setTimeout(runArbitrageWorker, 5000);
      return;
    }

    const task = JSON.parse(rawTask);
    console.log(`🔎 [Worker] Headless audit running on: ${task.targetUrl}`);
    
    const browser = await getSharedBrowser();
    context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
    });
    const page = await context.newPage();

    let result = await auditArbitrageTarget(task, page);
    await context.close();

    if (!result.success) {
      console.warn(`💰 [Monetary Leak Identified!] Risk on ${task.targetUrl} ($${task.estimatedValueUSD})`);
      await sendTelegramAlert(
        `🚨 *Monetary Leakage / Arbitrage Alert*\n\n` +
        `• *Target:* \`${task.targetUrl}\`\n` +
        `• *Final URL:* \`${result.finalUrl || 'N/A'}\`\n` +
        `• *Marker Survived:* \`${result.markerSurvived ? 'Yes' : '❌ STRIPPED'}\`\n` +
        `• *Risk Value:* \`$${task.estimatedValueUSD}\``
      );
    } else {
      console.log(`✅ [Route Secured] Tracking marker intact. Value protected: $${task.estimatedValueUSD}`);
    }

  } catch (err) {
    if (context) { try { await context.close(); } catch (e) {} }
    console.error('❌ [Worker Exception]', err.message);
  }

  setTimeout(runArbitrageWorker, 2000);
}

// Boot background headless processes
setTimeout(runAutonomousDiscovery, 3000);
setTimeout(runArbitrageWorker, 6000);

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Autonomous Headless Arbitrage Cluster active on port ${PORT}`);
});
