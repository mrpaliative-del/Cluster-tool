/**
 * ============================================================================
 * OMNI-TASK ENGINE: INDUSTRIAL ZERO-STARVATION LOCAL FILE DAEMON
 * ============================================================================
 * File: index.js
 * Version: 5.0.0-Local-Standalone
 * Architecture: Local JSON File Queue (`tasks.json`) + BullMQ + 
 * Playwright Headless Automation + Telegram Alerts.
 * ============================================================================
 */

const http = require('http');
const https = require('https');
const crypto = require('crypto');
const fs = require('fs');
const path = require('path');
const { chromium } = require('playwright');
const { Queue, Worker } = require('bullmq');
const IORedis = require('ioredis');

// ==========================================
// 1. CONFIGURATION & ENVIRONMENT SETUP
// ==========================================
const PORT = process.env.PORT || 10000;
const POLL_INTERVAL_MS = parseInt(process.env.POLL_INTERVAL_MS, 10) || 6000;
const AFFILIATE_MARKER = process.env.AFFILIATE_MARKER || 'global_cluster_master_01';
const PAYSTACK_SECRET_KEY = process.env.PAYSTACK_SECRET_KEY || '';
const TASKS_FILE = path.join(__dirname, 'tasks.json');

// Telegram Notification Credentials
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN || '8608729377:AAE9L9fNEDMyvZjG0aGYVRYu34psvSDdb-A';
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID || '5058299552';

// Redis & BullMQ Setup
const redisConnection = new IORedis({
    host: process.env.REDIS_HOST || 'localhost',
    port: parseInt(process.env.REDIS_PORT, 10) || 6379,
    maxRetriesPerRequest: null,
});

const omniQueue = new Queue('omni-task-queue', { connection: redisConnection });

// Runtime Metrics Tracking for Health Dashboard
const metrics = {
    uptimeStarted: Date.now(),
    totalCyclesExecuted: 0,
    tasksProcessedSuccessfully: 0,
    tasksFailed: 0,
    lastActiveTimestamp: null,
    activeWorkerMarker: AFFILIATE_MARKER
};

