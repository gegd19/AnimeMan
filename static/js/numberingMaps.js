/** Explicit TV numbering maps: preview before every save. */
window.App = window.App || {};
App.NumberingMaps = (function(app) {
    'use strict';
    let reviewed = null;
    const byId = id => document.getElementById(id);
    const fields = ['numberingScope','numberingSrcPath','numberingTmdbId','numberingKind',
        'numberingSourceLabel','numberingStart','numberingEnd','numberingTargetSeason','numberingTargetEpisode'];
    function showResult(text, state) {
        const box = byId('numberingPreviewResult');
        box.textContent = text; box.dataset.state = state;
    }
    function invalidate() {
        reviewed = null;
        byId('numberingSave').disabled = true;
        showResult('输入已变化，请重新预览。', 'stale');
    }
    // 只显示当前映射方式需要的字段；payload() 本来就只读取对应字段。
    function syncKind() {
        const editor = byId('numberingMapsDetails');
        if (editor) editor.dataset.kind = byId('numberingKind').value;
    }
    const pad = n => String(n).padStart(2, '0');
    function whole(id, min, max) {
        const raw=byId(id).value.trim(), value=Number(raw);
        if (!/^\d+$/.test(raw) || !Number.isSafeInteger(value) || value<min || value>max)
            throw new Error('请填写有效的 TMDB ID、范围和目标季集。');
        return value;
    }
    function payload() {
        const kind=byId('numberingKind').value;
        const data={scope:byId('numberingScope').value.trim(),src_path:byId('numberingSrcPath').value.trim(),
            tmdb_id:whole('numberingTmdbId',1,2147483647),kind,
            season:whole('numberingTargetSeason',0,99),episode:whole('numberingTargetEpisode',1,9999)};
        if (!data.scope || !data.src_path) throw new Error('请填写作用域和示例文件路径。');
        if (kind==='exact') {
            data.source_label=byId('numberingSourceLabel').value;
            if (!data.source_label.trim()) throw new Error('请填写原始编号。');
        } else {
            data.start=whole('numberingStart',0,9999);data.end=whole('numberingEnd',0,9999);
        }
        return data;
    }
    async function post(url,data) {
        const response=await app.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        const result=await response.json();
        if (!response.ok || result.status!=='success') throw new Error(result.message || '操作失败');
        return result;
    }
    async function refresh() {
        const response=await app.fetch('/api/numbering_maps');
        const result=await response.json();
        if (!response.ok || !Array.isArray(result.rules)) throw new Error(result.message || '读取映射失败');
        const list=byId('numberingList');
        app.setRuleCount('numbering',result.rules.length);
        if (!result.rules.length) { app.ruleEmpty(list,'还没有编号映射。在上面填写并预览后保存。'); return; }
        list.replaceChildren(...result.rules.map(rule => {
            const exact=rule.kind==='exact';
            const source=exact ? `第 ${rule.source_label} 集` : `第 ${rule.start}–${rule.end} 集`;
            const target=`S${pad(rule.season)}E${pad(rule.episode)}${exact ? '' : ' 起'}`;
            return app.ruleRow({
                enabled: !!rule.enabled, toggleLabel: `编号映射 ${source} → ${target}`,
                onToggle: async enabled => {
                    try { await post('/api/numbering_maps/state',{id:rule.id,enabled});await refresh(); }
                    catch(error) { app.showToast(error.message,'error'); }
                },
                title: `${source} → ${target}`,
                facts: [`剧集 · TMDB ${rule.tmdb_id}`],
                tags: [{text: exact ? '单个编号' : '编号范围', kind: exact ? '' : 'blue'}],
                pathLabel: '作用域', path: rule.scope,
                actions: [app.button('删除映射', async () => {
                    if (!confirm(`删除编号映射「${source} → ${target}」？\n${rule.scope}\n\n只删除映射本身，不会改动已入库的文件。`)) return;
                    try { await post('/api/numbering_maps/delete',{id:rule.id});app.showToast('编号映射已删除。','success');await refresh(); }
                    catch(error) { app.showToast(error.message,'error'); }
                }, 'danger btn-sm')],
            });
        }));
    }
    for (const id of fields) byId(id).addEventListener('input',invalidate);
    byId('numberingKind').addEventListener('change', () => { syncKind(); invalidate(); });
    syncKind();
    byId('numberingPreview').addEventListener('click', async () => {
        invalidate();
        try {
            const data=payload(), snapshot=JSON.stringify(data);
            const result=await post('/api/numbering_maps/preview',data);
            if (JSON.stringify(payload())!==snapshot) return;
            const p=result.preview;
            showResult(`${p.source_label ?? data.source_label ?? ''} → S${pad(p.season)}E${pad(p.episode)}（剧集 ${p.tmdb_id ?? data.tmdb_id}，${p.scope ?? data.scope}）`, 'ok');
            reviewed=snapshot;byId('numberingSave').disabled=false;
        } catch(error) { showResult(error.message, 'error'); }
    });
    byId('numberingSave').addEventListener('click', async () => {
        try {
            const data=payload();
            if (!reviewed || JSON.stringify(data)!==reviewed) throw new Error('请先重新预览。');
            byId('numberingSave').disabled=true;reviewed=null;
            await post('/api/numbering_maps',data);
            app.showToast('编号映射已保存。','success');await refresh();
        } catch(error) { app.showToast(error.message,'error'); }
    });
    byId('numberingRefresh').addEventListener('click', () => refresh().catch(error => app.showToast(error.message,'error')));
    return {refresh};
})(window.App);
