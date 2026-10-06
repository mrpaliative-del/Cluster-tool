const express = require('express');
const { Queue, Worker } = require('bullmq');
const axios = require('axios');
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

app.get('/v1/sources/alpha-feed', (req, res) => {
    res.json({
        sourceName: 'AlphaTask-Network',
        tasks: [
            { id: `alpha-${taskCounter++}`, bountyUSD: 1.00, payload: '{"category": "sentiment", "score": "0.95"}' },
            { id: `alpha-${taskCounter++}`, bountyUSD: 1.50, payload: '{"category": "entity_tag", "verified": true}' }
        ]
    });
});

app.post('/v1/tasks/submit', (req, res) => {
    res.status(200).json({ status: "success", creditedUSD: req.body.bountyUSD });
});

app.listen(PORT, () => {
    console.log(`🌐 Unified Gateway & Cluster running on port ${PORT}`);
});

const taskQueue = new Queue('cluster-task-queue', { connection: connectionConfig });

async function runProducer() {
    try {
        const response = await axios.get(`http://localhost:${PORT}/v1/sources/alpha-feed`, { timeout: 3000 });
        const tasks = response.data.tasks || [];

        for (const task of tasks) {
            task.sourceName = response.data.sourceName;
            await taskQueue.add('process-task', task, { jobId: task.id, removeOnComplete: true });
            console.log(`📥 [Producer] Ingested Task ${task.id} ($${task.bountyUSD})`);
        }
    } catch (err) {}
    setTimeout(runProducer, 5000);
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
