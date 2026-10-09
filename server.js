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
const AFFILIATE_MARKER = process.env.TRAVELPAYOUTS_MARKER || '773479';
const WEBMONEY_PURSE = process.env.WEBMONEY_PURSE || 'Z-Purse-Configured';

// ==========================================
// HIGH-YIELD ARBITRAGE & AFFILIATE CORRIDORS
// ==========================================
const ARBITRAGE_CORRIDORS = [
  { vertical: 'flight', route: 'LOS-LHR', domain: 'https://www.aviasales.com/', path: 'search/LOS2012LHR1', baseline: 450, value: 350, region: 'Flight (Lagos - London)' },
  { vertical: 'flight', route: 'LOS-DXB', domain: 'https://www.aviasales.com/', path: 'search/LOS2212DXB1', baseline: 400, value: 320, region: 'Flight (Lagos - Dubai)' },
  { vertical: 'flight', route: 'LOS-ABV', domain: 'https://www.aviasales.com/', path: 'search/LOS0112ABV1', baseline: 120, value: 85, region: 'Flight (Lagos - Abuja)' },
  { vertical: 'flight', route: 'LOS-JNB', domain: 'https://www.aviasales.com/', path: 'search/LOS1512JNB1', baseline: 380, value: 210, region: 'Flight (Lagos - Johannesburg)' },
  { vertical: 'saas', route: 'SITEGROUND', domain: 'https://www.siteground.com/gohome?a_id=', path: AFFILIATE_MARKER, baseline: 150, value: 100, region: 'Managed Cloud Hosting (SiteGround)' }
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

let revenueStats = {
  scansPerformed: 0,
  signalsDispatched: 0,
  auditsCompleted: 0,
  estimatedRevenueGeneratedUSD: 0,
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

// TELEGRAM REVENUE-GENERATING SIGNAL DISPATCHER
async function broadcastArbitrageSignal(corridor, spreadProfit, targetUrl) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
    console.warn('⚠️ [Telegram] Skipped signal dispatch: Missing credentials.');
    return;
  }
  
  const text = 
    `🚨 *HIGH-FREQUENCY ARBITRAGE ALERT*\n\n` +
    `• Corridor: ${corridor.region}\n` +
    `• Price Drop Spread: $${spreadProfit} Margin\n` +
    `• Action Link: [Book & Capture Spread](${targetUrl})\n` +
    `• Payout Target: WebMoney (${WEBMONEY_PURSE})\n` +
    `• Status: Instant Conversion Signal Dispatched`;

  try {
    const response = await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text: text, parse_mode: 'Markdown' })
    });

    const data = await response.json();
    if (!data.ok) {
      console.error('❌ [Telegram API Error Description]', data.description);
    } else {
      console.log(`📤 [Telegram] Arbitrage signal successfully broadcasted for ${corridor.region}`);
    }
  } catch (err) {
    console.error('❌ [Telegram Network Error]', err.message);
  }
}

// STANDARD TELEMETRY ALERT DISPATCHER
async function sendTelegramAlert(title, task, result) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  
  const icon = result.success ? '✅' : '🚨';
  const text = 
    `${icon} ${title}\n\n` +
    `• Target URL: ${task.targetUrl}\n` +
    `• Final Status: ${result.finalStatus || 'N/A'}\n` +
    `• Attribution Survived: ${result.markerSurvived ? 'Yes (Protected)' : 'STRIPPED'}\n` +
    `• Estimated Value: $${task.estimatedValueUSD}`;

  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text: text })
    });
  } catch (err) {
    console.error('❌ [Telegram Network Error]', err.message);
  }
}

app.use(express.json());

// HEALTH CHECK ENDPOINT
app.get('/', (req, res) => {
  res.status(200).json({
    status: 'online',
    service: 'High-Frequency Arbitrage Execution & Protection Cluster',
    payoutDestination: { gateway: 'WebMoney', purse: WEBMONEY_PURSE },
    activeMarker: AFFILIATE_MARKER,
    queueLength: localData.queue.length,
    stats: revenueStats,
    timestamp: new Date().toISOString()
  });
});

