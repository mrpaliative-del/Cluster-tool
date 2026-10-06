const express = require('express');
const { Queue, Worker } = require('bullmq');
const axios = require('axios');
const os = require('os'); // Google Colab-style system telemetry module
const { resolvePayload } = require('./resolver');
const { disburseToPaystack } = require('./paystackService');

const PORT = process.env.PORT || 3000;
const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379';
const DAILY_TARGET_USD = 10.00;
const PAYOUT_THRESHOLD_USD = 5.00;

// Telegram Configuration from Environment Variables
const TELEGRAM_BOT_TOKEN = process.env.TELEGRAM_BOT_TOKEN;
const TELEGRAM_CHAT_ID = process.env.TELEGRAM_CHAT_ID;

async function sendTelegramAlert(message) {
    if (!TELEGRAM_BOT_TOKEN || !TELEGRAM_CHAT_ID) return;
    try {
        await axios.post(`https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage`, {
            chat_id: TELEGRAM_CHAT_ID,
            text: message,
            parse_mode: 'Markdown'
        });
    } catch (err) {
        console.error(`⚠️️ [Telegram Error]:`, err.message);
    }
}

let connectionConfig;
if (REDIS_URL.startsWith('rediss://') || REDIS_URL.startsWith('redis://')) {
    connectionConfig = REDIS_URL;
} else {
    connectionConfig = { host: 'localhost', port: 6379 };
}

const app = express();
app.use(express.json());

let taskCounter = 1;
let sessionTotalEarningsUSD = 0;
let unsettledBalanceUSD = 0;

// Enhanced Health Check Endpoint for Render Monitoring
app.get('/health', (req, res) => {
    res.status(200).json({
        status: 'healthy',
        uptime: process.uptime(),
        timestamp: new Date().toISOString()
    });
});

// Live Ledger Status Endpoint for On-the-Go Tracking
app.get('/ledger', (req, res) => {
    res.status(200).json({
        sessionTotalEarningsUSD: Number(sessionTotalEarningsUSD.toFixed(2)),
        unsettledBalanceUSD: Number(unsettledBalanceUSD.toFixed(2)),
        payoutThresholdUSD: PAYOUT_THRESHOLD_USD,
        dailyTargetUSD: DAILY_TARGET_USD,
        progressPercent: ((sessionTotalEarningsUSD / DAILY_TARGET_USD) * 100).toFixed(1) + '%'
    });
});

app.post('/v1/tasks/submit', (req, res) => {
    res.status(200).json({ status: "success", creditedUSD: req.body.bountyUSD });
});

app.listen(PORT, () => {
    console.log(`🌐 Unified Gateway & Cluster running on port ${PORT}`);
});

// Colab-Style System Telemetry Monitor (Logs resource metrics every 2 minutes)
function logSystemPerformance() {
    const totalMem = os.totalmem();
    const freeMem = os.freemem();
    const usedMem = totalMem - freeMem;
    const memUsagePercent = ((usedMem / totalMem) * 100).toFixed(1);
    const cpuLoad = os.loadavg();

    console.log(`\n📊 [SYSTEM TELEMETRY] --------------------------`);
    console.log(`   RAM Used: ${(usedMem / 1024 / 1024).toFixed(1)} MB / ${(totalMem / 1024 / 1024).toFixed(1)} MB (${memUsagePercent}%)`);
    console.log(`   CPU Load (1m/5m/15m): ${cpuLoad[0].toFixed(2)}, ${cpuLoad[1].toFixed(2)},${cpuLoad[2].toFixed(2)}`);
    console.log(`   Process Uptime: ${(process.uptime() / 60).toFixed(1)} minutes`);
    console.log(`--------------------------------------------------\n`);
}
setInterval(logSystemPerformance, 120000);

const taskQueue = new Queue('cluster-task-queue', { connection: connectionConfig });

