/**
 * ============================================================================
 * OMNI-TASK ENGINE: INDUSTRIAL PRODUCTION REVENUE GATEWAY
 * ============================================================================
 * File: index.js
 * Version: 9.1.0-Production-Live
 * ============================================================================
 */

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');

// ==========================================
// 1. CONFIGURATION & ENVIRONMENT SETUP
// ==========================================
const PORT = process.env.PORT || 10000;
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';
const OPAY_RECIPIENT_CODE = process.env.OPAY_RECIPIENT_CODE || ''; 
const TASKS_FILE = path.join(__dirname, 'tasks.json');
const WALLET_FILE = path.join(__dirname, 'wallet.json');

const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '';

const metrics = {
    uptimeStarted: Date.now(),
    totalWebhooksProcessed: 0,
    realRevenueCapturedUSD: 0,
    lastActiveTimestamp: null
};

function initializeStorageFiles() {
    if (!fs.existsSync(TASKS_FILE)) {
        fs.writeFileSync(TASKS_FILE, JSON.stringify({ tasks: [] }, null, 2));
    }
    if (!fs.existsSync(WALLET_FILE)) {
        const initialWallet = { accumulated_usd: 0.0, total_withdrawn_usd: 0.0, payouts_count: 0 };
        fs.writeFileSync(WALLET_FILE, JSON.stringify(initialWallet, null, 2));
    }
}
initializeStorageFiles();

// ==========================================
// 2. PAYSTACK DIRECT API HELPER
// ==========================================
function initializePaystackTransactionApi(email, amountInKobo, metadata) {
    return new Promise((resolve) => {
        if (!PAYSTACK_SECRET_KEY) return resolve({ status: false, message: 'Missing Secret Key' });

        const postData = JSON.stringify({
            email: email,
            amount: amountInKobo,
            metadata: metadata,
            callback_url: `https://${process.env.RENDER_EXTERNAL_URL || 'localhost'}/`
        });

        const options = {
            hostname: 'api.paystack.co',
            port: 443,
            path: '/transaction/initialize',
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${PAYSTACK_SECRET_KEY}`,
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(postData)
            }
        };

        const req = https.request(options, (res) => {
            let body = '';
            res.on('data', chunk => body += chunk);
            res.on('end', () => {
                try {
                    const json = JSON.parse(body);
                    resolve(json);
                } catch (err) {
                    resolve({ status: false, message: 'Parse error' });
                }
            });
        });

        req.on('error', () => resolve({ status: false, message: 'Network error' }));
        req.write(postData);
        req.end();
    });
}

// ==========================================
// 3. RENDER HTTP SERVER & WEBHOOK INGESTION
// ==========================================
const server = http.createServer(async (req, res) => {
    const baseUrl = `http://${req.headers.host || 'localhost'}`;
    const parsedUrl = new URL(req.url, baseUrl);
    const pathname = parsedUrl.pathname;

    // Manual external task injection endpoint
    if (req.method === 'POST' && pathname === '/tasks') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', () => {
            try {
                const payload = JSON.parse(body);
                if (!payload.target_url) {
                    res.writeHead(400, { 'Content-Type': 'application/json' });
                    return res.end(JSON.stringify({ status: 'error', message: 'Missing target_url' }));
                }

                const dbData = JSON.parse(fs.readFileSync(TASKS_FILE, 'utf8'));
                const newTask = {
                    id: `task-${Date.now().toString().slice(-6)}`,
                    sector: payload.sector || 'Custom Injected Task',
                    target_url: payload.target_url,
                    estimated_value: parseFloat(payload.estimated_value) || 1.25,
                    status: 'pending',
                    created_at: new Date().toISOString()
                };

                dbData.tasks.push(newTask);
                fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));

                res.writeHead(201, { 'Content-Type': 'application/json' });
                return res.end(JSON.stringify({ status: 'success', task_id: newTask.id }));
            } catch (err) {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                return res.end(JSON.stringify({ status: 'error', message: 'Invalid payload' }));
            }
        });
        return;
    }

    // Direct Server-to-Server Transaction Initialization Endpoint
    if (req.method === 'POST' && pathname === '/initialize-transaction') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', async () => {
            try {
                const payload = JSON.parse(body);
                const email = payload.email || 'customer@domain.com';
                const amountNGN = parseFloat(payload.amount) || 5000;
                const amountInKobo = Math.round(amountNGN * 100);
                
                const response = await initializePaystackTransactionApi(email, amountInKobo, {
                    task_id: payload.task_id || `task-${Date.now().toString().slice(-6)}`,
                    sector: payload.sector || 'Direct API Checkout Fulfillment'
                });

                if (response.status) {
                    res.writeHead(200, { 'Content-Type': 'application/json' });
                    return res.end(JSON.stringify({
                        status: 'success',
                        authorization_url: response.data.authorization_url,
                        reference: response.data.reference
                    }));
                } else {
                    res.writeHead(400, { 'Content-Type': 'application/json' });
                    return res.end(JSON.stringify({ status: 'error', message: response.message }));
                }
            } catch (err) {
                res.writeHead(400, { 'Content-Type': 'application/json' });
                return res.end(JSON.stringify({ status: 'error', message: 'Invalid payload' }));
            }
        });
        return;
    }

    // Secure Paystack Webhook Handler with Strict HMAC SHA512 Verification
    if (req.method === 'POST' && pathname === '/webhook/paystack') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', async () => {
            try {
                const signature = req.headers['x-paystack-signature'];
                const hash = crypto.createHmac('sha512', PAYSTACK_SECRET_KEY).update(body).digest('hex');
                
                if (hash !== signature) {
                    console.warn('[Security] Unauthorized webhook signature dropped.');
                    res.writeHead(401, { 'Content-Type': 'application/json' });
                    return res.end(JSON.stringify({ status: 'error', message: 'Invalid signature' }));
                }
                
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'received' }));

                const event = JSON.parse(body);
                
                if (event.event === 'charge.success') {
                    const data = event.data;
                    if (data.status !== 'success') return;

                    const metadata = data.metadata || {};
                    const amountNgn = data.amount / 100;
                    const usdValue = Number((amountNgn / 1500).toFixed(2));

                    console.log(`✅ [Paystack Verified] Charge received! Ref: ${data.reference}, Amount: ₦${amountNgn}`);
                    
                    // Credit wallet with real revenue
                    await creditWalletWithRealPayment(metadata.task_id || data.reference, amountNgn, usdValue, metadata.sector || 'Paystack Checkout');
                    await sendWebhookAlert(metadata.task_id || 'unknown', amountNgn, data.reference, metadata.sector || 'Paystack Checkout');
                }
            } catch (err) {
                console.error('⚠️ [Webhook Error]:', err.message);
            }
        });
        return;
    }

    const walletData = JSON.parse(fs.readFileSync(WALLET_FILE, 'utf8'));

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        status: 'online',
        service: 'Production Revenue & Webhook Gateway',
        version: '9.1.0-Production-Live',
        walletBalanceUSD: walletData.accumulated_usd,
        opayRecipientConfigured: Boolean(OPAY_RECIPIENT_CODE),
        metrics: {
            ...metrics,
            uptime_seconds: Math.floor((Date.now() - metrics.uptimeStarted) / 1000)
        },
        timestamp: new Date().toISOString()
    }));
});

