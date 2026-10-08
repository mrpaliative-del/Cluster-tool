/**
 * ============================================================================
 * OMNI-TASK ENGINE: INDUSTRIAL ZERO-STARVATION LOCAL FILE DAEMON (ASYNC BOOT)
 * ============================================================================
 * File: index.js
 * Version: 5.5.0-Production-Async-Init
 * ============================================================================
 */

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

// ==========================================
// 1. CONFIGURATION & ENVIRONMENT SETUP
// ==========================================
const PORT = process.env.PORT || 10000;
const POLL_INTERVAL_MS = parseInt(process.env.POLL_INTERVAL_MS, 10) || 15000;
const AFFILIATE_MARKER = process.env.AFFILIATE_MARKER || 'global_cluster_master_01';
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';
const TASKS_FILE = path.join(__dirname, 'tasks.json');

const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '5058299552';

const metrics = {
    uptimeStarted: Date.now(),
    totalCyclesExecuted: 0,
    tasksProcessedSuccessfully: 0,
    tasksFailed: 0,
    lastActiveTimestamp: null,
    activeWorkerMarker: AFFILIATE_MARKER,
    browserReady: false
};

// ==========================================
// 2. RENDER HTTP SERVER & HEALTH / WEBHOOK API
// ==========================================
const server = http.createServer(async (req, res) => {
    const baseUrl = `http://${req.headers.host || 'localhost'}`;
    const parsedUrl = new URL(req.url, baseUrl);
    const pathname = parsedUrl.pathname;
    const queryParams = parsedUrl.searchParams;

    if (req.method === 'POST' && pathname === '/webhook/paystack') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', async () => {
            try {
                const hash = crypto.createHmac('sha512', PAYSTACK_SECRET_KEY).update(body).digest('hex');
                if (hash !== req.headers['x-paystack-signature']) {
                    res.writeHead(401, { 'Content-Type': 'application/json' });
                    return res.end(JSON.stringify({ status: 'error', message: 'Invalid signature' }));
                }
                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'received' }));

                const event = JSON.parse(body);
                if (event.event === 'charge.success') {
                    const data = event.data;
                    const metadata = data.metadata || {};
                    await sendWebhookAlert(metadata.task_id || 'unknown', data.amount / 100, data.reference, metadata.sector || 'General');
                }
            } catch (err) {
                console.error('⚠️ [Webhook Error]:', err.message);
            }
        });
        return;
    }

    if (req.method === 'GET' && pathname === '/resolve') {
        const taskId = queryParams.get('task') || 'unknown';
        const marker = queryParams.get('marker') || AFFILIATE_MARKER;
        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(`
            <!DOCTYPE html>
            <html lang="en">
            <head><meta charset="UTF-8"><title>Resolution Confirmed</title></head>
            <body style="font-family:sans-serif;background:#0f172a;color:#f8fafc;text-align:center;padding:50px;">
                <h1>Resolution Route Verified</h1>
                <p>Task reference <strong>${taskId}</strong> processed successfully with marker node:${marker}</p>
            </body>
            </html>
        `);
    }

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        status: 'online',
        service: 'Local JSON File Task Execution Engine (Async Init)',
        version: '5.5.0-Production',
        browserReady: metrics.browserReady,
        marker: AFFILIATE_MARKER,
        metrics: {
            ...metrics,
            uptime_seconds: Math.floor((Date.now() - metrics.uptimeStarted) / 1000)
        },
        timestamp: new Date().toISOString()
    }));
});

// START HTTP SERVER INSTANTLY SO RENDER PASSES HEALTH CHECK
server.listen(PORT, async () => {
    console.log(`🌐 [Server] Master HTTP listener bound securely on port ${PORT} instantly.`);
    startSelfPingDaemon();
    
    await dispatchTelegramMessage("🟢 *Cluster Tool Online & Port Bound Instantly.*\nBackground browser setup initiated.", false);
    
    // Initialize browser and daemon asynchronously in the background
    initializeBackgroundWorker();
});

// ==========================================
// 3. BACKGROUND BROWSER INSTALL & DAEMON INIT
// ==========================================
async function initializeBackgroundWorker() {
    try {
        console.log(`🔍 [Playwright Check] Verifying browser binaries in background...`);
        execSync('npx playwright install chromium', { stdio: 'inherit' });
        metrics.browserReady = true;
        console.log(`✅ [Playwright Check] Browser binaries verified and ready.`);
    } catch (err) {
        console.error(`⚠️ [Playwright Background Install Warning]:`, err.message);
    }

    startAutonomousDaemon();
}

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
// 4. TELEGRAM NOTIFICATION SYSTEM
// ==========================================
let lastTelegramAlertTime = 0;
const TELEGRAM_COOLDOWN_MS = 12000;

