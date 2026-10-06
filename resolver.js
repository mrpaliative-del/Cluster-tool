function resolvePayload(rawPayload) {
    if (!rawPayload) throw new Error("Validation Error: Null payload");
    let parsedData = typeof rawPayload === 'object' ? rawPayload : JSON.parse(rawPayload);
    const clean = {};
    for (const k in parsedData) {
        let v = parsedData[k];
        clean[k] = (v === null || v === 'null') ? null : (!isNaN(v) && typeof v === 'string' && v.trim() !== '') ? Number(v) : v;
    }
    return clean;
}
module.exports = { resolvePayload };
