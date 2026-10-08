import { chromium } from 'playwright';
import crypto from 'crypto';

let sharedBrowser = null;

async function getSharedBrowser() {
  if (!sharedBrowser || !sharedBrowser.isConnected()) {
    sharedBrowser = await chromium.launch({
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-dev-shm-usage',
        '--disable-accelerated-2d-canvas',
        '--disable-gpu'
      ]
    });
  }
  return sharedBrowser;
}

export async function executeOptimizedTaskBundle(rawBundlePayload, clientSignature, secretKey, maxConcurrency = 4) {
  const computedHash = crypto.createHmac('sha512', secretKey).update(rawBundlePayload).digest('hex');
  if (!crypto.timingSafeEqual(Buffer.from(computedHash, 'hex'), Buffer.from(clientSignature, 'hex'))) {
    throw new Error('Security Halt: Invalid bundle signature.');
  }

  const { batchId, tasks } = JSON.parse(rawBundlePayload.toString('utf8'));
  const browser = await getSharedBrowser();
  let index = 0;
  const results = [];

  async function worker() {
    while (index < tasks.length) {
      const currentIndex = index++;
      const task = tasks[currentIndex];
      const taskStart = Date.now();
      let context;

      try {
        context = await browser.newContext({
          userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        });

        const page = await context.newPage();

        // Drop unnecessary assets for max velocity
        await page.route('**/*', (route) => {
          const type = route.request().resourceType();
          if (['image', 'stylesheet', 'font', 'media'].includes(type)) {
            route.abort();
          } else {
            route.continue();
          }
        });

        const response = await page.goto(task.targetUrl, {
          waitUntil: 'commit',
          timeout: 6000
        });

        const statusCode = response ? response.status() : 0;
        const finalUrl = page.url();

        results.push({
          taskId: task.taskId,
          status: statusCode >= 200 && statusCode < 400 ? 'SUCCESS' : 'FAILED',
          statusCode,
          finalUrl,
          latencyMs: Date.now() - taskStart
        });

      } catch (err) {
        results.push({
          taskId: task.taskId,
          status: 'ERROR',
          error: err.message,
          latencyMs: Date.now() - taskStart
        });
      } finally {
        if (context) await context.close();
      }
    }
  }

  const activeWorkers = Array.from({ length: Math.min(maxConcurrency, tasks.length) }, () => worker());
  await Promise.all(activeWorkers);

  return { batchId, processedCount: tasks.length, results };
}
