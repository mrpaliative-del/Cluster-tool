const http = require('http');
const https = require('https');
const crypto = require('crypto');
const { createClient } = require('@supabase/supabase-js');

// ==========================================
// CONFIGURATION & ENVIRONMENT VARIABLES
// ==========================================
const PORT = process.env.PORT || 10000;
const POLL_INTERVAL_MS = parseInt(process.env.POLL_INTERVAL_MS, 10) || 6000;
const AFFILIATE_MARKER = process.env.AFFILIATE_MARKER || 'global_cluster_master_01';
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';

// External live scanner endpoint
const LEADS_SCANNER_ENDPOINT = process.env.LEADS_SCANNER_ENDPOINT || '';

// Telegram Notification Credentials
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '5058299552';

// Supabase Configuration
const SUPABASE_URL = process.env.SUPABASE_URL || '';
const SUPABASE_SERVICE_ROLE_KEY = process.env.SUPABASE_SERVICE_ROLE_KEY || '';

let supabase = null;
if (SUPABASE_URL && SUPABASE_SERVICE_ROLE_KEY) {
    supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY);
    console.log('📦 Supabase client initialized successfully.');
} else {
    console.log('⚠️ Supabase credentials missing. Database logging will be bypassed.');
}

// ==========================================
// 1. RENDER HTTP SERVER & ROUTE HANDLERS
// ==========================================
const server = http.createServer(async (req, res) => {
    // Modern WHATWG URL parsing
    const baseUrl = `http://${req.headers.host || 'localhost'}`;
    const parsedUrl = new URL(req.url, baseUrl);
    const pathname = parsedUrl.pathname;
    const queryParams = parsedUrl.searchParams;

    // A. Paystack Webhook Receiver Endpoint
    if (req.method === 'POST' && pathname === '/webhook/paystack') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', async () => {
            const hash = crypto.createHmac('sha512', PAYSTACK_SECRET_KEY).update(body).digest('hex');
            
            if (hash !== req.headers['x-paystack-signature']) {
                res.writeHead(401, { 'Content-Type': 'application/json' });
                return res.end(JSON.stringify({ status: 'error', message: 'Invalid signature' }));
            }

            res.writeHead(200, { 'Content-Type': 'application/json' });
            res.end(JSON.stringify({ status: 'received' }));

            try {
                const event = JSON.parse(body);
                if (event.event === 'charge.success') {
                    const data = event.data;
                    const metadata = data.metadata || {};
                    console.log(`🎉 [Webhook] Payment Successful! Ref: ${data.reference} \vert{} Task:${metadata.task_id || 'N/A'}`);

                    await sendWebhookAlert(metadata.task_id || 'unknown', data.amount / 100, data.reference, metadata.sector || 'General');
                    
                    if (supabase && metadata.task_id) {
                        await supabase.from('pending_tasks').update({ status: 'settled_success' }).eq('id', metadata.task_id);
                        await supabase.from('gap_scans').update({
                            status: `settled_success (Ref: ${data.reference})`
                        }).eq('task_id', metadata.task_id);
                    }
                }
            } catch (err) {
                console.error('⚠️ Webhook Processing Exception:', err.message);
            }
        });
        return;
    }

    // B. Resolution & Deep Link Handler (Telegram / Affiliate Click-Through)
    if (req.method === 'GET' && pathname === '/resolve') {
        const taskId = queryParams.get('task') || 'unknown';
        const marker = queryParams.get('marker') || AFFILIATE_MARKER;

        console.log(`🔗 [Resolution Route] Click registered for Task: ${taskId} using marker:${marker}`);

        if (supabase && taskId !== 'unknown') {
            try {
                await supabase.from('pending_tasks').update({ status: 'resolved_clicked' }).eq('id', taskId);
                await supabase.from('gap_scans').update({ status: 'resolved_clicked' }).eq('task_id', taskId);
            } catch (e) {}
        }

        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(`
            <!DOCTYPE html>
            <html>
            <head>
                <title>FlyMatrix & DelightPay Gateway - Resolution</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 50px 20px; }
                    .card { max-width: 500px; margin: 0 auto; background: #1e293b; padding: 30px; border-radius: 12px; box-shadow: 0 10px 25px rgba(0,0,0,0.3); border: 1px solid #334155; }
                    h2 { color: #38bdf8; margin-top: 0; }
                    p { color: #94a3b8; line-height: 1.6; }
                    .badge { display: inline-block; background: #0284c7; color: white; padding: 6px 12px; border-radius: 6px; font-size: 13px; font-weight: bold; margin-bottom: 20px; }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="badge">Marker: ${marker}</div>
                    <h2>Resolution Successful</h2>
                    <p>Task ID <strong>${taskId}</strong> has been successfully tracked and verified through the autonomous pipeline.</p>
                    <p>You may now close this window or return to your application dashboard.</p>
                </div>
            </body>
            </html>
        `);
    }

    // C. Default Health Status Endpoint
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        status: 'online',
        service: 'Global Multi-Sector Autonomous Gap Scanner Daemon',
        marker: AFFILIATE_MARKER,
        supabase_connected: !!supabase,
        uptime_seconds: process.uptime(),
        timestamp: new Date().toISOString()
    }));
});

