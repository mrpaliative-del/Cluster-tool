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

let connectionConfig;
if (REDIS_URL.startsWith('rediss://') || REDIS_URL.startsWith('redis://')) {
    connectionConfig = REDIS_URL;
} else {
    connectionConfig = { host: 'localhost', port: 6379 };
}

const app = express();
app.use(express.json());

let taskCounter = 1;

// Enhanced Health Check Endpoint for Render Monitoring
app.get('/health', (req, res) => {
    res.status(200).json({
        status: 'healthy',
        uptime: process.uptime(),
        timestamp: new Date().toISOString()
    });
});

// Original Alpha Feed
app.get('/v1/sources/alpha-feed', (req, res) => {
    res.json({
        sourceName: 'AlphaTask-Network',
        tasks: [
            { id: `alpha-${taskCounter++}`, bountyUSD: 1.00, payload: '{"category": "sentiment", "score": "0.95"}' },
            { id: `alpha-${taskCounter++}`, bountyUSD: 1.50, payload: '{"category": "entity_tag", "verified": true}' }
        ]
    });
});

// New Revenue Module 1: Travel & Route Spreads (Travelpayouts Integration)
app.get('/v1/sources/travel-feed', (req, res) => {
    const travelId = `travel-${Date.now()}-${taskCounter++}`;
    const rawUrl = 'https://jetradar.com/search?from=LOS&to=JOS';
    const affiliateMarker = 'mpee_travel_01';
    const optimizedDeepLink = `${rawUrl}&marker=${affiliateMarker}&ura=true`;

    res.json({
        sourceName: 'TravelMatrix-Feed',
        tasks: [
            { 
                id: travelId, 
                bountyUSD: 1.50, 
                payload: JSON.stringify({ category: 'travel_route', route: 'LOS-JOS', monetizedUrl: optimizedDeepLink }) 
            }
        ]
    });
});

// New Revenue Module 2: API & Data Micro-Brokerage
app.get('/v1/sources/api-broker-feed', (req, res) => {
    const brokerId = `broker-${Date.now()}-${taskCounter++}`;
    const baseCostUSD = 0.50;
    const markupUSD = 0.30;
    const totalBounty = baseCostUSD + markupUSD;
    const proxiedUrl = 'https://api.external-provider.com/v1/analyze?proxied=true&margin=0.3';

    res.json({
        sourceName: 'RapidAPI-Broker-Feed',
        tasks: [
            { 
                id: brokerId, 
                bountyUSD: totalBounty, 
                payload: JSON.stringify({ category: 'api_brokerage', service: 'Sentiment-Analysis-Proxy', endpoint: proxiedUrl }) 
            }
        ]
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
    console.log(`   CPU Load (1m/5m/15m): ${cpuLoad[0].toFixed(2)}, ${cpuLoad[1].toFixed(2)}, ${cpuLoad[2].toFixed(2)}`);
    console.log(`   Process Uptime: ${(process.uptime() / 60).toFixed(1)} minutes`);
    console.log(`--------------------------------------------------\n`);
}
setInterval(logSystemPerformance, 120000);

const taskQueue = new Queue('cluster-task-queue', { connection: connectionConfig });

// Multi-Source Radar Producer Loop
async function runProducer() {
    const endpoints = [
        '/v1/sources/alpha-feed',
        '/v1/sources/travel-feed',
        '/v1/sources/api-broker-feed'
    ];

    for (const endpoint of endpoints) {
        try {
            const response = await axios.get(`http://localhost:${PORT}${endpoint}`, { timeout: 3000 });
            const tasks = response.data.tasks || [];

            for (const task of tasks) {
                task.sourceName = response.data.sourceName;
                await taskQueue.add('process-task', task, { 
                    jobId: task.id, 
                    removeOnComplete: true,
                    attempts: 3,
                    backoff: {
                        type: 'exponential',
                        delay: 10000 // Intelligent retry backoff starting at 10s
                    }
                });
                console.log(`📥 [Radar - ${response.data.sourceName}] Ingested Task ${task.id} ($${task.bountyUSD})`);
            }
        } catch (err) {
            // Silently catch network hiccups on self-polling endpoints to keep loop resilient
        }
    }

    setTimeout(runProducer, 15000); // Poll feeds every 15 seconds
}
runProducer();

let sessionTotalEarningsUSD = 0;
let unsettledBalanceUSD = 0;

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
    console.log(`💰 [LEDGER] Earned: +$${bounty.toFixed(2)} | Total: $${sessionTotalEarningsUSD.toFixed(2)} / $${DAILY_TARGET_USD.toFixed(2)} (${progress}%)`);

    if (unsettledBalanceUSD >= PAYOUT_THRESHOLD_USD) {
        try {
            console.log(`🚀 Threshold reached ($${unsettledBalanceUSD.toFixed(2)}). Triggering Paystack transfer...`);
            
            const transfer = await disburseToPaystack(unsettledBalanceUSD);
            console.log(`✅ [PAYSTACK] Ref: ${transfer.data.reference} | Status: ${transfer.data.status}`);
            unsettledBalanceUSD = 0;
        } catch (payoutErr) {
            console.error(`❌ [PAYSTACK ERROR]:`, payoutErr.message);
        }
    }
}, { connection: connectionConfig, concurrency: 3 });

console.log("👷 Unified Worker Daemon online...");