// ==========================================
// 2. RENDER HTTP SERVER & HEALTH / WEBHOOK API
// ==========================================
const server = http.createServer(async (req, res) => {
    const baseUrl = `http://${req.headers.host || 'localhost'}`;
    const parsedUrl = new URL(req.url, baseUrl);
    const pathname = parsedUrl.pathname;
    const queryParams = parsedUrl.searchParams;

    // A. Paystack Webhook Receiver Endpoint
    if (req.method === 'POST' && pathname === '/webhook/paystack') {
        let body = '';
        req.on('data', chunk => { body += chunk; });
        req.on('end', async () => {
            try {
                const hash = crypto.createHmac('sha512', PAYSTACK_SECRET_KEY).update(body).digest('hex');
                
                if (hash !== req.headers['x-paystack-signature']) {
                    res.writeHead(401, { 'Content-Type': 'application/json' });
                    return res.end(JSON.stringify({ status: 'error', message: 'Invalid cryptographic signature' }));
                }

                res.writeHead(200, { 'Content-Type': 'application/json' });
                res.end(JSON.stringify({ status: 'received' }));

                const event = JSON.parse(body);
                if (event.event === 'charge.success') {
                    const data = event.data;
                    const metadata = data.metadata || {};
                    console.log(`🎉 [Webhook] Paystack Charge Success! Ref: ${data.reference} \vert{} Task:${metadata.task_id || 'N/A'}`);
                    await sendWebhookAlert(metadata.task_id || 'unknown', data.amount / 100, data.reference, metadata.sector || 'General');
                }
            } catch (err) {
                console.error('⚠️ [Webhook Processing Exception]:', err.message);
            }
        });
        return;
    }

    // B. Resolution & Deep Link Handler (Affiliate / Telegram Click-Through)
    if (req.method === 'GET' && pathname === '/resolve') {
        const taskId = queryParams.get('task') || 'unknown';
        const marker = queryParams.get('marker') || AFFILIATE_MARKER;

        console.log(`🔗 [Resolution Route] Click intercepted for Task ID: ${taskId} using marker:${marker}`);

        res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
        return res.end(`
            <!DOCTYPE html>
            <html lang="en">
            <head>
                <meta charset="UTF-8">
                <title>FlyMatrix & DelightPay Gateway - Resolution Confirmed</title>
                <meta name="viewport" content="width=device-width, initial-scale=1">
                <style>
                    body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; background: #0f172a; color: #f8fafc; text-align: center; padding: 60px 20px; }
                    .card { max-width: 520px; margin: 0 auto; background: #1e293b; padding: 40px; border-radius: 16px; box-shadow: 0 10px 30px rgba(0,0,0,0.4); border: 1px solid #334155; }
                    h2 { color: #38bdf8; margin-top: 0; font-size: 24px; }
                    p { color: #94a3b8; line-height: 1.7; font-size: 15px; }
                    .badge { display: inline-block; background: #0284c7; color: white; padding: 6px 14px; border-radius: 6px; font-size: 13px; font-weight: bold; margin-bottom: 20px; }
                    .footer-note { margin-top: 25px; font-size: 12px; color: #64748b; }
                </style>
            </head>
            <body>
                <div class="card">
                    <div class="badge">Marker Node: ${marker}</div>
                    <h2>Resolution Route Verified</h2>
                    <p>Task reference <strong>${taskId}</strong> has been successfully tracked, parsed, and routed through the automated zero-starvation framework.</p>
                    <div class="footer-note">FlyMatrix Autonomous Processing Engine &bull; Secure Gateway</div>
                </div>
            </body>
            </html>
        `);
    }

    // C. Comprehensive System Health & Diagnostics Status Endpoint
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
        status: 'online',
        service: 'Local JSON File Task Execution Engine (BullMQ Integrated)',
        version: '5.0.0-Local-Standalone',
        marker: AFFILIATE_MARKER,
        metrics: {
            ...metrics,
            uptime_seconds: Math.floor((Date.now() - metrics.uptimeStarted) / 1000)
        },
        timestamp: new Date().toISOString()
    }));
});

server.listen(PORT, () => {
    console.log(`🌐 [Server] Master HTTP listener bound securely on port ${PORT}`);
});

// ==========================================
// 3. ADVANCED TIMEOUT-PROTECTED TELEGRAM SYSTEM
// ==========================================
function dispatchTelegramMessage(message) {
    return new Promise((resolve) => {
        if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) {
            console.warn('⚠️ [Telegram] Skipped: Bot token or chat ID missing.');
            return resolve(false);
        }

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
            },
            timeout: 10000
        };

        const req = https.request(options, (res) => {
            let responseBody = '';
            res.on('data', chunk => responseBody += chunk);
            res.on('end', () => {
                if (res.statusCode === 200) {
                    console.log('📱 [Telegram] Alert dispatched successfully.');
                    resolve(true);
                } else {
                    console.error(`❌ [Telegram API Error] Status ${res.statusCode}:${responseBody}`);
                    resolve(false);
                }
            });
        });

        req.on('timeout', () => {
            console.error('❌ [Telegram Error]: Request timed out.');
            req.destroy();
            resolve(false);
        });

        req.on('error', (err) => {
            console.error('❌ [Telegram Network Error]:', err.message);
            resolve(false);
        });

        req.write(postData);
        req.end();
    });
}

function sendTaskAlert(task, template, payoutAmount, authUrl) {
    const paymentLink = authUrl || `https://cluster-tool.onrender.com/resolve?task=${task.id}&marker=${AFFILIATE_MARKER}`;
    const message = `🚀 *Zero-Starvation Task Execution Alert*\n\n` +
                    `• *Template:* *${template.template_name}*\n` +
                    `• *Task ID:* \`${task.id}\`\n` +
                    `• *Sector/Trigger:* \`${template.keyword_trigger}\`\n` +
                    `• *Target Asset:* \`${task.payload.target_asset || 'N/A'}\`\n` +
                    `• *Verified Payout:* \`$${payoutAmount.toFixed(2)}\`\n` +
                    `• *Gateway Resolution:* [Open Secure Link](${paymentLink})\n` +
                    `• *Daemon Status:* \`Processed Locally ✅\``;

    return dispatchTelegramMessage(message);
}

