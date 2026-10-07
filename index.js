const express = require('express');
const { disburseToPaystack } = require('./paystackService');
const axios = require('axios');

const app = express();
const PORT = process.env.PORT || 10000;

app.use(express.json());

// In-memory ledger and state tracking
let unsettledBalanceUSD = 0;
let totalProcessedTasks = 0;
const PIS_THRESHOLD = 5.00; // Payout threshold

// Telegram alert utility
async function sendTelegramAlert(message) {
    const botToken = process.env.TELEGRAM_BOT_TOKEN;
    const chatId = process.env.TELEGRAM_CHAT_ID;
    if (!botToken || !chatId) return;

    try {
        await axios.post(`https://api.telegram.org/bot${botToken}/sendMessage`, {
            chat_id: chatId,
            text: message,
            parse_mode: 'Markdown'
        });
    } catch (err) {
        console.error('❌ Failed to send Telegram alert:', err.message);
    }
}

// Multi-source feed task simulation array
const feeds = [
    { name: 'Radar - RapidAPI-Broker-Feed', type: 'broker', baseEarn: 0.80 },
    { name: 'Radar - Logistics-Transit-Feed', type: 'transit', baseEarn: 1.60 },
    { name: 'Radar - AlphaTask-Network', type: 'alpha', baseEarn: 1.00 },
    { name: 'Radar - TravelMatrix-Feed', type: 'travel', baseEarn: 1.50 },
    { name: 'Radar - SEO-Optimizer-Feed', type: 'seo', baseEarn: 0.85 }
];

// Background Unified Worker Daemon Loop (runs every 15 seconds)
setInterval(async () => {
    totalProcessedTasks++;
    const randomFeed = feeds[Math.floor(Math.random() * feeds.length)];
    const taskID = `${randomFeed.type}-${Date.now()}-${totalProcessedTasks}`;
    const earnedUSD = randomFeed.baseEarn;

    unsettledBalanceUSD += earnedUSD;
    const progressPercent = Math.min((unsettledBalanceUSD / PIS_THRESHOLD) * 100, 100).toFixed(1);

    console.log(`📥 [${randomFeed.name}] Processed Task ${taskID} \vert{} Earned: +$${earnedUSD.toFixed(2)} \vert{} Total:$${unsettledBalanceUSD.toFixed(2)} (${progressPercent}%)`);

    // Check if payout threshold is reached
    if (unsettledBalanceUSD >= PIS_THRESHOLD) {
        console.log(`🚀 Threshold reached ($${unsettledBalanceUSD.toFixed(2)}). Triggering Paystack transfer...`);
        
        try {
            const payoutResult = await disburseToPaystack(unsettledBalanceUSD);
            console.log(`✅ Payout successful:`, payoutResult);
            await sendTelegramAlert(`✅ *Payout Successful!*\nTransferred balance for $${unsettledBalanceUSD.toFixed(2)}.`);
            
            // Reset balance after success
            unsettledBalanceUSD = 0;
        } catch (payoutErr) {
            // Captures Paystack's exact API rejection validation string
            const exactReason = payoutErr.response?.data?.message || JSON.stringify(payoutErr.response?.data) || payoutErr.message;
            
            console.error(`❌ [PAYSTACK ERROR]:`, exactReason);
            await sendTelegramAlert(`❌ *Payout Failed!*\nError: \`${exactReason}\``);
            
            // Reset balance to avoid getting stuck in a loop of failing requests
            unsettledBalanceUSD = 0;
        }
    }
}, 15000);

// System Telemetry Logger (every 2 minutes)
setInterval(() => {
    const memoryUsage = process.memoryUsage();
    const heapUsedMB = (memoryUsage.heapUsed / 1024 / 1024).toFixed(1);
    const heapTotalMB = (memoryUsage.heapTotal / 1024 / 1024).toFixed(1);
    const uptimeMinutes = (process.uptime() / 60).toFixed(1);

    console.log(`\n📊 [SYSTEM TELEMETRY] --------------------------`);
    console.log(`   RAM Heap Used: ${heapUsedMB} MB / ${heapTotalMB} MB`);
    console.log(`   Process Uptime: ${uptimeMinutes} minutes`);
    console.log(`--------------------------------------------------\n`);
}, 120000);

// Health check endpoint
app.get('/health', (req, res) => {
    res.status(200).json({ status: 'online', daemon: 'Unified In-Memory Worker Daemon' });
});

// Ledger endpoint for viewing current running stats
app.get('/ledger', (req, res) => {
    res.status(200).json({
        unsettledBalanceUSD: Number(unsettledBalanceUSD.toFixed(2)),
        totalProcessedTasks,
        threshold: PIS_THRESHOLD,
        status: 'Active'
    });
});

// Start Express Server
app.listen(PORT, () => {
    console.log(`👷 Unified In-Memory Worker Daemon online...`);
    console.log(`🌐 Unified Gateway & Cluster running on port ${PORT}`);
});
