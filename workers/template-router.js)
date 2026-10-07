const { createClient } = require('@supabase/supabase-js');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

async function routeScrapedLeadToTemplate(scrapedData) {
    console.log(`📥 [Router] Evaluating incoming lead against locked templates...`);

    const { data: templates, error } = await supabase
        .from('locked_task_templates')
        .select('*')
        .eq('is_active', true);

    if (error) {
        console.error('❌ [Router Error] Failed to fetch templates:', error.message);
        return { status: 'error', error: error.message };
    }

    // Match incoming data text against template keyword triggers and payout minimums
    const matchedTemplate = templates.find(t => 
        scrapedData.text.toLowerCase().includes(t.keyword_trigger.toLowerCase()) &&
        (scrapedData.payout || 0.40) >= t.minimum_payout
    );

    if (!matchedTemplate) {
        console.log(`⏩ [Router] Lead did not meet locked template thresholds. Skipping.`);
        return { status: 'ignored' };
    }

    console.log(`🎯 [Match Found!] Routing lead to template: "${matchedTemplate.template_name}"`);

    const { data: jobLog, error: jobError } = await supabase
        .from('execution_queue')
        .insert({
            template_id: matchedTemplate.id,
            raw_payload: scrapedData,
            status: 'queued'
        })
        .select();

    if (jobError) {
        console.error('❌ [Router Error] Failed to queue job:', jobError.message);
        throw jobError;
    }

    return { status: 'queued', jobId: jobLog[0].id, template: matchedTemplate.template_name };
}

module.exports = { routeScrapedLeadToTemplate };
