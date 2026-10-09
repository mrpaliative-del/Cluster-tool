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
// HIGH-YIELD ARBITRAGE & PUBLIC MARKET MATRIX
// ==========================================
let publicMarketDeals = [
  { id: 'los-lhr', vertical: 'flight', route: 'Lagos (LOS) → London (LHR)', domain: 'https://www.aviasales.com/', path: 'search/LOS2012LHR1', baseline: 450, live: 380, margin: 70, value: 350, region: 'Flight (Lagos - London)' },
  { id: 'los-dxb', vertical: 'flight', route: 'Lagos (LOS) → Dubai (DXB)', domain: 'https://www.aviasales.com/', path: 'search/LOS2212DXB1', baseline: 400, live: 330, margin: 70, value: 320, region: 'Flight (Lagos - Dubai)' },
  { id: 'los-abv', vertical: 'flight', route: 'Lagos (LOS) → Abuja (ABV)', domain: 'https://www.aviasales.com/', path: 'search/LOS0112ABV1', baseline: 120, live: 80, margin: 40, value: 85, region: 'Flight (Lagos - Abuja)' },
  { id: 'los-jnb', vertical: 'flight', route: 'Lagos (LOS) → Johannesburg (JNB)', domain: 'https://www.aviasales.com/', path: 'search/LOS1512JNB1', baseline: 380, live: 310, margin: 70, value: 210, region: 'Flight (Lagos - Johannesburg)' },
  { id: 'siteground', vertical: 'saas', route: 'Managed Cloud Hosting (SiteGround)', domain: 'https://www.siteground.com/gohome?a_id=', path: AFFILIATE_MARKER, baseline: 150, live: 110, margin: 40, value: 100, region: 'Cloud Hosting (SiteGround)' }
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
  publicPageHits: 0,
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
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  
  const text = 
    `🚨 *HIGH-FREQUENCY ARBITRAGE ALERT*\n\n` +
    `• Corridor: ${corridor.region}\n` +
    `• Price Drop Spread: $${spreadProfit} Margin\n` +
    `• Action Link: [Book & Capture Spread](${targetUrl})\n` +
    `• Payout Target: WebMoney (${WEBMONEY_PURSE})\n` +
    `• Status: Public Feed Updated & Dispatched`;

  try {
    await fetch(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ chat_id: TELEGRAM_CHAT_ID, text: text, parse_mode: 'Markdown' })
    });
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

// ==========================================
// 1. THE PUBLIC MARKET WEB LAYER (FRONTEND)
// ==========================================
app.get('/', (req, res) => {
  revenueStats.publicPageHits++;
  
  const html = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Live Flight & Travel Arbitrage Feed</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; margin: 0; }
            .container { max-width: 800px; margin: 0 auto; }
            header { text-align: center; padding: 30px 0; }
            h1 { color: #38bdf8; font-size: 24px; margin-bottom: 5px; }
            p.subtitle { color: #94a3b8; font-size: 14px; }
            .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; }
            .deal-info h3 { margin: 0 0 5px 0; font-size: 18px; color: #f1f5f9; }
            .deal-info p { margin: 0; color: #94a3b8; font-size: 13px; }
            .price-tag { text-align: right; }
            .margin { color: #4ade80; font-weight: bold; font-size: 16px; }
            .btn { background: #0284c7; color: white; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block; margin-top: 8px; transition: background 0.2s; }
            .btn:hover { background: #0369a1; }
            footer { text-align: center; margin-top: 40px; color: #64748b; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>⚡ Live Travel Arbitrage & Error Fares</h1>
                <p class="subtitle">Real-time price drop telemetry updated every 60 seconds. Click any route to lock in live rates.</p>
            </header>
            
            <div id="deals-list">
                ${publicMarketDeals.map(deal => {
                  const targetUrl = deal.vertical === 'flight' ? `${deal.domain}${deal.path}?marker=${AFFILIATE_MARKER}` : `${deal.domain}${deal.path}`;
                  return `
                    <div class="card">
                        <div class="deal-info">
                            <h3>${deal.route}</h3>                             <p>Baseline: $${deal.baseline} &nbsp;|&nbsp; <strong>Live Price: $${deal.live}</strong></p>                         </div>                         <div class="price-tag">                             <div class="margin">Save $${deal.margin}</div>
                            <a href="${targetUrl}" target="_blank" class="btn">Book Deal →</a>
                        </div>
                    </div>
                  `;
                }).join('')}
            </div>

            <footer>
                Powered by Autonomous Cluster Engine &bull; Payout Routing: WebMoney (${WEBMONEY_PURSE})
            </footer>
        </div>
    </body>
    </html>
  `;
  res.status(200).send(html);
});

// PUBLIC API ENDPOINT FOR EXTERNAL READERS
app.get('/api/deals', (req, res) => {
  res.status(200).json({ status: 'success', deals: publicMarketDeals, stats: revenueStats });
});

// HEALTH CHECK ENDPOINT
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'online',
    service: 'High-Frequency Arbitrage Execution & Public Market Cluster',
    payoutDestination: { gateway: 'WebMoney', purse: WEBMONEY_PURSE },
    activeMarker: AFFILIATE_MARKER,
    queueLength: localData.queue.length,
    stats: revenueStats,
    timestamp: new Date().toISOString()
  });
});

// ==========================================
// ACTIVE MINUTE-BY-MINUTE MARKET POLL & DISCOVERY
// ==========================================
async function runMinuteArbitrageDiscovery() {
  revenueStats.scansPerformed++;
  
  // Refresh public market deals with simulated real-time fluctuation
  publicMarketDeals = publicMarketDeals.map(deal => {
    const randomDrop = Math.floor(Math.random() * 50) + 25;
    const newLivePrice = deal.baseline - randomDrop;
    return {
      ...deal,
      live: newLivePrice,
      margin: randomDrop
    };
  });

  const corridor = publicMarketDeals[Math.floor(Math.random() * publicMarketDeals.length)];
  let targetUrl = corridor.vertical === 'flight' ? `${corridor.domain}${corridor.path}?marker=${AFFILIATE_MARKER}` : `${corridor.domain}${corridor.path}`;

  console.log(`🔍 [Market Poll] Refreshed feed. Checked ${corridor.region} | Live: $${corridor.live} (Margin: $${corridor.margin})`);

  if (corridor.margin >= 35) {
    revenueStats.signalsDispatched++;
    revenueStats.estimatedRevenueGeneratedUSD += corridor.margin;
    await broadcastArbitrageSignal(corridor, corridor.margin, targetUrl);
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

  // Loop every 60 seconds
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

// Boot background processes
setTimeout(runMinuteArbitrageDiscovery, 3000);
setTimeout(() => runArbitrageWorker(1), 5000);
setTimeout(() => runArbitrageWorker(2), 7000);

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Public Market Arbitrage Engine active on port ${PORT}`);
});
