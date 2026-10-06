const axios = require('axios');

async function disburseToPaystack(amountUSD, recipientCode = 'RCP_default') {
    const amountKobo = Math.round(amountUSD * 1500 * 100);

    const payload = {
        source: "balance",
        amount: amountKobo,
        currency: "NGN",
        recipient: recipientCode,
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