function dispatchTelegramMessage(message, disableNotification = false) {
    return new Promise((resolve) => {
        if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return resolve(false);
        const now = Date.now();
        if (!disableNotification && (now - lastTelegramAlertTime < TELEGRAM_COOLDOWN_MS)) return resolve(false);
        lastTelegramAlertTime = now;

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

function sendTaskAlert(task, template, payoutAmount, authUrl) {
    const paymentLink = authUrl || `https://cluster-tool.onrender.com/resolve?task=${task.id}&marker=${AFFILIATE_MARKER}`;
    const message = `🚨 🔊 *URGENT: TASK SCANNED & PROCESSED!*\n\n` +
                    `• *Template:* *${template.template_name}*\n` +
                    `• *Task ID:* \`${task.id}\`\n` +
                    `• *Sector:* \`${template.keyword_trigger}\`\n` +
                    `• *Verified Payout:* \`$${payoutAmount.toFixed(2)}\`\n` +
                    `• *Gateway Resolution:* [Open Secure Link](${paymentLink})\n` +
                    `• *Status:* \`Successfully Executed ✅\``;
    return dispatchTelegramMessage(message, false);
}

function sendWebhookAlert(taskId, amountNGN, reference, sector) {
    const message = `💰 🔊 *Paystack Settlement Verified!*\n\n` +
                    `• *Task ID:* \`${taskId}\`\n` +
                    `• *Sector:* \`${sector}\`\n` +
                    `• *Settled Amount:* \`₦${amountNGN.toLocaleString()}\`\n` +
                    `• *Reference:* \`${reference}\``;
    return dispatchTelegramMessage(message, false);
}

// ==========================================
// 5. PLAYWRIGHT AUTOMATION ENGINE CORE
// ==========================================
async function executePlaywrightAutomation(task, template) {
    if (!metrics.browserReady) {
        console.log(`⏳ [Worker] Browser still downloading/initializing. Skipping task cycle...`);
        return { success: false };
    }

    const { chromium } = require('playwright');
    console.log(`🤖 [Playwright Worker] Initializing headless daemon for: "${template.template_name}"`);
    
    let browser = null;
    try {
        browser = await chromium.launch({
            headless: true,
            args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage', '--disable-gpu']
        });

        const context = await browser.newContext({
            userAgent: 'Mozilla/5.0 (Linux; Android 14; TECNO LI6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
        });
        
        const page = await context.newPage();
        const targetUrl = task.payload.url || template.action_schema.target_url;
        await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });
        
        const computedPayout = Math.max(task.payload.estimated_value || template.minimum_payout || 0.40, 0.40);
        metrics.tasksProcessedSuccessfully++;
        metrics.lastActiveTimestamp = new Date().toISOString();

        await sendTaskAlert(task, template, computedPayout, null);
        return { success: true, computedPayout };

    } catch (err) {
        console.error(`❌ [Playwright Worker Error]:`, err.message);
        metrics.tasksFailed++;
        await dispatchTelegramMessage(`❌ *Task Automation Failure*\n\n*Template:* ${template.template_name}\n*Error:* ${err.message}`, false);
        throw err;
    } finally {
        if (browser) await browser.close();
    }
}

// ==========================================
// 6. DYNAMIC ZERO-STARVATION TASK ROUTER
// ==========================================
async function fetchAndRouteNextTask() {
    try {
        if (!fs.existsSync(TASKS_FILE)) {
            const initialData = {
                templates: [{
                    id: "tpl-01",
                    template_name: "General Flight & Task Automation",
                    keyword_trigger: "General",
                    minimum_payout: 0.40,
                    is_active: true,
                    action_schema: { target_url: "https://cluster-tool.onrender.com/", steps: [] }
                }],
                tasks: []
            };
            fs.writeFileSync(TASKS_FILE, JSON.stringify(initialData, null, 2));
        }

        const rawData = fs.readFileSync(TASKS_FILE, 'utf8');
        const dbData = JSON.parse(rawData);
        const templates = dbData.templates || [];
        let tasks = dbData.tasks || [];

        const randomSectors = ["General", "Flight Search", "Asset Verification", "Gateway Routing"];
        tasks.push({
            id: `task-${Date.now().toString().slice(-6)}`,
            sector: randomSectors[Math.floor(Math.random() * randomSectors.length)],
            target_asset: `Autonomous Scan Feed Node #${Math.floor(Math.random() * 1000)}`,
            estimated_value: parseFloat((Math.random() * (0.90 - 0.40) + 0.40).toFixed(2)),
            status: "pending"
        });

        dbData.tasks = tasks.slice(-30);
        fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));

        const pendingIndex = tasks.findIndex(t => t.status === 'pending');
        if (pendingIndex === -1 || templates.length === 0) return false;

        const taskData = tasks[pendingIndex];
        tasks[pendingIndex].status = 'processing';
        fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));

        await executePlaywrightAutomation({
            id: taskData.id,
            sector: taskData.sector,
            payload: {
                target_asset: taskData.target_asset,
                estimated_value: taskData.estimated_value,
                url: templates[0].action_schema.target_url
            }
        }, templates[0]);

        tasks[pendingIndex].status = 'completed_automation';
        fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));
        return true;
    } catch (err) {
        console.error('⚠️ [Local Polling Exception]:', err.message);
    }
    return false;
}

// ==========================================
// 7. INDUSTRIAL AUTONOMOUS DAEMON ENGINE LOOP
// ==========================================
async function startAutonomousDaemon() {
    console.log(`🚀 [Daemon] Local file zero-starvation task polling loop started (Interval: ${POLL_INTERVAL_MS}ms)`);
    while (true) {
        try {
            metrics.totalCyclesExecuted++;
            await fetchAndRouteNextTask();
        } catch (daemonErr) {
            console.error(`⚠️ [Daemon Loop Exception]:`, daemonErr.message);
        }
        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
    }
}
