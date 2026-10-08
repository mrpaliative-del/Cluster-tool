const crypto = require('crypto');

// Configuration
const CLUSTER_URL = 'https://cluster-tool.onrender.com/api/tasks/submit-bundle';
const CLUSTER_SECRET = process.env.CLUSTER_SECRET || 'your-cluster-hmac-secret';

async function generateAndDispatchBundle() {
  // In production, replace these with dynamic fetches from your sitemap or database
  const liveTasks = [
    {
      taskId: `aff_${Date.now()}_1`,
      type: 'affiliate_redirect',
      targetUrl: 'https://example.com/travel/partner-flight-deal',
      expectedMarker: 'Book Flight'
    },
    {
      taskId: `seo_${Date.now()}_2`,
      type: 'seo_og_drift',
      targetUrl: 'https://example.com/flights/lagos-to-jos',
      expectedMarker: 'og:image'
    },
    {
      taskId: `widget_${Date.now()}_3`,
      type: 'widget_liveness',
      targetUrl: 'https://example.com/checkout',
      selector: 'iframe[name^=\'paystack\']'
    }
  ];

  const bundle = {
    batchId: `batch_automated_${Date.now()}`,
    tasks: liveTasks
  };

  const bodyString = JSON.stringify(bundle);
  
  // Cryptographically sign the bundle payload using your cluster secret
  const signature = crypto.createHmac('sha256', CLUSTER_SECRET)
    .update(bodyString)
    .digest('hex');

  console.log(`🚀 [Producer] Dispatching bundle ${bundle.batchId} with ${liveTasks.length} tasks...`);

  try {
    const response = await fetch(CLUSTER_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'x-escrow-signature': signature
      },
      body: bodyString
    });

    const result = await response.json();
    if (response.ok) {
      console.log('✅ [Producer] Successfully queued:', result.message);
    } else {
      console.error('❌ [Producer Rejected]', result);
    }
  } catch (err) {
    console.error('❌ [Producer Network Error]', err.message);
  }
}

generateAndDispatchBundle();
