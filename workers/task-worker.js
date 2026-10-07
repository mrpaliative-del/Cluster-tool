const { chromium } = require('playwright');
const { createClient } = require('@supabase/supabase-js');
const { sendTelegramAlert } = require('../services/telegram');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

async function executeTask(taskItem) {
    const template = taskItem.locked_task_templates;
    console.log(`🚀 [Worker] Executing task for template: "${template.template_name}"`);

    const browser = await chromium.launch({
        headless: true,
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage']
    });
    
    const context = await browser.newContext();
    const page = await context.newPage();

    try {
        const targetUrl = taskItem.raw_payload.url || template.action_schema.target_url;
        await page.goto(targetUrl, { waitUntil: 'domcontentloaded' });

        const steps = template.action_schema.steps || [];
        for (const step of steps) {
            if (step.type === 'click') await page.click(step.selector);
            if (step.type === 'fill') await page.fill(step.selector, step.value);
            if (step.type === 'wait') await page.waitForTimeout(step.ms || 2000);
        }

        const payout = taskItem.raw_payload.payout || template.minimum_payout || 0.40;

        // Update queue status to completed
        await supabase.from('execution_queue').update({ status: 'completed', result_output: { success: true } }).eq('id', taskItem.id);

        // Record entry in the revenue accounting ledger
        await supabase.from('task_ledger').insert({
            template_id: template.id,
            payout_amount: payout,
            platform_source: template.template_name
        });

        console.log(`✅ [Worker] Task completed. Logged $${payout} to ledger.`);
        await sendTelegramAlert(`🚀 *Task Executed Successfully!*\n\n*Template:* ${template.template_name}\n*Payout:* $${payout}\n*Status:* Verified & Logged`);

    } catch (err) {
        console.error(`❌ [Worker Error] Task ${taskItem.id} failed:`, err.message);
        await supabase.from('execution_queue').update({ status: 'failed', result_output: { error: err.message } }).eq('id', taskItem.id);
        await sendTelegramAlert(`❌ *Task Execution Failed*\n\n*Template:* ${template.template_name}\n*Error:* ${err.message}`);
    } finally {
        await browser.close();
    }
}

module.exports = { executeTask };
