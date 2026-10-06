const axios = require('axios');

async function disburseToPaystack(amountUSD, recipientCode = process.env.PAYSTACK_RECIPIENT_CODE || 'RCP_default') {
    // Convert USD to NGN Kobo (using conversion multiplier)
    const amountKobo = Math.round(amountUSD * 1500 * 100);

    // Generate a unique idempotency reference to prevent duplicate transfers on network retries
    const uniqueReference = `MPEE-PAYOUT-${Date.now()}-${Math.floor(Math.random() * 1000)}`;

    const payload = {
        source: "balance",
        amount: amountKobo,
        currency: "NGN",
        recipient: recipientCode,
        reference: uniqueReference,
        reason: "Micro-task Automated Payout Settlement"
    };

    const response = await axios.post('https://api.paystack.co/transfer', payload, {
        headers: {
            Authorization: `Bearer ${process.env.PAYSTACK_SECRET_KEY}`,
            'Content-Type': 'application/json'
        },
        timeout: 6000
    });
    
    return response.data;
}

module.exports = { disburseToPaystack };