// START HTTP SERVER INSTANTLY
server.listen(PORT, async () => {
    console.log(`🌐 [Server] Production HTTP listener bound securely on port ${PORT}`);
    startSelfPingDaemon();
    await dispatchTelegramMessage("🟢 *Production Revenue Gateway Online.* Simulations removed. Listening for live Paystack webhooks.", false);
});

// ==========================================
// 4. SELF-PING DAEMON
// ==========================================
function startSelfPingDaemon() {
    const PING_INTERVAL_MS = 10 * 60 * 1000;
    setInterval(() => {
        http.get(`http://localhost:${PORT}/`, (res) => {
            res.on('data', () => {});
            res.on('end', () => {});
        }).on('error', () => {});
    }, PING_INTERVAL_MS);
}

// ==========================================
// 5. TELEGRAM NOTIFICATION SYSTEM
// ==========================================
function dispatchTelegramMessage(message, disableNotification = false) {
    return new Promise((resolve) => {
        if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return resolve(false);

        const postData = JSON.stringify({
            chat_id: TELEGRAM_CHAT_ID,
            text: message,
            parse_mode: 'Markdown',
            disable_notification: disableNotification 
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

function sendWebhookAlert(taskId, amountNGN, reference, sector) {
    const message = `💰 🔊 *REAL PAYSTACK PAYMENT RECEIVED*\n\n` +
                    `• *Task ID:* \`${taskId}\`\n` +
                    `• *Sector:* \`${sector}\`\n` +
                    `• *Settled Amount:* \`₦${amountNGN.toLocaleString()}\`\n` +
                    `• *Reference:* \`${reference}\``;
    return dispatchTelegramMessage(message, false);
}

// ==========================================
// 6. REAL WALLET ACCUMULATION
// ==========================================
async function creditWalletWithRealPayment(taskId, amountNgn, amountUsd, sector) {
    let wallet = { accumulated_usd: 0.0, total_withdrawn_usd: 0.0, payouts_count: 0 };
    if (fs.existsSync(WALLET_FILE)) {
        wallet = JSON.parse(fs.readFileSync(WALLET_FILE, 'utf8'));
    }

    wallet.accumulated_usd += amountUsd;
    metrics.totalWebhooksProcessed++;
    metrics.realRevenueCapturedUSD += amountUsd;
    metrics.lastActiveTimestamp = new Date().toISOString();

    fs.writeFileSync(WALLET_FILE, JSON.stringify(wallet, null, 2));
    console.log(`💰 [Real Revenue Credited] Added $${amountUsd.toFixed(2)} (₦${amountNgn.toLocaleString()}) from [${sector}]. Total Balance: $${wallet.accumulated_usd.toFixed(2)}`);
}
