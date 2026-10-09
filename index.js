// ==========================================
// REAL LIVE ECOSYSTEM TELEMETRY ENGINE (NO SIMULATION)
// ==========================================
async function fetchRealEcosystemTelemetry() {
    const liveSignals = [];
    const timestamp = new Date().toISOString();

    // 1. Live Travelpayouts / Aviasales Public Data API Query for LOS -> JOS
    try {
        const response = await fetch('https://api.travelpayouts.com/v1/prices/cheap?origin=LOS&destination=JOS&currency=USD', {
            headers: {
                'X-Access-Token': TRAVELPAYOUTS_API_KEY || ''
            }
        });
        const data = await response.json();

        if (data && data.success && data.data && data.data.JOS) {
            const keys = Object.keys(data.data.JOS);
            if (keys.length > 0) {
                const flightRecord = data.data.JOS[keys[0]];
                const liveFare = flightRecord.price;
                const liveDeepLink = `https://www.aviasales.com/search?origin=LOS&destination=JOS&marker=${TRAVELPAYOUTS_MARKER}`;

                liveSignals.push({
                    sector: 'Travel Arbitrage (Live API)',
                    route: 'LOS -> JOS',
                    metric: `Live Market Fare: $${liveFare}`,
                    status: 'Live API Payload Captured',
                    target_url: liveDeepLink,
                    estimated_value_usd: Number((liveFare * 0.04).toFixed(2)), // Computed purely from live fetched fare
                    timestamp
                });
            }
        } else {
            // If no active flight record is returned by the live feed, record the live network check state
            liveSignals.push({
                sector: 'Travel Arbitrage (Live API)',
                route: 'LOS -> JOS',
                metric: `Live Endpoint Connected (Marker: ${TRAVELPAYOUTS_MARKER})`,
                status: 'Awaiting Active Flight Matrix Stream',
                target_url: `https://www.aviasales.com/search?origin=LOS&destination=JOS&marker=${TRAVELPAYOUTS_MARKER}`,
                estimated_value_usd: 0.00,
                timestamp
            });
        }
    } catch (err) {
        liveSignals.push({
            sector: 'Travel Arbitrage (Live API)',
            route: 'LOS -> JOS',
            metric: `Network Query Error: ${err.message}`,
            status: 'Connection Interrupted',
            target_url: `https://www.aviasales.com/search?origin=LOS&destination=JOS&marker=${TRAVELPAYOUTS_MARKER}`,
            estimated_value_usd: 0.00,
            timestamp
        });
    }

    // 2. Live Paystack Gateway Production Handshake Check
    try {
        const paystackRes = await fetch('https://api.paystack.co/integration/payment_session_timeout', {
            headers: {
                'Authorization': `Bearer ${PAYSTACK_SECRET_KEY}`
            }
        });
        const paystackData = await paystackRes.json();

        liveSignals.push({
            sector: 'Fintech Rail (Live API)',
            metric: `Paystack Handshake Status: ${paystackRes.status}`,
            status: paystackData.status ? 'Live Rails Verified' : 'Endpoint Active',
            target_url: 'https://dashboard.paystack.com',
            estimated_value_usd: 0.00, // Zero simulated money—wallet credits exclusively on real charge.success webhooks
            timestamp
        });
    } catch (err) {
        liveSignals.push({
            sector: 'Fintech Rail (Live API)',
            metric: `Paystack Handshake Error: ${err.message}`,
            status: 'Connection Failed',
            target_url: 'https://dashboard.paystack.com',
            estimated_value_usd: 0.00,
            timestamp
        });
    }

    metrics.arbitrageSignalsDetected += liveSignals.length;
    return liveSignals;
}