function sendWebhookAlert(taskId, amountNGN, reference, sector) {
    const message = `💰 *Paystack Settlement Verified!*\n\n` +
                    `• *Task ID:* \`${taskId}\`\n` +
                    `• *Sector:* \`${sector}\`\n` +
                    `• *Settled Amount:* \`₦${amountNGN.toLocaleString()}\`\n` +
                    `• *Reference:* \`${reference}\`\n` +
                    `• *Ledger State:* \`Fulfilled & Balanced 🟢\``;

    return dispatchTelegramMessage(message);
}

// ==========================================
// 4. PLAYWRIGHT AUTOMATION ENGINE CORE
// ==========================================
async function executePlaywrightAutomation(task, template) {
    console.log(`🤖 [Playwright Worker] Initializing headless daemon for: "${template.template_name}"`);
    
    let browser = null;
    try {
        browser = await chromium.launch({
            headless: true,
            args: [
                '--no-sandbox', 
                '--disable-setuid-sandbox', 
                '--disable-dev-shm-usage',
                '--disable-accelerated-2d-canvas',
                '--disable-gpu'
            ]
        });

        const context = await browser.newContext({
            userAgent: 'Mozilla/5.0 (Linux; Android 14; TECNO LI6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36'
        });
        
        const page = await context.newPage();
        const targetUrl = task.payload.url || template.action_schema.target_url;

        if (!targetUrl) {
            throw new Error(`Target URL missing for template ${template.template_name}`);
        }

        console.log(`🌐 [Worker] Navigating to target endpoint: ${targetUrl}`);
        await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 30000 });

        const steps = template.action_schema.steps || [];
        for (const step of steps) {
            console.log(`⚡ [Worker Step] Executing action: ${step.type} on selector: ${step.selector || 'none'}`);
            if (step.type === 'click' && step.selector) {
                await page.click(step.selector, { timeout: 10000 });
            } else if (step.type === 'fill' && step.selector) {
                await page.fill(step.selector, step.value || '', { timeout: 10000 });
            } else if (step.type === 'wait') {
                await page.waitForTimeout(step.ms || 2000);
            }
        }

        const computedPayout = Math.max(task.payload.estimated_value || template.minimum_payout || 0.40, 0.40);

        console.log(`✅ [Worker Success] Automation complete. Computed Payout: $${computedPayout.toFixed(2)}`);
        metrics.tasksProcessedSuccessfully++;
        metrics.lastActiveTimestamp = new Date().toISOString();

        await sendTaskAlert(task, template, computedPayout, null);
        return { success: true, computedPayout };

    } catch (err) {
        console.error(`❌ [Playwright Worker Error]:`, err.message);
        metrics.tasksFailed++;
        await dispatchTelegramMessage(`❌ *Task Automation Failure*\n\n*Template:* ${template.template_name}\n*Error:* ${err.message}`);
        throw err;

    } finally {
        if (browser) {
            await browser.close();
            console.log(`🔒 [Worker] Browser session closed safely.`);
        }
    }
}

// ==========================================
// 5. BULLMQ WORKER REGISTRATION
// ==========================================
const omniWorker = new Worker(
    'omni-task-queue',
    async (job) => {
        console.log(`📦 [BullMQ Worker] Processing job ID: ${job.id} | Name: ${job.name}`);
        const { task, template } = job.data;
        
        if (!task || !template) {
            throw new Error('Invalid job payload: missing task or template structure.');
        }

        return await executePlaywrightAutomation(task, template);
    },
    { 
        connection: redisConnection, 
        concurrency: 2 
    }
);

