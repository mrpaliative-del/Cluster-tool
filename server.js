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
// RESILIENT MULTI-VERTICAL AFFILIATE ASSET MATRIX
// ==========================================
const AFFILIATE_ASSET_MATRIX = [
  // --- Travel Corridors (Aviasales Engine) ---
  { vertical: 'flight', domain: 'https://www.aviasales.com/', path: 'search/LOS0112ABV1', value: 85, region: 'Flight (Lagos - Abuja)' },
  { vertical: 'flight', domain: 'https://www.aviasales.com/', path: 'search/LOS2012LHR1', value: 350, region: 'Flight (Lagos - London)' },
  { vertical: 'flight', domain: 'https://www.aviasales.com/', path: 'search/LOS2212DXB1', value: 320, region: 'Flight (Lagos - Dubai)' },
  { vertical: 'hotel', domain: 'https://www.aviasales.com/', path: 'search/LOS0112ABV1', value: 180, region: 'Hotel Corridor (Lagos Hub)' },

  // --- E-Commerce & Tech Hardware (Amazon) ---
  { vertical: 'retail', domain: 'https://www.amazon.com/', path: 's?k=developer+laptop+stand', value: 45, region: 'Tech Hardware (Amazon Hub)' },
  { vertical: 'retail', domain: 'https://www.amazon.com/', path: 's?k=portable+monitor+usb+c', value: 95, region: 'Tech Gear (Retail Hub)' },

  // --- Cloud Hosting & Developer Tools (SaaS) ---
  { vertical: 'saas', domain: 'https://www.digitalocean.com/?ref=', path: AFFILIATE_MARKER, value: 50, region: 'Cloud Infrastructure (DigitalOcean)' }
];

// ==========================================
// ROTATING USER-AGENT POOL
// ==========================================
const USER_AGENTS = [
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2.1 Safari/605.1.15',
  'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0'
];

// ==========================================
// LOCAL PERSISTENCE STORAGE LAYER & STATS
// ==========================================
const STORAGE_FILE = path.join(__dirname, 'cluster_state.json');

let localData = {
  queue: [],
  state: {}
};

let dailyStats = {
  auditsCompleted: 0,
  valueProtectedUSD: 0,
  leaksIdentified: 0,
  startTime: Date.now()
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
async function sendTelegramAlert(title, task, result) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
    console.warn('⚠️ [Telegram] Skipped alert: Token or Chat ID is missing in environment variables.');
    return;
  }
  
  const icon = result.success ? '✅' : '🚨';
  const text = 
    `${icon} ${title}\n\n` +
    `• Target URL: ${task.targetUrl}\n` +
    `• Final Status: ${result.finalStatus || 'N/A'}\n` +
    `• Attribution Survived: ${result.markerSurvived ? 'Yes (Protected)' : 'STRIPPED'}\n` +
    `• Redirect Hops: ${result.hopCount}\n` +
    `• Estimated Value: $${task.estimatedValueUSD}\n` +
    `• Timestamp: ${new Date().toISOString()}`;

  try {
    const response = await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text: text })
    });

    const data = await response.json();
    if (!data.ok) {
      console.error('❌ [Telegram API Error Description]', data.description);
    } else {
      console.log(`📤 [Telegram] Alert successfully dispatched for ${task.targetUrl}`);
    }
  } catch (err) {
    console.error('❌ [Telegram Network Error]', err.message);
  }
}

// DAILY REVENUE PROTECTION SUMMARY CRON
async function sendDailySummaryReport() {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;

  const uptimeHours = ((Date.now() - dailyStats.startTime) / (1000 * 60 * 60)).toFixed(1);
  const text = 
    `📊 *Autonomous Cluster 24-Hour Guardian Report*\n\n` +
    `• Uptime Window: ${uptimeHours} hours\n` +
    `• Total Assets Audited: ${dailyStats.auditsCompleted}\n` +
    `• Total Revenue Protected: $${dailyStats.valueProtectedUSD}\n` +
    `• Attribution Leaks Caught: ${dailyStats.leaksIdentified}\n` +
    `• Cluster Status: Operational & Secured`;

  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text: text })
    });
  } catch (err) {
    console.error('❌ [Telegram Summary Error]', err.message);
  }

  setTimeout(sendDailySummaryReport, 24 * 60 * 60 * 1000);
}

setTimeout(sendDailySummaryReport, 24 * 60 * 60 * 1000);

app.use(express.json());

