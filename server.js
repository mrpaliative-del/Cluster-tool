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
// GLOBAL & REGIONAL ROUTE MATRIX
// ==========================================
const GLOBAL_ROUTE_MATRIX = [
  { route: 'LOS0112ABV1', value: 85, region: 'Domestic (Lagos - Abuja)' },
  { route: 'LOS1012ACC1', value: 120, region: 'Regional (Lagos - Accra)' },
  { route: 'LOS1512JNB1', value: 210, region: 'Continental (Lagos - Johannesburg)' },
  { route: 'LOS2012LHR1', value: 350, region: 'Intercontinental (Lagos - London)' },
  { route: 'LOS2212DXB1', value: 320, region: 'Intercontinental (Lagos - Dubai)' },
  { route: 'ABV2512IST1', value: 290, region: 'Intercontinental (Abuja - Istanbul)' },
  { route: 'LOS0512JFK1', value: 450, region: 'Intercontinental (Lagos - New York)' }
];

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
async function sendTelegramAlert(title, task, result) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  
  const icon = result.success ? '✅' : '🚨';
  const text = 
    `${icon} *${title}*\n\n` +
    `• *Target URL:* \`${task.targetUrl}\`\n` +
    `• *Final Status:* \`${result.finalStatus || 'N/A'}\`\n` +
    `• *Marker Survived:* \`${result.markerSurvived ? 'Yes (Protected)' : '❌ STRIPPED'}\`\n` +
    `• *Redirect Hops:* \`${result.hopCount}\`\n` +
    `• *Estimated Value:* \`$${task.estimatedValueUSD}\`\n` +
    `• *Timestamp:* \`${new Date().toISOString()}\``;

  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text: text, parse_mode: 'Markdown' })
    });
  } catch (err) {
    console.error('❌ [Telegram Error]', err.message);
  }
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
// ROBUST AUTONOMOUS TARGET DISCOVERY ENGINE
// ==========================================
async function runAutonomousDiscovery() {
  let discoveredCount = 0;

  try {
    console.log(`📡 [Discovery Engine] Sweeping public domain vectors for travel & affiliate opportunities...`);
    
    const publicSearchQueries = [
      'https://html.duckduckgo.com/html/?q=travel+booking+resources+blog',
      'https://html.duckduckgo.com/html/?q=flight+aggregator+partners+directory'
    ];

    const randomQueryUrl = publicSearchQueries[Math.floor(Math.random() * publicSearchQueries.length)];
    
    const res = await fetch(randomQueryUrl, {
      headers: {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml'
      }
    });

    if (res.ok) {
      const htmlText = await res.text();
      const linkMatches = htmlText.match(/class="result__url"[^>]*><span>(.*?)<\/span>/g);
      
      if (linkMatches && linkMatches.length > 0) {
        for (const match of linkMatches) {
          const cleanUrl = match.replace(/<\/?span>/g, '').replace(/class="result__url"/g, '').replace(/<[^>]*>/g, '').trim();
          const fullTargetUrl = cleanUrl.startsWith('http') ? cleanUrl : `https://${cleanUrl}`;

          const exists = localData.queue.some(item => item.includes(fullTargetUrl));
          if (!exists && localData.queue.length < 40 && !fullTargetUrl.includes('duckduckgo') && !fullTargetUrl.includes('aviasales')) {
            const targetUrlWithMarker = `${fullTargetUrl}${fullTargetUrl.includes('?') ? '&' : '?'}marker=${AFFILIATE_MARKER}`;
            const task = {
              batchId: `auto_public_${Date.now()}`,
              taskId: `arb_${Math.random().toString(36).substring(7)}`,
              type: 'affiliate_arbitrage_audit',
              targetUrl: targetUrlWithMarker,
              requiredMarker: AFFILIATE_MARKER,
              estimatedValueUSD: 75,
              timestamp: Date.now()
            };
            await storePush(JSON.stringify(task));
            discoveredCount++;
          }
        }
      }
    }
  } catch (err) {
    console.warn(`⚠️ [Discovery Notice] Public network sweep restricted on cloud IP. Switching to global route matrix.`);
  }

  // Guaranteed resilient fallback: Pulls from expanded global route matrix
  if (discoveredCount === 0 && localData.queue.length < 25) {
    const selectedMatrix = GLOBAL_ROUTE_MATRIX[Math.floor(Math.random() * GLOBAL_ROUTE_MATRIX.length)];
    const fallbackUrl = `https://www.aviasales.com/search/${selectedMatrix.route}?marker=${AFFILIATE_MARKER}`;

    const exists = localData.queue.some(item => item.includes(fallbackUrl));
    if (!exists) {
      await storePush(JSON.stringify({
        batchId: `auto_matrix_${Date.now()}`,
        taskId: `arb_${Math.random().toString(36).substring(7)}`,
        type: 'affiliate_arbitrage_audit',
        targetUrl: fallbackUrl,
        requiredMarker: AFFILIATE_MARKER,
        estimatedValueUSD: selectedMatrix.value,
        timestamp: Date.now()
      }));
      console.log(`🚀 [Discovery Engine] Injected [${selectedMatrix.region}] route: ${selectedMatrix.route} ($${selectedMatrix.value})`);
    }
  }

  // Rapid discovery cycle set to every 30 seconds (30000 ms)
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
    context = await browser.newContext({
      userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36'
    });
    const page = await context.newPage();

    let result = await auditArbitrageTarget(task, page);
    await context.close();

    if (!result.success) {
      console.warn(`💰 [Worker #${workerId}] Monetary Leak Identified on ${task.targetUrl} ($${task.estimatedValueUSD})`);
      await sendTelegramAlert('Monetary Leakage / Arbitrage Alert', task, result);
    } else {
      console.log(`✅ [Worker #${workerId}] Route Secured. Value protected: $${task.estimatedValueUSD}`);
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
  console.log(`Autonomous Headless Arbitrage Cluster active on port ${PORT}`);
});
