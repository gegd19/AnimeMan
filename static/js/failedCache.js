/**
 * 失败缓存管理模块
 * 负责查看、清空失败缓存列表，并提供手动修正入口（单文件/批量）
 * 新增：查看文件夹内所有视频文件（含成功与失败），方便批量纠错
 */
window.App = window.App || {};
App.FailedCache = (function(app) {
    'use strict';

    const modalId = 'failedCacheModal';
    const listDivId = 'failedCacheList';
    const countSpanId = 'failedCount';

    let currentClusters = [];

    // ---------- 私有函数 ----------
    function _closeModal() {
        document.getElementById(modalId).style.display = 'none';
    }

    function _header(folder, files) {
        const bar = app.el('div', {className: 'list-head'},
            app.button('返回文件夹视图', () => _loadCache()),
            app.el('strong', {text: `${folder}`}));
        if (files) bar.append(app.button('批量修正全部', () => _openBatchWithAllFiles(folder), 'success'));
        return bar;
    }

    function _correctionButton(file, label = '修正', className = 'warning') {
        return app.button(label, () => App.Correction.openCorrectionModal(file.path, file.name, file.recognition_pending), className);
    }

    function _error(error) {
        document.getElementById(listDivId).textContent = `请求失败：${error.message}`;
    }

    async function _loadCache() {
        try {
            const resp = await app.fetch('/api/failed_cache/clusters');
            const data = await resp.json();
            const listDiv = document.getElementById(listDivId);
            currentClusters = data.clusters || [];
            document.getElementById(countSpanId).textContent = currentClusters.reduce((sum, c) => sum + c.count, 0);
            if (!currentClusters.length) {
                listDiv.textContent = '暂无失败缓存记录';
                return;
            }
            const table = app.el('table', {className: 'failed-table'},
                app.el('tr', {}, ...['文件夹', '失败数量', '操作'].map(text => app.el('th', {text}))));
            for (const cluster of currentClusters) {
                table.append(app.el('tr', {},
                    app.el('td', {title: cluster.folder, text: cluster.folder, className: 'mono'}),
                    app.el('td', {text: cluster.count}), app.el('td', {},
                        app.button('批量修正', () => App.BatchCorrection.openModal(cluster.folder, cluster.files), 'success'),
                        app.button('查看失败文件', () => _showFilesInFolder(cluster.folder, cluster.files)),
                        app.button('查看所有文件', () => _showAllFilesInFolder(cluster.folder)))));
            }
            listDiv.replaceChildren(app.el('div', {className: 'list-head'},
                app.button('切换为列表视图', () => _switchToListView())), table);
        } catch (error) { _error(error); }
    }

    function _showFilesInFolder(folder, files, withTime = false) {
        const table = app.el('table', {className: 'failed-table'});
        const columns = ['文件名', '失败原因', ...(withTime ? ['时间'] : []), '操作'];
        table.append(app.el('tr', {}, ...columns.map(text => app.el('th', {text}))));
        for (const file of files) {
            const row = app.el('tr', {}, app.el('td', {title: file.path, text: file.name}),
                app.el('td', {text: file.reason || '', className: 'text-danger'}));
            if (withTime) row.append(app.el('td', {text: file.failed_time ? new Date(file.failed_time * 1000).toLocaleString() : '未知'}));
            row.append(app.el('td', {}, _correctionButton(file)));
            table.append(row);
        }
        document.getElementById(listDivId).replaceChildren(_header(folder), table);
    }

    async function _switchToListView() {
        try {
            const data = await (await app.fetch('/api/failed_cache')).json();
            const files = data.failed || [];
            document.getElementById(countSpanId).textContent = files.length;
            if (!files.length) {
                document.getElementById(listDivId).textContent = '暂无失败缓存记录';
                return;
            }
            _showFilesInFolder('失败缓存', files, true);
        } catch (error) { _error(error); }
    }

    async function _showAllFilesInFolder(folder) {
        const listDiv = document.getElementById(listDivId);
        listDiv.textContent = '正在加载文件夹详情...';
        window.__currentFolderAllFiles = [];
        try {
            const data = await (await app.fetch(`/api/failed_cache/folder_details?folder=${encodeURIComponent(folder)}`)).json();
            if (!data.files) throw new Error('获取文件夹详情失败');
            const files = data.files;
            window.__currentFolderAllFiles = files.map(f => ({
                path: f.path, name: f.name, status: f.status, title: f.title || '',
                season: f.season, episode: f.episode,
                reason: f.reason || (f.status === 'success' ? `已识别: ${f.title || '未知'}` : '未处理')
            }));
            const table = app.el('table', {className: 'failed-table'},
                app.el('tr', {}, ...['状态', '文件名', '识别信息', '操作'].map(text => app.el('th', {text}))));
            for (const file of files) {
                const success = file.status === 'success';
                const badge = success ? '成功' : file.status === 'failed' ? '失败' : '未处理';
                const badgeClass = success ? 'badge is-green' : file.status === 'failed' ? 'badge is-red' : 'badge';
                let info = success ? (file.title || '') : file.status === 'failed' ? `失败原因: ${file.reason || '未知'}` : '尚未处理';
                if (success) {
                    if (file.media_type === 'tv' && file.season != null && file.episode != null) {
                        info += ` S${String(file.season).padStart(2, '0')}E${String(file.episode).padStart(2, '0')}`;
                    }
                    const score = app.recognitionScore(file);
                    info += ` (${score.label}${score.detail ? '；' + score.detail : ''})`;
                }
                table.append(app.el('tr', {}, app.el('td', {}, app.el('span', {className: badgeClass, text: badge})),
                    app.el('td', {title: file.path, text: file.name}), app.el('td', {text: info, className: 'text-small'}),
                    app.el('td', {}, _correctionButton(file, success ? '重处理' : '修正', success ? 'secondary' : 'warning'))));
            }
            const head = _header(`${folder} (共 ${files.length} 个视频文件)`);
            head.append(app.button('批量修正此文件夹所有文件', () => _openBatchWithAllFiles(folder), 'success'));
            listDiv.replaceChildren(head, table,
                app.el('div', {className: 'text-muted text-small', text: '批量修正会打开修正面板，可以调整顺序并选择正确的 TMDB 条目。'}));
        } catch (error) { _error(error); }
    }

    // 打开批量修正，并传入当前文件夹所有文件
    function _openBatchWithAllFiles(folder) {
        const files = window.__currentFolderAllFiles;
        if (!files || files.length === 0) {
            app.showToast('没有可用的文件', 'warning');
            return;
        }
        if (typeof App.BatchCorrection !== 'undefined') {
            App.BatchCorrection.openModalWithFiles(`${folder}`, files);
        } else {
            app.showToast('批量修正模块未加载', 'error');
        }
    }

    // ---------- 公开接口 ----------
    return {
        viewFailedCache: function() {
            document.getElementById(modalId).style.display = 'block';
            _loadCache();
        },

        closeFailedCacheModal: _closeModal,

        loadFailedCache: _loadCache,

        switchToListView: _switchToListView,

        showFilesInFolder: _showFilesInFolder,

        // 新增公开方法
        showAllFilesInFolder: _showAllFilesInFolder,
        openBatchWithAllFiles: _openBatchWithAllFiles,

        clearFailedCache: async function() {
            if (!confirm('确定要清空所有失败缓存记录吗？此操作不可撤销。')) return;
            const resp = await app.fetch('/api/failed_cache/clear', { method: 'POST' });
            const data = await resp.json();
            if (data.status === 'success') {
                app.showToast(`已清空 ${data.removed} 条失败记录`, 'success');
                await _loadCache();
            } else {
                app.showToast('清空失败', 'error');
            }
        }
    };
})(window.App);
