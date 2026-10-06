const axios = require('axios');

async function generateRecipient() {
    try {
        const response = await axios.post('https://api.paystack.co/transferrecipient', {
            type: "nuban",
            name: "Mpee global ventures", // Your exact registered business name on OPay
            account_number: "8063749774",
            bank_code: "999992", // OPay NIBSS code
            currency: "NGN"
        }, {
            headers: {
                Authorization: `Bearer ${process.env.PAYSTACK_SECRET_KEY}`, // Or replace with your 'sk_live_...' key string directly
                'Content-Type': 'application/json'
            }
        });
        
        console.log("SUCCESS! Your Recipient Code is:", response.data.data.recipient_code);
    } catch (error) {
        console.error("Error:", error.response?.data || error.message);
    }
}

generateRecipient();
