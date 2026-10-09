const express = require('express');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');

const app = express();
app.use(express.json());

// ==========================================
// CONFIG & SECRETS (Loaded from Environment)
// ==========================================
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '';
const AFFILIATE_MARKER = process.env.TRAVELPAYOUTS_MARKER || '773479';
const WEBMONEY_PURSE = process.env.WEBMONEY_PURSE || 'Z-Purse-Configured';
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';

// ==========================================
// ZERO-DB IMMUTABLE LEDGER (REAL TRANSACTIONS ONLY)
// ==========================================
const LEDGER_FILE = path.join(__dirname, 'cluster_payout_ledger.json');

if (!fs.existsSync(LEDGER_FILE)) {
  fs.writeFileSync(LEDGER_FILE, JSON.stringify({ total_value_captured: 0.0, completed_tasks: [] }, null, 2), 'utf8');
}

// Atomic write lock to prevent race conditions during real webhook spikes
let isWriting = false;
const writeQueue = [];

async function commitRealRevenueToLedger(taskName, sourceNiche, valueCaptured) {
  writeQueue.push({ taskName, sourceNiche, valueCaptured });
  if (isWriting) return;
  isWriting = true;

  while (writeQueue.length > 0) {
    const item = writeQueue.shift();
    try {
      const rawData = fs.existsSync(LEDGER_FILE) ? fs.readFileSync(LEDGER_FILE, 'utf8') : '{"total_value_captured":0.0,"completed_tasks":[]}';
      const ledger = JSON.parse(rawData);

      ledger.total_value_captured += item.valueCaptured;
      ledger.completed_tasks.unshift({
        task: item.taskName,
        source: item.sourceNiche,
        value: item.valueCaptured,
        timestamp: new Date().toISOString()
      });

      if (ledger.completed_tasks.length > 300) {
        ledger.completed_tasks = ledger.completed_tasks.slice(0, 300);
      }

      const tempFile = `${LEDGER_FILE}.tmp`;
      fs.writeFileSync(tempFile, JSON.stringify(ledger, null, 2), 'utf8');
      fs.renameSync(tempFile, LEDGER_FILE);

      console.log(`💳 [Real Ledger Commit] +$${item.valueCaptured.toFixed(2)} recorded \vert{} Cumulative:$${ledger.total_value_captured.toFixed(2)}`);
    } catch (err) {
      console.error('❌ [Ledger Write Error]:', err.message);
    }
  }
  isWriting = false;
}

// ==========================================
// STATIC PUBLIC TRAVEL MATRIX (No Fake Spreads)
// ==========================================
const publicMarketDeals = [
  { id: 'los-lhr', vertical: 'flight', route: 'Lagos (LOS) → London (LHR)', domain: 'https://www.aviasales.com/', path: 'search/LOS2012LHR1', region: 'Flight (Lagos - London)' },
  { id: 'los-dxb', vertical: 'flight', route: 'Lagos (LOS) → Dubai (DXB)', domain: 'https://www.aviasales.com/', path: 'search/LOS2212DXB1', region: 'Flight (Lagos - Dubai)' },
  { id: 'los-abv', vertical: 'flight', route: 'Lagos (LOS) → Abuja (ABV)', domain: 'https://www.aviasales.com/', path: 'search/LOS0112ABV1', region: 'Flight (Lagos - Abuja)' },
  { id: 'los-jnb', vertical: 'flight', route: 'Lagos (LOS) → Johannesburg (JNB)', domain: 'https://www.aviasales.com/', path: 'search/LOS1512JNB1', region: 'Flight (Lagos - Johannesburg)' },
  { id: 'siteground', vertical: 'saas', route: 'Managed Cloud Hosting (SiteGround)', domain: 'https://www.siteground.com/gohome?a_id=', path: AFFILIATE_MARKER, region: 'Cloud Hosting (SiteGround)' }
];

