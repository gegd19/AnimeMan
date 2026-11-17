/** Offline anime databases: show what is downloaded and start a download / update. */
window.App = window.App || {};
App.AnimeDb = (function(app) {
    'use strict';
    const byId = id => document.getElementById(id);
    let timer = null;
    function describe(state) {
        if (state.updating) return state.message || '正在更新番剧数据库…';
        if (state.error) return `更新失败：${state.error}`;
        if (!state.available) return '尚未下载。点「下载 / 更新数据」后才会使用。';
        const meta = state.meta || {}, counts = meta.counts || {};
        const when = meta.updated_at ? new Date(meta.updated_at * 1000).toLocaleDateString() : '未知日期';
        const failed = Object.entries(meta.sources || {}).filter(([, s]) => !s.ok).map(([name]) => name);
        return `已就绪：${counts.works || 0} 部作品，更新于 ${when}` + (failed.length ? `（${failed.join('、')} 本次下载失败，沿用旧数据）` : '');
    }
    function render(state) {
        const text = byId('animeDbStatusText'), button = byId('animeDbUpdateBtn');
        if (!text || !button) return;
        text.textContent = describe(state);
        text.dataset.state = state.updating ? 'running' : (state.error ? 'error' : (state.available ? 'ready' : 'empty'));
        button.disabled = !!state.updating;
        clearTimeout(timer);
        if (state.updating) timer = setTimeout(refresh, 2000);
    }
    async function refresh() {
        try {
            const response = await app.fetch('/api/anime_db/status');
            render(await response.json());
        } catch (error) {
            const text = byId('animeDbStatusText');
            if (text) text.textContent = '无法读取番剧数据库状态';
        }
    }
    async function update() {
        try {
            const response = await app.fetch('/api/anime_db/update', {method: 'POST'});
            const state = await response.json();
            if (!response.ok) throw new Error(state.message || '无法开始更新');
            render({...state, updating: true});
        } catch (error) {
            app.showToast(error.message || '无法开始更新', 'error');
        }
    }
    return {refresh, update};
})(window.App);