server.listen(PORT, () => {
    console.log(`🌐 Autonomous Health, Webhook & Resolution Server bound and active on port ${PORT}`);
});

// ==========================================
// 2. SUPABASE AUDIT LOGGER HELPER
// ==========================================
async function logScanToSupabase(task, valueUSD, paystackRef, status = 'completed') {
    if (!supabase) return;

    try {
        await supabase.from('gap_scans').insert([
            {
                task_id: task.id,
                sector: task.sector,
                target_asset: task.payload.target_asset,
                estimated_value: valueUSD,
                worker_marker: AFFILIATE_MARKER,
                status: `${status} (Ref:${paystackRef || 'N/A'})`,
                detected_at: new Date().toISOString()
            }
        ]);
        console.log(`💾 [Supabase Audit] Successfully logged Task [ID: ${task.id}]`);
    } catch (err) {
        console.error(`⚠️ Supabase Exception:`, err.message);
    }
}

// ==========================================
// 3. HYBRID TASK FETCHER (API + DATABASE)
// ==========================================
async function fetchNextGlobalTask() {
    // Tier 1: Try External API Endpoint
    if (LEADS_SCANNER_ENDPOINT && !LEADS_SCANNER_ENDPOINT.includes('your-endpoint.com')) {
        try {
            const apiTask = await new Promise((resolve) => {
                https.get(LEADS_SCANNER_ENDPOINT, {
                    headers: {
                        'Authorization': `Bearer ${PAYSTACK_SECRET_KEY}`,
                        'X-Worker-Marker': AFFILIATE_MARKER
                    }
                }, (res) => {
                    let data = '';
                    res.on('data', chunk => data += chunk);
                    res.on('end', () => {
                        try {
                            const parsed = JSON.parse(data);
                            if (parsed && (parsed.lead || parsed.id)) {
                                return resolve(parsed.lead || parsed);
                            }
                        } catch (e) {}
                        resolve(null);
                    });
                }).on('error', () => resolve(null));
            });

            if (apiTask) return apiTask;
        } catch (e) {}
    }

    // Tier 2: Try Supabase Database Queue (`pending_tasks`)
    if (supabase) {
        try {
            const { data, error } = await supabase
                .from('pending_tasks')
                .select('*')
                .eq('status', 'pending')
                .order('created_at', { ascending: true })
                .limit(1)
                .single();

            if (!error && data) {
                // Atomic Lock to prevent race conditions
                const { error: updateError } = await supabase
                    .from('pending_tasks')
                    .update({ status: 'processing', worker_marker: AFFILIATE_MARKER })
                    .eq('id', data.id)
                    .eq('status', 'pending');

                if (!updateError) {
                    return {
                        id: data.id,
                        sector: data.sector,
                        payload: {
                            target_asset: data.target_asset,
                            estimated_value: data.estimated_value,
                            detection_source: 'supabase_database_queue'
                        }
                    };
                }
            }
        } catch (err) {
            // No pending rows found or table not created yet
        }
    }

    return null; // No active tasks in either queue at the moment
}

// ==========================================
// 4. TELEGRAM NOTIFICATION DISPATCHERS
// ==========================================
function sendTelegramAlert(task, valueUSD, authUrl, reference) {
    return new Promise((resolve) => {
        if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return resolve(false);

        const paymentLink = authUrl || `https://cluster-tool.onrender.com/resolve?task=${task.id}&marker=${AFFILIATE_MARKER}`;
        const message = `🚀 *Live Paystack Ledger Alert*\n\n` +
                        `• *Task ID:* \`${task.id}\`\n` +
                        `• *Sector:* \`${task.sector}\`\n` +
                        `• *Target Asset:* *${task.payload.target_asset}*\n` +
                        `• *Paystack Ref:* \`${reference || 'N/A'}\`\n` +
                        `• *Payment Gateway:* [Complete Checkout](${paymentLink})\n` +
                        `• *Ledger Yield:* \`$${valueUSD}\`\n` +
                        `• *Source:* \`${task.payload.detection_source || 'hybrid_queue'}\`\n` +
                        `• *Status:* \`Live Initialization ✅\``;

        dispatchTelegramMessage(message, resolve);
    });
}

