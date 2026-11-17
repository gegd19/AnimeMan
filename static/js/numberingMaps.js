/** Explicit TV numbering maps: preview before every save. */
window.App = window.App || {};
App.NumberingMaps = (function(app) {
    'use strict';
    let reviewed = null;
    const byId = id => document.getElementById(id);
    const fields = ['numberingScope','numberingSrcPath','numberingTmdbId','numberingKind',
        'numberingSourceLabel','numberingStart','numberingEnd','numberingTargetSeason','numberingTargetEpisode'];
    function invalidate() {
        reviewed = null;
        byId('numberingSave').disabled = true;
        byId('numberingPreviewResult').textContent = '输入已变化，请重新预览。';
    }
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
        const list=byId('numberingList');list.replaceChildren();
        if (!result.rules.length) list.textContent='暂无映射';
        for (const rule of result.rules) {
            const text=rule.kind==='exact' ? rule.source_label : `${rule.start}–${rule.end}`;
            const row=app.el('div',{className:'note'});
            row.append(app.el('span',{text:`${rule.enabled?'启用':'停用'} · ${rule.scope} · TV ${rule.tmdb_id} · ${text} → S${String(rule.season).padStart(2,'0')}E${String(rule.episode).padStart(2,'0')}`}));
            row.append(app.button(rule.enabled?'停用':'启用', async () => {
                try { await post('/api/numbering_maps/state',{id:rule.id,enabled:!rule.enabled});await refresh(); }
                catch(error) { app.showToast(error.message,'error'); }
            }));
            list.append(row);
        }
    }
    for (const id of fields) byId(id).addEventListener('input',invalidate);
    byId('numberingPreview').addEventListener('click', async () => {
        invalidate();
        try {
            const data=payload(), snapshot=JSON.stringify(data);
            const result=await post('/api/numbering_maps/preview',data);
            if (JSON.stringify(payload())!==snapshot) return;
            const p=result.preview;
            byId('numberingPreviewResult').textContent=`${p.source_label} → S${String(p.season).padStart(2,'0')}E${String(p.episode).padStart(2,'0')}（TV ${p.tmdb_id}，${p.scope}）`;
            reviewed=snapshot;byId('numberingSave').disabled=false;
        } catch(error) { byId('numberingPreviewResult').textContent=error.message; }
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