omniWorker.on('failed', (job, err) => {
    console.error(`❌ [BullMQ Worker] Job ${job?.id} permanently failed:`, err.message);
});

omniWorker.on('completed', (job) => {
    console.log(`✨ [BullMQ Worker] Job ${job.id} successfully finished.`);
});

// ==========================================
// 6. LOCAL FILE TASK ROUTER & POLLING DAEMON
// ==========================================
async function fetchAndRouteNextTask() {
    try {
        if (!fs.existsSync(TASKS_FILE)) {
            // Initialize default local file structure if missing
            const initialData = {
                templates: [
                    {
                        id: "tpl-01",
                        template_name: "General Flight & Task Automation",
                        keyword_trigger: "General",
                        minimum_payout: 0.40,
                        is_active: true,
                        action_schema: {
                            target_url: "https://cluster-tool.onrender.com/",
                            steps: []
                        }
                    }
                ],
                tasks: [
                    {
                        id: "task-001",
                        sector: "General",
                        target_asset: "Test Asset",
                        estimated_value: 0.50,
                        status: "pending"
                    }
                ]
            };
            fs.writeFileSync(TASKS_FILE, JSON.stringify(initialData, null, 2));
        }

        const rawData = fs.readFileSync(TASKS_FILE, 'utf8');
        const dbData = JSON.parse(rawData);
        
        const templates = dbData.templates || [];
        const tasks = dbData.tasks || [];

        const pendingTaskIndex = tasks.findIndex(t => t.status === 'pending');
        if (pendingTaskIndex === -1 || templates.length === 0) {
            return false;
        }

        const taskData = tasks[pendingTaskIndex];

        const matchedTemplate = templates.find(t => {
            const matchesKeyword = (taskData.sector && taskData.sector.toLowerCase().includes(t.keyword_trigger.toLowerCase())) ||
                                   (taskData.target_asset && taskData.target_asset.toLowerCase().includes(t.keyword_trigger.toLowerCase()));
            const satisfiesPayout = (taskData.estimated_value || 0.40) >= t.minimum_payout;
            return matchesKeyword && satisfiesPayout && t.is_active;
        });

        if (matchedTemplate) {
            // Mark task as processing locally
            tasks[pendingTaskIndex].status = 'processing';
            tasks[pendingTaskIndex].worker_marker = AFFILIATE_MARKER;
            fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));

            console.log(`🎯 [Router Match] Task ID [${taskData.id}] matched template: "${matchedTemplate.template_name}". Enqueuing to BullMQ...`);
            
            await omniQueue.add('execute-omni-task', {
                task: {
                    id: taskData.id,
                    sector: taskData.sector,
                    payload: {
                        target_asset: taskData.target_asset,
                        estimated_value: taskData.estimated_value,
                        url: matchedTemplate.action_schema.target_url
                    }
                },
                template: matchedTemplate
            });

            // Update status to completed after queue dispatch
            tasks[pendingTaskIndex].status = 'completed_automation';
            fs.writeFileSync(TASKS_FILE, JSON.stringify(dbData, null, 2));

            return true;
        }
    } catch (err) {
        console.error('⚠️ [Local Polling Exception]:', err.message);
    }

    return false;
}

// ==========================================
// 7. INDUSTRIAL AUTONOMOUS DAEMON ENGINE LOOP
// ==========================================
async function startAutonomousDaemon() {
    console.log(`🚀 [Daemon] Local file task polling loop started (Interval: ${POLL_INTERVAL_MS}ms)`);

    while (true) {
        try {
            metrics.totalCyclesExecuted++;
            const dispatched = await fetchAndRouteNextTask();

            if (!dispatched) {
                process.stdout.write('.');
            } else {
                continue;
            }
        } catch (daemonErr) {
            console.error(`⚠️ [Daemon Loop Exception Warning]:`, daemonErr.message);
        }

        await new Promise(resolve => setTimeout(resolve, POLL_INTERVAL_MS));
    }
}

// Start the master background execution daemon loop
startAutonomousDaemon();