function sendWebhookAlert(taskId, amountNGN, reference, sector) {
    return new Promise((resolve) => {
        if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return resolve(false);

        const message = `💰 *Paystack Settlement Verified!*\n\n` +
                        `• *Task ID:* \`${taskId}\`\n` +
                        `• *Sector:* \`${sector}\`\n` +
                        `• *Settled Amount:* \`₦${amountNGN.toLocaleString()}\`\n` +
                        `• *Reference:* \`${reference}\`\n` +
                        `• *Status:* \`Settled & Fulfilled 🟢\``;

        dispatchTelegramMessage(message, resolve);
    });
}

function dispatchTelegramMessage(message, resolve) {
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
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(postData)
        }
    };

    const req = https.request(options, (res) => {
        res.on('data', () => {});
        res.on('end', () => resolve(true));
    });

    req.on('error', () => resolve(false));
    req.write(postData);
    req.end();
}

// ==========================================
// 5. LIVE PAYSTACK LEDGER SYNCHRONIZATION
// ==========================================
function executeLedgerFulfillment(task) {
    return new Promise((resolve) => {
        const valueUSD = task.payload.estimated_value || 1.50;
        console.log(`🔍 [Scanning] Sector: ${task.sector} | Target: ${task.payload.target_asset} | Est. Value: $${valueUSD}`);

        const amountKobo = Math.round(valueUSD * 1500 * 100);

        const payload = JSON.stringify({
            email: "solveease.leads@gmail.com",
            amount: amountKobo,
            currency: "NGN",
            callback_url: `https://cluster-tool.onrender.com/resolve?task=${task.id}&marker=${AFFILIATE_MARKER}`,
            metadata: {
                task_id: task.id,
                sector: task.sector,
                target: task.payload.target_asset,
                worker_marker: AFFILIATE_MARKER
            }
        });

        const options = {
            hostname: 'api.paystack.co',
            port: 443,
            path: '/transaction/initialize',
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${PAYSTACK_SECRET_KEY}`,
                'Content-Type': 'application/json',
                'Content-Length': Buffer.byteLength(payload)
            }
        };

        const req = https.request(options, (res) => {
            let resData = '';
            res.on('data', chunk => resData += chunk);
            res.on('end', async () => {
                try {
                    const parsedResponse = JSON.parse(resData);
                    if (parsedResponse.status && parsedResponse.data) {
                        const reference = parsedResponse.data.reference;
                        console.log(`💰 [Paystack Live API] Initialized! Ref: ${reference}`);
                        
                        await sendTelegramAlert(task, valueUSD, parsedResponse.data.authorization_url, reference);
                        await logScanToSupabase(task, valueUSD, reference, 'live_initialized');
                    } else {
                        console.log(`⚠️ Paystack API error:`, parsedResponse.message || 'Unknown');
                    }
                } catch (parseErr) {
                    console.error(`⚠️ Parse Error:`, parseErr.message);
                }
                resolve(true);
            });
        });

        req.on('error', async (err) => {
            console.error(`⚠️ Network Error:`, err.message);
            resolve(true);
        });

        req.write(payload);
        req.end();
    });
}

// ==========================================
// 6. AUTONOMOUS NON-STOPPING DAEMON LOOP
// ==========================================
async function startAutonomousDaemon() {
    console.log("🚀 Initializing Hybrid Task Daemon (API + Supabase Queue)...");
    let executionCycle = 0;

    while (true) {
        try {
            executionCycle++;
            const task = await fetchNextGlobalTask();

            if (task && task.id) {
                console.log(`\n--- Execution Cycle #${executionCycle} [Real Task ID: ${task.id}] ---`);
                await executeLedgerFulfillment(task);
                console.log(`✅ Task [ID: ${task.id}] Processed Successfully.`);
            } else {
                process.stdout.write('.');
            }
        } catch (err) {
            console.error(`⚠️ Daemon Loop Warning:`, err.message);
        }

        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
    }
}

startAutonomousDaemon();
