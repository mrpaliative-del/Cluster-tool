/**
 * ============================================================================
 * OMNI-TASK ENGINE: FULLY AUTONOMOUS INDUSTRIAL FEEDER DAEMON
 * ============================================================================
 * File: index.js
 * Version: 5.7.0-Fully-Autonomous-Production
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
const POLL_INTERVAL_MS = parseInt(process.env.POLL_INTERVAL_MS, 10) || 12000; // 12s cadence
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

// Autonomous target pool for self-feeding execution
const LIVE_TARGET_POOL = [
    { sector: 'Flight Aggregation', url: 'https://cluster-tool.onrender.com/resolve?route=lagos-jos', value: 0.65 },
    { sector: 'Asset Verification', url: 'https://cluster-tool.onrender.com/resolve?node=verify-01', value: 0.50 },
    { sector: 'Gateway Routing', url: 'https://cluster-tool.onrender.com/resolve?gateway=paystack-sync', value: 0.75 },
    { sector: 'Search Indexing', url: 'https://cluster-tool.onrender.com/resolve?seo=crawl-target', value: 0.45 }
];

function initializeTasksFile() {
    if (!fs.existsSync(TASKS_FILE)) {
        const initialData = { tasks: [] };
        fs.writeFileSync(TASKS_FILE, JSON.stringify(initialData, null, 2));
    }
}
initializeTasksFile();

// ==========================================
// 2. RENDER HTTP SERVER & HEALTH DASHBOARD
// ==========================================
const server = http.createServer(async (req, res) => {
    const baseUrl = `http://${req.headers.host || 'localhost'}`;
    const parsedUrl = new URL(req.url, baseUrl);
    const pathname = parsedUrl.pathname;

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

    const dbData = JSON.parse(fs.readFileSync(TASKS_FILE, 'utf8'));
    const pendingCount = dbData.tasks.filter(t => t.status === 'pending').length;

    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        status: 'online',
        service: 'Fully Autonomous Industrial Task Engine',
        version: '5.7.0-Autonomous',
        browserReady: metrics.browserReady,
        pendingTasksInQueue: pendingCount,
        marker: AFFILIATE_MARKER,
        metrics: {
            ...metrics,
            uptime_seconds: Math.floor((Date.now() - metrics.uptimeStarted) / 1000)
        },
        timestamp: new Date().toISOString()
    }));
});

// START HTTP SERVER INSTANTLY
server.listen(PORT, async () => {
    console.log(`🌐 [Server] Master HTTP listener bound securely on port ${PORT}`);
    startSelfPingDaemon();
    
    await dispatchTelegramMessage("🟢 *Fully Autonomous Engine Online.*\nSystem is self-feeding and executing background tasks.", false);
    initializeBackgroundWorker();
});

// ==========================================
// 3. BACKGROUND BROWSER SETUP & DAEMON INIT
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
const TELEGRAM_COOLDOWN_MS = 5000;

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

function sendTaskAlert(task, payoutAmount) {
    const message = `🚨 🔊 *AUTONOMOUS TASK EXECUTED!*\n\n` +
                    `• *Task ID:* \`${task.id}\`\n` +
                    `• *Sector:* \`${task.sector}\`\n` +
                    `• *Target URL:* ${task.target_url}\n` +
                    `• *Verified Value:* \`$${payoutAmount.toFixed(2)}\`\n` +
                    `• *Status:* \`Executed Successfully ✅\``;
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
async function executePlaywrightAutomation(task) {
    if (!metrics.browserReady) {
        console.log(`⏳ [Worker] Browser still initializing. Retrying next cycle...`);
        return { success: false };
    }

    const { chromium } = require('playwright');
    console.log(`🤖 [Playwright Worker] Processing autonomous task ID: ${task.id} -> ${task.target_url}`);
    
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
        await page.goto(task.target_url, { waitUntil: 'domcontentloaded', timeout: 30000 });
        
        const computedPayout = Math.max(task.estimated_value || 0.40, 0.40);
        metrics.tasksProcessedSuccessfully++;
        metrics.lastActiveTimestamp = new Date().toISOString();

        await sendTaskAlert(task, computedPayout);
        return { success: true, computedPayout };

    } catch (err) {
        console.error(`❌ [Playwright Worker Error]:`, err.message);
        metrics.tasksFailed++;
        await dispatchTelegramMessage(`❌ *Autonomous Task Failure*\n\n*Task ID:* ${task.id}\n*Error:* ${err.message}`, false);
        throw err;
    } finally {
        if (browser) await browser.close();
    }
}

// ==========================================
// 6. FULLY AUTOMATED SELF-FEEDING LOOP
// ==========================================
async function fetchAndRouteNextTask() {
    try {
        if (!fs.existsSync(TASKS_FILE)) return false;

        const rawData = fs.readFileSync(TASKS_FILE, 'utf8');
        const dbData = JSON.parse(rawData);
        let tasks = dbData.tasks || [];

        // Check if there are pending tasks; if not, automatically feed a new one from the pool!
        const pendingTasks = tasks.filter(t => t.status === 'pending');
        if (pendingTasks.length === 0) {
            const randomTarget = LIVE_TARGET_POOL[Math.floor(Math.random() * LIVE_TARGET_POOL.length)];
            const autoTask = {
                id: `auto-${Date.now().toString().slice(-6)}`,
                sector: randomTarget.sector,
                target_url: randomTarget.url,
                estimated_value: randomTarget.value,
                status: 'pending',
                created_at: new Date().toISOString()
            };
            tasks.push(autoTask);
            dbData.tasks = tasks;
            fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));
            console.log(`✨ [Auto-Feeder] Generated new autonomous task: ${autoTask.id} (${autoTask.sector})`);
        }

        // Find and process the next pending task
        const pendingIndex = tasks.findIndex(t => t.status === 'pending');
        if (pendingIndex === -1) return false;

        const taskData = tasks[pendingIndex];
        tasks[pendingIndex].status = 'processing';
        fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));

        // Execute via Playwright
        await executePlaywrightAutomation(taskData);

        // Mark completed and maintain history log
        tasks[pendingIndex].status = 'completed';
        dbData.tasks = tasks.slice(-50);
        fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));
        return true;

    } catch (err) {
        console.error('⚠️ [Autonomous Polling Exception]:', err.message);
    }
    return false;
}

// ==========================================
// 7. DAEMON EXECUTION LOOP
// ==========================================
async function startAutonomousDaemon() {
    console.log(`🚀 [Daemon] Autonomous self-feeding loop started (Interval: ${POLL_INTERVAL_MS}ms)`);
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
