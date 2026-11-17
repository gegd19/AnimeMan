/** User-confirmed, scoped recognition aliases; a fresh preview is mandatory. */
window.App = window.App || {};
App.RecognitionAliases = (function(app) {
    'use strict';
    const byId = id => document.getElementById(id);
    const fields=['recognitionAliasScope','recognitionAliasName','recognitionAliasType','recognitionAliasId'];
    let reviewed=null;
    function invalidate() {
        reviewed=null;byId('recognitionAliasSave').disabled=true;
        byId('recognitionAliasPreviewResult').textContent='输入已变化，请重新预览。';
    }
    function payload() {
        const raw=byId('recognitionAliasId').value.trim(), ident=Number(raw);
        const result={scope:byId('recognitionAliasScope').value.trim(),name:byId('recognitionAliasName').value,
            media_type:byId('recognitionAliasType').value,tmdb_id:ident};
        if (!result.scope || !result.name.trim() || !/^\d+$/.test(raw) || !Number.isSafeInteger(ident) || ident<1 || ident>2147483647)
            throw new Error('请填写源目录、别名、作品类型和有效 TMDB ID。');
        return result;
    }
    async function post(url,data) {
        const response=await app.fetch(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
        const result=await response.json();
        if (!response.ok || result.status!=='success') throw new Error(result.message || '操作失败');
        return result;
    }
    async function refresh() {
        const response=await app.fetch('/api/recognition_aliases');
        const result=await response.json();
        if (!response.ok || !Array.isArray(result.aliases)) throw new Error(result.message || '读取别名失败');
        const list=byId('recognitionAliasList');list.replaceChildren();
        if (!result.aliases.length) list.textContent='暂无人工别名';
        for (const record of result.aliases) {
            const row=app.el('div',{className:'note'});
            row.append(app.el('span',{text:`${record.name} → ${record.media_type} ${record.tmdb_id} · ${record.scope || '历史未限定范围'}`}));
            if (record.scope) row.append(app.button('删除人工别名',async () => {
                try { await post('/api/recognition_aliases/delete',{record});await refresh(); }
                catch(error) { app.showToast(error.message,'error'); }
            },'danger'));
            list.append(row);
        }
    }
    for (const id of fields) byId(id).addEventListener('input',invalidate);
    byId('recognitionAliasPreview').addEventListener('click',async () => {
        invalidate();
        try {
            const data=payload(), snapshot=JSON.stringify(data);
            const result=await post('/api/recognition_aliases/preview',data);
            if (JSON.stringify(payload())!==snapshot) return;
            const p=result.preview;
            const conflict=p.conflicting_ids.length ? `；同名还关联 ${p.conflicting_ids.join('、')}，可能需要人工确认` : '';
            byId('recognitionAliasPreviewResult').textContent=`${p.name} → ${p.title}（${p.media_type} ${p.tmdb_id}${p.year ? '，'+p.year : ''}）；范围：${p.scope}（含子目录）${conflict}`;
            reviewed={snapshot,token:result.preview_token};byId('recognitionAliasSave').disabled=false;
        } catch(error) { byId('recognitionAliasPreviewResult').textContent=error.message; }
    });
    byId('recognitionAliasSave').addEventListener('click',async () => {
        try {
            const data=payload();
            if (!reviewed || JSON.stringify(data)!==reviewed.snapshot) throw new Error('请先重新预览。');
            data.preview_token=reviewed.token;reviewed=null;byId('recognitionAliasSave').disabled=true;
            const result=await post('/api/recognition_aliases',data);
            app.showToast(result.active ? '人工别名已保存。' : '别名已保存；请在设置中启用后使用。',result.active ? 'success' : 'warning',6000);
            await refresh();
        } catch(error) { app.showToast(error.message,'error'); }
    });
    byId('recognitionAliasRefresh').addEventListener('click',() => refresh().catch(error => app.showToast(error.message,'error')));
    return {refresh};
})(window.App);