// ==========================================
// TELEGRAM ALERT DISPATCHER
// ==========================================
async function sendTelegramAlert(title, message) {
  if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
  
  const text = `🚨 *${title}*\n\n${message}`;
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

// ==========================================
// PUBLIC DASHBOARD WEB LAYER (FRONTEND)
// ==========================================
app.get('/', (req, res) => {
  let ledgerData = { total_value_captured: 0.0, completed_tasks: [] };
  try {
    ledgerData = JSON.parse(fs.readFileSync(LEDGER_FILE, 'utf8'));
  } catch (e) {}

  const html = `
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Live Travel Feed & Payment Engine</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #0f172a; color: #f8fafc; padding: 20px; margin: 0; }
            .container { max-width: 850px; margin: 0 auto; }
            header { text-align: center; padding: 30px 0; }
            h1 { color: #38bdf8; font-size: 24px; margin-bottom: 5px; }
            p.subtitle { color: #94a3b8; font-size: 14px; }
            .stats-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 15px; margin-bottom: 25px; }
            .stat-card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 15px; text-align: center; }
            .stat-card h2 { color: #4ade80; margin: 5px 0 0 0; font-size: 24px; }
            .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; margin-bottom: 15px; display: flex; justify-content: space-between; align-items: center; }
            .deal-info h3 { margin: 0 0 5px 0; font-size: 18px; color: #f1f5f9; }
            .deal-info p { margin: 0; color: #94a3b8; font-size: 13px; }
            .btn { background: #0284c7; color: white; padding: 10px 18px; border-radius: 8px; text-decoration: none; font-weight: bold; display: inline-block; transition: background 0.2s; }
            .btn:hover { background: #0369a1; }
            footer { text-align: center; margin-top: 40px; color: #64748b; font-size: 12px; }
        </style>
    </head>
    <body>
        <div class="container">
            <header>
                <h1>⚡ Live Travel Feed & Production Engine</h1>
                <p class="subtitle">Zero-DB Verified Transaction & Affiliate Gateway.</p>
            </header>

            <div class="stats-grid">
                <div class="stat-card">
                    <span>Verified Real Revenue</span>
                    <h2>$${ledgerData.total_value_captured.toFixed(2)}</h2>
                </div>
                <div class="stat-card">
                    <span>Processed Transactions</span>
                    <h2>${ledgerData.completed_tasks.length}</h2>
                </div>
            </div>
            
            <div id="deals-list">
                ${publicMarketDeals.map(deal => {
                  const targetUrl = deal.vertical === 'flight' ? `${deal.domain}${deal.path}?marker=${AFFILIATE_MARKER}` : `${deal.domain}${deal.path}`;
                  return `
                    <div class="card">
                        <div class="deal-info">
                            <h3>${deal.route}</h3>
                            <p>Direct Affiliate Route (${deal.region})</p>
                        </div>
                        <div>
                            <a href="${targetUrl}" target="_blank" class="btn">Book Deal →</a>
                        </div>
                    </div>
                  `;
                }).join('')}
            </div>

            <footer>
                Powered by Production Engine &bull; Payout Routing: WebMoney (${WEBMONEY_PURSE})
            </footer>
        </div>
    </body>
    </html>
  `;
  res.status(200).send(html);
});

// HEALTH CHECK ENDPOINT
app.get('/health', (req, res) => {
  res.status(200).json({
    status: 'online',
    service: 'Production Fintech & Affiliate Gateway (Simulation Removed)',
    payoutDestination: { gateway: 'WebMoney', purse: WEBMONEY_PURSE },
    activeMarker: AFFILIATE_MARKER,
    timestamp: new Date().toISOString()
  });
});

// ==========================================
// PAYSTACK WEBHOOK RECONCILIATION
// ==========================================
app.post('/api/paystack/webhook', express.json(), async (req, res) => {
  const hash = req.headers['x-paystack-signature'];
  
  if (!PAYSTACK_SECRET_KEY) {
    console.error('❌ [Paystack Error] Secret key missing from environment.');
    return res.status(400).send('Secret key missing');
  }

  try {
    const computedHash = crypto
      .createHmac('sha512', PAYSTACK_SECRET_KEY)
      .update(JSON.stringify(req.body))
      .digest('hex');

    if (hash !== computedHash) {
      return res.status(401).send('Unauthorized signature');
    }

    const event = req.body;

    if (event && event.event === 'charge.success') {
      const paymentData = event.data;
      const amountPaidNaira = paymentData.amount / 100;
      const customerEmail = paymentData.customer.email;
      const reference = paymentData.reference;
      const estimatedUsdValue = Number((amountPaidNaira / 1500).toFixed(2));

      // Idempotency check: prevent duplicate credit
      const rawData = fs.readFileSync(LEDGER_FILE, 'utf8');
      const ledger = JSON.parse(rawData);
      const isDuplicate = ledger.completed_tasks.some(t => t.task.includes(reference));

      if (!isDuplicate) {
        console.log(`💳 [Paystack Verified] Received ₦${amountPaidNaira} from ${customerEmail} (Ref:${reference})`);
        await commitRealRevenueToLedger(`Paystack Subscription (${customerEmail}) - Ref:${reference}`, 'Direct Fintech Checkout', estimatedUsdValue);
        await sendTelegramAlert('PAYSTACK PAYMENT RECEIVED', `• Amount: \`₦${amountPaidNaira}\`\n• Customer: ${customerEmail}\n• Reference: \`${reference}\``);
      }
    }

    res.status(200).send('OK');
  } catch (err) {
    console.error('❌ [Paystack Webhook Error]', err.message);
    res.status(500).send('Internal Server Error');
  }
});

// ==========================================
// PAYSTACK MANUAL LEDGER SYNC ENDPOINT
// ==========================================
app.get('/api/paystack/sync-ledger', async (req, res) => {
  if (!PAYSTACK_SECRET_KEY) {
    return res.status(400).json({ status: 'error', message: 'Paystack secret key missing.' });
  }

  try {
    const response = await fetch('https://api.paystack.co/transaction?status=success&perPage=50', {
      method: 'GET',
      headers: {
        Authorization: `Bearer ${PAYSTACK_SECRET_KEY}`,
        'Content-Type': 'application/json'
      }
    });

    const data = await response.json();
    if (!data.status) {
      return res.status(400).json({ status: 'error', message: 'Failed to fetch transactions from Paystack' });
    }

    let syncedCount = 0;
    const rawData = fs.readFileSync(LEDGER_FILE, 'utf8');
    const ledger = JSON.parse(rawData);
    const existingTasks = ledger.completed_tasks.map(t => t.task);

    for (const tx of data.data) {
      const taskDescription = `Paystack Sync (${tx.customer.email}) - Ref: ${tx.reference}`;
      
      if (!existingTasks.some(taskStr => taskStr.includes(tx.reference))) {
        const amountNaira = tx.amount / 100;
        const usdValue = Number((amountNaira / 1500).toFixed(2));
        
        await commitRealRevenueToLedger(taskDescription, 'Direct Fintech Checkout', usdValue);
        syncedCount++;
      }
    }

    console.log(`🔄 [Ledger Sync] Successfully synchronized ${syncedCount} real transactions from Paystack.`);
    res.status(200).json({
      status: 'success',
      message: `Successfully synchronized ${syncedCount} real transactions into the local ledger.`,
      currentLedgerTotalUSD: ledger.total_value_captured
    });
  } catch (err) {
    console.error('❌ [Ledger Sync Error]', err.message);
    res.status(500).json({ status: 'error', message: err.message });
  }
});

const PORT = process.env.PORT || 10000;
app.listen(PORT, () => {
  console.log(`Production Engine active on port ${PORT} (Simulations Removed)`);
});