// HEALTH CHECK ENDPOINT
app.get('/', (req, res) => {
  res.status(200).json({
    status: 'online',
    service: 'Autonomous Headless Multi-Vertical Affiliate Cluster',
    activeToken: AFFILIATE_MARKER ? 'Configured & Secured' : 'Missing Token',
    queueLength: localData.queue.length,
    stats: dailyStats,
    timestamp: new Date().toISOString()
  });
});

// ==========================================
// ROBUST AUTONOMOUS TARGET DISCOVERY ENGINE
// ==========================================
async function runAutonomousDiscovery() {
  let discoveredCount = 0;

  if (localData.queue.length < 25) {
    const asset = AFFILIATE_ASSET_MATRIX[Math.floor(Math.random() * AFFILIATE_ASSET_MATRIX.length)];
    
    let fallbackUrl = '';
    if (asset.vertical === 'flight' || asset.vertical === 'hotel') {
      fallbackUrl = `${asset.domain}${asset.path}?marker=${AFFILIATE_MARKER}`;
    } else if (asset.vertical === 'retail') {
      fallbackUrl = `${asset.domain}${asset.path}&tag=${AFFILIATE_MARKER}`;
    } else if (asset.vertical === 'saas') {
      fallbackUrl = `${asset.domain}${asset.path}`;
    }

    const exists = localData.queue.some(item => item.includes(fallbackUrl));
    if (!exists && fallbackUrl) {
      await storePush(JSON.stringify({
        batchId: `auto_matrix_${Date.now()}`,
        taskId: `arb_${Math.random().toString(36).substring(7)}`,
        type: `affiliate_${asset.vertical}_audit`,
        targetUrl: fallbackUrl,
        requiredMarker: AFFILIATE_MARKER,
        estimatedValueUSD: asset.value,
        timestamp: Date.now()
      }));
      console.log(`🚀 [Discovery Engine] Injected [${asset.region}] audit target ($${asset.value})`);
      discoveredCount++;
    }
  }

  setTimeout(runAutonomousDiscovery, 30 * 1000);
}

// ==========================================
// PLAYWRIGHT HEADLESS WORKER ENGINE (CONCURRENT)
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

// Precise Parameter-Level Attribution Verification (Supports marker, tag, and ref)
function verifyAttributionMarker(finalUrl, requiredMarker) {
  if (!requiredMarker) return true;
  try {
    const parsedFinal = new URL(finalUrl);
    const markerParam = parsedFinal.searchParams.get('marker');
    const tagParam = parsedFinal.searchParams.get('tag');
    const refParam = parsedFinal.searchParams.get('ref');
    const aidParam = parsedFinal.searchParams.get('a_id');
    return markerParam === requiredMarker || tagParam === requiredMarker || refParam === requiredMarker || aidParam === requiredMarker;
  } catch (err) {
    return finalUrl.includes(requiredMarker);
  }
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

  const markerSurvived = verifyAttributionMarker(finalUrl, task.requiredMarker);
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

async function runArbitrageWorker(workerId) {
  let context = null;
  try {
    let rawTask = await storePop();
    if (!rawTask) {
      setTimeout(() => runArbitrageWorker(workerId), 4000);
      return;
    }

    const task = JSON.parse(rawTask);
    console.log(`🔎 [Worker #${workerId}] Headless audit running on: ${task.targetUrl}`);
    
    const browser = await getSharedBrowser();
    const randomUserAgent = USER_AGENTS[Math.floor(Math.random() * USER_AGENTS.length)];
    
    context = await browser.newContext({ userAgent: randomUserAgent });
    const page = await context.newPage();

    let result = await auditArbitrageTarget(task, page);
    await context.close();

    dailyStats.auditsCompleted++;
    if (result.success) {
      dailyStats.valueProtectedUSD += task.estimatedValueUSD;
      console.log(`✅ [Worker #${workerId}] Target Secured. Value protected: $${task.estimatedValueUSD}`);
    } else {
      dailyStats.leaksIdentified++;
      console.warn(`💰 [Worker #${workerId}] Attribution Leak Identified on ${task.targetUrl} ($${task.estimatedValueUSD})`);
      await sendTelegramAlert('Attribution Leak / Arbitrage Alert', task, result);
    }

  } catch (err) {
    if (context) { try { await context.close(); } catch (e) {} }
    console.error(`❌ [Worker #${workerId} Exception]`, err.message);
  }

  setTimeout(() => runArbitrageWorker(workerId), 2000);
}

// Boot background headless processes (Discovery + 2 Concurrent Workers)
setTimeout(runAutonomousDiscovery, 3000);
setTimeout(() => runArbitrageWorker(1), 5000);
setTimeout(() => runArbitrageWorker(2), 7000);

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Autonomous Headless Multi-Vertical Cluster active on port ${PORT}`);
});
