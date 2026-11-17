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
            app.button('返回文件夹视图', () => _loadCache(), 'ghost btn-sm'),
            app.el('strong', {text: `${folder}`}));
        if (files) bar.append(app.button('批量修正全部', () => _openBatchWithAllFiles(folder), 'success'));
        return bar;
    }

    // 路径的最后一段作为文件夹名，整条路径作为副标题；只用于显示。
    function _folderName(folder) {
        const parts = String(folder || '').split(/[\\/]/).filter(Boolean);
        return parts.length ? parts[parts.length - 1] : String(folder || '');
    }

    // 汇总一个文件夹里的失败原因：原因 → 次数，按次数降序。
    function _reasonSummary(files) {
        const counts = new Map();
        for (const file of files || []) {
            const reason = file.reason || '未记录原因';
            counts.set(reason, (counts.get(reason) || 0) + 1);
        }
        return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
    }

    function _emptyState() {
        return app.el('div', {className: 'empty-state'},
            app.el('b', {text: '没有失败记录'}),
            app.el('span', {text: '扫描到的文件都已识别。之后识别失败的文件会出现在这里。'}));
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
                listDiv.replaceChildren(_emptyState());
                return;
            }
            // 每个文件夹一张卡片：文件夹名、完整路径、失败数、原因汇总、操作。
            const cards = app.el('div', {className: 'failed-folders'});
            for (const cluster of currentClusters) {
                const reasons = _reasonSummary(cluster.files);
                const reasonList = app.el('ul', {className: 'reason-list'},
                    ...reasons.slice(0, 3).map(([reason, count]) => app.el('li', {},
                        app.el('span', {className: 'reason-text', text: reason}),
                        app.el('span', {className: 'reason-count', text: `× ${count}`}))));
                if (reasons.length > 3) reasonList.append(app.el('li', {className: 'reason-more', text: `另有 ${reasons.length - 3} 种原因`}));
                cards.append(app.el('article', {className: 'failed-folder'},
                    app.el('div', {className: 'failed-folder-head'},
                        app.el('span', {className: 'folder-icon', attrs: {'aria-hidden': 'true'}}),
                        app.el('div', {className: 'failed-folder-name'},
                            app.el('h4', {title: cluster.folder, text: _folderName(cluster.folder)}),
                            app.el('span', {className: 'mono', title: cluster.folder, text: cluster.folder})),
                        app.el('span', {className: 'badge is-red', text: `${cluster.count} 个文件`})),
                    ...(reasons.length ? [reasonList] : []),
                    app.el('div', {className: 'failed-folder-actions'},
                        app.button('批量修正', () => App.BatchCorrection.openModal(cluster.folder, cluster.files), 'success'),
                        app.button('查看失败文件', () => _showFilesInFolder(cluster.folder, cluster.files)),
                        app.button('查看所有文件', () => _showAllFilesInFolder(cluster.folder), 'ghost'))));
            }
            const total = currentClusters.reduce((sum, c) => sum + c.count, 0);
            listDiv.replaceChildren(app.el('div', {className: 'list-head'},
                app.el('span', {className: 'count', text: `${currentClusters.length} 个文件夹，共 ${total} 个文件待处理`}),
                app.el('span', {className: 'spacer'}),
                app.button('按文件列出', () => _switchToListView(), 'ghost btn-sm')), cards);
        } catch (error) { _error(error); }
    }

    // 失败文件：一行一个，文件名、原因、（可选）时间，右侧是修正按钮。
    function _showFilesInFolder(folder, files, withTime = false) {
        const list = app.el('ul', {className: 'failed-files'});
        for (const file of files) {
            const meta = app.el('div', {className: 'failed-file-meta'},
                app.el('span', {className: 'text-danger', text: file.reason || '未记录原因'}));
            if (withTime) meta.append(app.el('span', {className: 'text-muted',
                text: file.failed_time ? new Date(file.failed_time * 1000).toLocaleString() : '时间未知'}));
            list.append(app.el('li', {},
                app.el('div', {className: 'failed-file-body'},
                    app.el('div', {className: 'failed-file-name', title: file.path, text: file.name}),
                    meta),
                _correctionButton(file)));
        }
        document.getElementById(listDivId).replaceChildren(_header(folder), list);
    }

    async function _switchToListView() {
        try {
            const data = await (await app.fetch('/api/failed_cache')).json();
            const files = data.failed || [];
            document.getElementById(countSpanId).textContent = files.length;
            if (!files.length) {
                document.getElementById(listDivId).replaceChildren(_emptyState());
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