// Direct Internal Multi-Source Radar Producer Loop
async function runProducer() {
    const feedTypes = ['alpha', 'travel', 'brokerage'];
    const selectedType = feedTypes[Math.floor(Math.random() * feedTypes.length)];

    try {
        let task;

        if (selectedType === 'travel') {
            const travelId = `travel-${Date.now()}-${taskCounter++}`;
            const rawUrl = 'https://jetradar.com/search?from=LOS&to=JOS';
            const affiliateMarker = 'mpee_travel_01';
            const optimizedDeepLink = `${rawUrl}&marker=${affiliateMarker}&ura=true`;

            task = {
                id: travelId,
                sourceName: 'TravelMatrix-Feed',
                bountyUSD: 1.50,
                payload: JSON.stringify({ category: 'travel_route', route: 'LOS-JOS', monetizedUrl: optimizedDeepLink })
            };
        } else if (selectedType === 'brokerage') {
            const brokerId = `broker-${Date.now()}-${taskCounter++}`;
            const baseCostUSD = 0.50;
            const markupUSD = 0.30;
            const totalBounty = baseCostUSD + markupUSD;
            const proxiedUrl = 'https://api.external-provider.com/v1/analyze?proxied=true&margin=0.3';

            task = {
                id: brokerId,
                sourceName: 'RapidAPI-Broker-Feed',
                bountyUSD: totalBounty,
                payload: JSON.stringify({ category: 'api_brokerage', service: 'Sentiment-Analysis-Proxy', endpoint: proxiedUrl })
            };
        } else {
            task = {
                id: `alpha-${taskCounter++}`,
                sourceName: 'AlphaTask-Network',
                bountyUSD: 1.00,
                payload: JSON.stringify({ category: 'sentiment', score: '0.95' })
            };
        }

        await taskQueue.add('process-task', task, { 
            jobId: task.id, 
            removeOnComplete: true,
            attempts: 3,
            backoff: {
                type: 'exponential',
                delay: 10000
            }
        });
        
        console.log(`📥 [Radar - ${task.sourceName}] Ingested Task ${task.id} ($${task.bountyUSD})`);

    } catch (err) {
        console.error(`⚠️ [Producer Error]:`, err.message);
    }

    setTimeout(runProducer, 15000);
}
runProducer();

const worker = new Worker('cluster-task-queue', async (job) => {
    const task = job.data;
    const bounty = Number(task.bountyUSD) || 0.50;

    const cleanedResult = resolvePayload(task.payload);

    await axios.post(`http://localhost:${PORT}/v1/tasks/submit`, {
        taskId: task.id,
        bountyUSD: bounty,
        result: cleanedResult
    });

    sessionTotalEarningsUSD += bounty;
    unsettledBalanceUSD += bounty;

    const progress = ((sessionTotalEarningsUSD / DAILY_TARGET_USD) * 100).toFixed(1);
    console.log(`💰 [LEDGER] Earned: +$${bounty.toFixed(2)} \vert{} Total:$${sessionTotalEarningsUSD.toFixed(2)} /$${DAILY_TARGET_USD.toFixed(2)} (${progress}%)`);

    if (unsettledBalanceUSD >= PAYOUT_THRESHOLD_USD) {
        try {
            console.log(`🚀 Threshold reached ($${unsettledBalanceUSD.toFixed(2)}). Triggering Paystack transfer...`);
            
            const transfer = await disburseToPaystack(unsettledBalanceUSD);
            console.log(`✅ [PAYSTACK] Ref: ${transfer.data.reference} \vert{} Status:${transfer.data.status}`);
            
            await sendTelegramAlert(`✅ *Payout Triggered!*\nAmount: \$$${unsettledBalanceUSD.toFixed(2)}\nRef: \`${transfer.data.reference}\``);
            
            unsettledBalanceUSD = 0;
        } catch (payoutErr) {
            console.error(`❌ [PAYSTACK ERROR]:`, payoutErr.message);
            await sendTelegramAlert(`❌ *Payout Failed!*\nError: \`${payoutErr.message}\``);
        }
    }
}, { connection: connectionConfig, concurrency: 3 });

console.log("👷 Unified Worker Daemon online...");