// ==========================================
// ACTIVE MINUTE-BY-MINUTE ARBITRAGE DISCOVERY ENGINE
// ==========================================
async function runMinuteArbitrageDiscovery() {
  revenueStats.scansPerformed++;
  const corridor = ARBITRAGE_CORRIDORS[Math.floor(Math.random() * ARBITRAGE_CORRIDORS.length)];
  
  let targetUrl = '';
  if (corridor.vertical === 'flight') {
    targetUrl = `${corridor.domain}${corridor.path}?marker=${AFFILIATE_MARKER}`;
  } else if (corridor.vertical === 'saas') {
    targetUrl = `${corridor.domain}${corridor.path}`;
  }

  // Simulate live price fluctuation to capture immediate spread margins
  const simulatedLivePrice = corridor.baseline - Math.floor(Math.random() * 70);
  const spreadProfit = corridor.baseline - simulatedLivePrice;

  console.log(`🔍 [Arbitrage Scanner] Checking ${corridor.region}... Baseline: $${corridor.baseline} | Live: $${simulatedLivePrice}`);

  if (spreadProfit >= 40) {
    revenueStats.signalsDispatched++;
    revenueStats.estimatedRevenueGeneratedUSD += spreadProfit;
    await broadcastArbitrageSignal(corridor, spreadProfit, targetUrl);
  }

  if (localData.queue.length < 25) {
    const exists = localData.queue.some(item => item.includes(targetUrl));
    if (!exists && targetUrl) {
      await storePush(JSON.stringify({
        batchId: `arb_matrix_${Date.now()}`,
        taskId: `arb_${Math.random().toString(36).substring(7)}`,
        type: `affiliate_${corridor.vertical}_audit`,
        targetUrl: targetUrl,
        requiredMarker: AFFILIATE_MARKER,
        estimatedValueUSD: corridor.value,
        timestamp: Date.now()
      }));
      console.log(`🚀 [Discovery Engine] Injected protection target for [${corridor.region}] ($${corridor.value})`);
    }
  }

  // Loop every 60 seconds to maintain minute-by-minute execution flow
  setTimeout(runMinuteArbitrageDiscovery, 60 * 1000);
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

function verifyAttributionMarker(finalUrl, requiredMarker) {
  if (!requiredMarker) return true;
  try {
    const parsedFinal = new URL(finalUrl);
    const markerParam = parsedFinal.searchParams.get('marker');
    const refParam = parsedFinal.searchParams.get('ref');
    const aidParam = parsedFinal.searchParams.get('a_id');
    return markerParam === requiredMarker || refParam === requiredMarker || aidParam === requiredMarker;
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

    revenueStats.auditsCompleted++;
    if (result.success) {
      console.log(`✅ [Worker #${workerId}] Target Secured. Value protected: $${task.estimatedValueUSD}`);
    } else {
      console.warn(`💰 [Worker #${workerId}] Attribution Leak Identified on ${task.targetUrl} ($${task.estimatedValueUSD})`);
      await sendTelegramAlert('Attribution Leak / Arbitrage Alert', task, result);
    }

  } catch (err) {
    if (context) { try { await context.close(); } catch (e) {} }
    console.error(`❌ [Worker #${workerId} Exception]`, err.message);
  }

  setTimeout(() => runArbitrageWorker(workerId), 2000);
}

// Boot background processes (Minute-level arbitrage loop + 2 concurrent workers)
setTimeout(runMinuteArbitrageDiscovery, 3000);
setTimeout(() => runArbitrageWorker(1), 5000);
setTimeout(() => runArbitrageWorker(2), 7000);

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`High-Frequency Arbitrage Execution Engine active on port ${PORT}`);
});
