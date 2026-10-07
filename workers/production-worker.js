const { createClient } = require('@supabase/supabase-js');
const { executeTask } = require('./task-worker');

const supabase = createClient(process.env.SUPABASE_URL, process.env.SUPABASE_SERVICE_ROLE_KEY);

async function runProductionDaemon() {
    console.log('🛡️ [Daemon] Polling execution queue for pending tasks...');

    const { data: tasks, error } = await supabase
        .from('execution_queue')
        .select('*, locked_task_templates(*)')
        .eq('status', 'queued')
        .limit(1);

    if (error) {
        console.error('❌ [Daemon Error] Queue poll failed:', error.message);
    } else if (tasks && tasks.length > 0) {
        const task = tasks[0];
        // Mark as processing to prevent duplicate pickup
        await supabase.from('execution_queue').update({ status: 'processing' }).eq('id', task.id);
        
        // Execute the task
        await executeTask(task);
    } else {
        console.log('⏳ [Daemon] Queue is empty. Waiting 30 seconds for next cycle...');
    }

    // Loop continuously with a 30-second cadence
    setTimeout(runProductionDaemon, 30000);
}

module.exports = { runProductionDaemon };
