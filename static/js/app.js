
/**
 * 全局应用命名空间、辅助函数和模块导出
 * 所有功能模块都挂载到 window.App 对象下
 * 新增：日志暂停查看功能
 */
window.App = window.App || {};

(function(exports) {
    'use strict';

    // ========== 全局变量 ==========
    exports.currentBrowsePath = '';
    exports.targetField = '';
    exports.statusInterval = null;
    exports.configCache = {};
    exports.fullStreamResult = '';
    exports.aiParseResults = [];

    exports.scannedSubtitles = [];
    exports.matchResults = [];
    exports.mediaLibraryCache = [];
    exports.filteredMediaLibrary = [];
    exports.currentSubtitleIndex = -1;

    exports.mappingRules = [];
    exports.currentCorrectionPath = '';
    exports.selectedTmdbId = null;
    exports.selectedMediaType = 'tv';

    // 日志暂停相关
    exports.logsPaused = false;
    exports.pendingLogs = [];          // 暂停期间缓存的日志
    exports.cachedLogsForDisplay = []; // 当前显示的日志快照

    // ========== 辅助函数 ==========
    exports.escapeHtml = function(text) {
        if (!text) return text;
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    };

    // Dynamic values enter the DOM as text/properties, never as HTML or code.
    exports.el = function(tag, properties = {}, ...children) {
        const node = document.createElement(tag);
        for (const [key, value] of Object.entries(properties)) {
            if (key === 'text') node.textContent = value ?? '';
            else if (key === 'style') node.style.cssText = value;
            else if (key === 'dataset') Object.assign(node.dataset, value);
            else node[key] = value;
        }
        node.append(...children);
        return node;
    };

    exports.button = function(text, action, className = 'secondary', properties = {}) {
        const button = exports.el('button', {type: 'button', text, className, ...properties});
        button.addEventListener('click', event => {
            try {
                Promise.resolve(action(event)).catch(error => exports.showToast(error.message, 'error'));
            } catch (error) {
                exports.showToast(error.message, 'error');
            }
        });
        return button;
    };

    exports.mediaPosterUrl = function(mediaType, tmdbId) {
        if (!['movie', 'tv'].includes(mediaType) || !/^[1-9][0-9]*$/.test(String(tmdbId))) return '';
        return `/media_poster/${mediaType}/${encodeURIComponent(tmdbId)}`;
    };

    exports.poster = function(src, properties = {}) {
        const image = exports.el('img', properties);
        image.addEventListener('error', () => { image.style.display = 'none'; });
        if (src) image.src = src;
        else image.style.display = 'none';
        return image;
    };

    exports.tableMessage = function(body, text, columns = 5) {
        body.replaceChildren(exports.el('tr', {}, exports.el('td', {
            colSpan: columns, text, style: 'text-align:center;padding:12px;'
        })));
    };

    exports.pagination = function(container, current, total, goTo) {
        container.replaceChildren();
        if (total <= 1) return;
        const bar = exports.el('div', {style: 'display:flex;align-items:center;justify-content:center;gap:8px;margin-top:12px;flex-wrap:wrap;'});
        const move = (label, page, disabled) => exports.button(label, () => goTo(page), 'secondary', {disabled});
        bar.append(move('⏮️', 1, current === 1), move('◀', current - 1, current === 1),
            exports.el('span', {text: `第 ${current} / ${total} 页`}),
            move('▶', current + 1, current === total), move('⏭️', total, current === total));
        container.append(bar);
    };

    // Return the original Response so JSON and streaming consumers share checks.
    exports.fetch = async function(url, options) {
        let response;
        try {
            response = await fetch(url, options);
        } catch (error) {
            if (error.name === 'AbortError') throw error;
            const failure = new Error(`网络请求失败：${error.message}`);
            exports.showToast(failure.message, 'error');
            throw failure;
        }
        if (response.ok) return response;
        const status = response.status;
        const label = status === 401 ? '认证失效，请重新登录' :
            status === 403 ? '无权访问此资源' : status === 409 ? '操作冲突，请等待当前任务结束或刷新后重试' :
            status >= 500 ? '服务器错误，请查看服务端日志' : '请求失败';
        let detail = '';
        try {
            const data = await response.json();
            const message = data?.message || data?.error;
            if (typeof message === 'string') detail = `：${message}`;
        } catch (_) { /* Non-JSON error pages are not displayed as server HTML. */ }
        const error = new Error(`${label}（HTTP ${status}）${detail}`);
        error.status = status;
        exports.showToast(error.message, 'error');
        throw error;
    };

    exports.renderTmdbResults = function(container, items, mediaType, select) {
        const table = container.tagName === 'TBODY' ? container : exports.el('table', {className: 'failed-table'});
        table.replaceChildren();
        if (table !== container) {
            table.append(exports.el('tr', {}, ...['海报', '标题', '年份', '季详情', '操作'].map(text => exports.el('th', {text}))));
            container.replaceChildren(table);
        }
        for (const item of items) {
            const details = item.media_type === 'tv' ? (item.seasons_detail || []) : [];
            const seasons = exports.el('span', {
                text: details.length ? details.map(s => `S${s.season_number}(${s.episode_count}集)`).join(', ') : '-',
                title: details.map(s => `S${s.season_number}: ${s.name} (${s.episode_count}集)`).join('\n')
            });
            table.append(exports.el('tr', {},
                exports.el('td', {}, item.poster_url ? exports.poster(item.poster_url, {style: 'width:45px;height:68px;object-fit:cover;border-radius:6px;'}) : exports.el('span', {text: '无图'})),
                exports.el('td', {text: item.title}), exports.el('td', {text: item.year || ''}),
                exports.el('td', {}, seasons), exports.el('td', {}, exports.button('选择', () => select(item.id, item.title, mediaType)))));
        }
    };

    /**
     * 渲染日志到 logBox
     * 如果暂停，则只缓存日志而不更新 DOM
     */
    exports.renderLogs = function(logs) {
        const logBox = document.getElementById('logBox');
        if (!logBox) return;

        // 更新暂停按钮状态显示
        const pauseBtn = document.getElementById('pauseLogsBtn');
        if (pauseBtn) {
            pauseBtn.textContent = exports.logsPaused ? '▶ 恢复日志' : '⏸️ 暂停日志';
        }

        // 如果处于暂停状态，只保存日志到 pendingLogs，不更新界面
        if (exports.logsPaused) {
            exports.pendingLogs = logs.slice(); // 保存最新日志
            return;
        }

        // 正常渲染日志
        _renderLogsToDOM(logs);
        exports.cachedLogsForDisplay = logs.slice();
        exports.pendingLogs = [];
    };

    // 内部函数：实际将日志渲染到 DOM
    function _renderLogsToDOM(logs) {
        const logBox = document.getElementById('logBox');
        if (!logBox) return;

        logBox.innerHTML = '';
        if (!logs || logs.length === 0) {
            logBox.innerHTML = '<div style="color:#8a95a5;">✨ 准备就绪</div>';
            return;
        }

        logs.forEach(item => {
            const div = document.createElement('div');
            let color = '#e3e8f0';
            if (item.level === 'error') color = '#ff6b6b';
            else if (item.level === 'success') color = '#51cf66';
            else if (item.level === 'warning') color = '#ffd43b';
            else if (item.level === 'progress') color = '#74c0fc';
            div.style.color = color;
            const time = item.time ? new Date(item.time * 1000).toLocaleTimeString() : '';
            div.textContent = time ? `[${time}] ${item.msg}` : item.msg;
            logBox.appendChild(div);
        });
        logBox.scrollTop = logBox.scrollHeight;
    }

    /**
     * 切换日志暂停状态
     */
    exports.toggleLogsPause = function() {
        exports.logsPaused = !exports.logsPaused;
        const pauseBtn = document.getElementById('pauseLogsBtn');

        if (!exports.logsPaused) {
            // 恢复：如果有待渲染的日志，立即渲染
            if (exports.pendingLogs.length > 0) {
                _renderLogsToDOM(exports.pendingLogs);
                exports.cachedLogsForDisplay = exports.pendingLogs.slice();
                exports.pendingLogs = [];
            } else if (exports.cachedLogsForDisplay.length > 0) {
                // 没有新日志但之前有缓存，重新渲染缓存（保持显示）
                _renderLogsToDOM(exports.cachedLogsForDisplay);
            }
            exports.showToast('日志已恢复滚动', 'info', 1500);
        } else {
            exports.showToast('日志已暂停，可安心查看', 'info', 2000);
        }

        if (pauseBtn) {
            pauseBtn.textContent = exports.logsPaused ? '▶ 恢复日志' : '⏸️ 暂停日志';
        }
    };

    /**
     * 清空日志显示
     */
    exports.clearLogs = function() {
        const logBox = document.getElementById('logBox');
        if (logBox) {
            logBox.innerHTML = '<div style="color:#8a95a5;">✨ 准备就绪</div>';
        }
        exports.pendingLogs = [];
        exports.cachedLogsForDisplay = [];
    };

    exports.showToast = function(message, type = 'info', duration = 3000) {
        const existingToast = document.querySelector('.app-toast');
        if (existingToast) existingToast.remove();

        const toast = document.createElement('div');
        toast.className = `app-toast app-toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            max-width: 350px;
            padding: 12px 20px;
            border-radius: 10px;
            font-size: 14px;
            font-weight: 500;
            color: white;
            z-index: 10000;
            box-shadow: 0 8px 20px rgba(0,0,0,0.15);
            animation: slideIn 0.3s ease;
            word-break: break-word;
        `;

        const colors = {
            success: '#28a745',
            error: '#dc3545',
            info: '#2c7be5',
            warning: '#fd7e14'
        };
        toast.style.backgroundColor = colors[type] || colors.info;

        const style = document.createElement('style');
        style.textContent = `
            @keyframes slideIn {
                from { opacity: 0; transform: translateX(20px); }
                to { opacity: 1; transform: translateX(0); }
            }
        `;
        if (!document.querySelector('#toast-animation')) {
            style.id = 'toast-animation';
            document.head.appendChild(style);
        }

        document.body.appendChild(toast);

        if (duration > 0) {
            setTimeout(() => {
                toast.style.opacity = '0';
                toast.style.transition = 'opacity 0.3s';
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }
    };

    // ========== 全局函数绑定 ==========
    function bindGlobalFunctions() {
        if (typeof App.Config !== 'undefined') {
            window.saveConfig = App.Config.saveConfig;
            window.setDefaultSubtitleFolder = App.Config.setDefaultSubtitleFolder;
        }
        if (typeof App.Task !== 'undefined') {
            window.startTask = App.Task.startTask;
            window.stopTask = App.Task.stopTask;
            window.refreshStatus = App.Task.refreshStatus;
            window.viewFullLog = App.Task.viewFullLog;
        }
        if (typeof App.FailedCache !== 'undefined') {
            window.viewFailedCache = App.FailedCache.viewFailedCache;
            window.closeFailedCacheModal = App.FailedCache.closeFailedCacheModal;
            window.clearFailedCache = App.FailedCache.clearFailedCache;
            window.switchToListView = App.FailedCache.switchToListView;
            window.showFilesInFolder = App.FailedCache.showFilesInFolder;
        }
        if (typeof App.Correction !== 'undefined') {
            window.openCorrectionModal = App.Correction.openCorrectionModal;
            window.closeCorrectionModal = App.Correction.closeCorrectionModal;
            window.searchTmdbForCorrection = App.Correction.searchTmdbForCorrection;
            window.selectTmdbForCorrection = App.Correction.selectTmdbForCorrection;
            window.executeCorrection = App.Correction.executeCorrection;
        }
        if (typeof App.BatchCorrection !== 'undefined') {
            window.openBatchCorrectionModal = App.BatchCorrection.openModal;
            window.closeBatchCorrectionModal = App.BatchCorrection.closeModal;
            window.toggleSelectAll = App.BatchCorrection.toggleSelectAll;
            window.toggleFile = App.BatchCorrection.toggleFile;
            window.moveUp = App.BatchCorrection.moveUp;
            window.moveDown = App.BatchCorrection.moveDown;
            window.smartSort = App.BatchCorrection.smartSort;
            window.resetOrder = App.BatchCorrection.resetOrder;
            window.autoExtractStartEpisode = App.BatchCorrection.autoExtractStartEpisode;
            window.searchTmdbBatch = App.BatchCorrection.searchTmdb;
            window.selectTmdbBatch = App.BatchCorrection.selectTmdb;
            window.executeBatchCorrection = App.BatchCorrection.execute;
        }
        if (typeof App.OfflinePreparser !== 'undefined') {
            window.scanOfflineFolders = App.OfflinePreparser.scanFolders;
            window.runFullPreparse = App.OfflinePreparser.runFullPreparse;
            window.refreshOfflineStatus = App.OfflinePreparser.refreshStatus;
        }
        if (typeof App.Browse !== 'undefined') {
            window.openBrowser = App.Browse.openBrowser;
            window.closeModal = App.Browse.closeModal;
            window.loadDrives = App.Browse.loadDrives;
            window.browsePath = App.Browse.browsePath;
            window.goUp = App.Browse.goUp;
            window.selectCurrentPath = App.Browse.selectCurrentPath;
        }
        if (typeof App.AIStream !== 'undefined') {
            window.startStreamEnhance = App.AIStream.startStreamEnhance;
            window.copyStreamResult = App.AIStream.copyStreamResult;
        }
        if (typeof App.SubtitleCenter !== 'undefined') {
            window.scanSubtitleFolder = App.SubtitleCenter.scanSubtitleFolder;
            window.matchSubtitles = App.SubtitleCenter.matchSubtitles;
            window.executeAllMatches = App.SubtitleCenter.executeAllMatches;
        }
        if (typeof App.MediaLibrary !== 'undefined') {
            window.closeManualSelectModal = App.MediaLibrary.closeManualSelectModal;
            window.filterMediaLibrary = App.MediaLibrary.filterMediaLibrary;
        }
        if (typeof App.MappingRules !== 'undefined') {
            window.openMappingModal = App.MappingRules.openMappingModal;
            window.editMappingRule = App.MappingRules.editMappingRule;
            window.closeMappingModal = App.MappingRules.closeMappingModal;
            window.saveMappingRule = App.MappingRules.saveMappingRule;
            window.deleteMappingRule = App.MappingRules.deleteMappingRule;
        }
        if (typeof App.MediaManager !== 'undefined') {
            window.refreshMediaLibrary = App.MediaManager.refreshLibrary;
            window.filterMediaManagerLibrary = App.MediaManager.filterLibrary;
            window.toggleMediaShowExpand = App.MediaManager.toggleShowExpand;
            window.toggleMediaSeasonExpand = App.MediaManager.toggleSeasonExpand;
            window.toggleMediaSelect = App.MediaManager.toggleSelect;
            window.correctMediaSingle = App.MediaManager.correctSingle;
            window.deleteMediaSingle = App.MediaManager.deleteSingle;
            window.batchCorrectMediaSelected = App.MediaManager.batchCorrectSelected;
            window.batchDeleteMediaSelected = App.MediaManager.batchDeleteSelected;
        }
        if (typeof App.History !== 'undefined') {
            window.loadProcessedHistory = App.History.loadProcessedHistory;
            window.retryProcessed = App.History.retryProcessed;
            window.openManualCorrectionForHistory = App.History.openManualCorrectionForHistory;
            window.toggleSelectAllHistory = App.History.toggleSelectAll;
            window.toggleSelectHistory = App.History.toggleSelect;
            window.openBatchCorrectionForHistory = App.History.openBatchCorrectionForHistory;
        }
        if (typeof App.ProcessedCache !== 'undefined') {
            window.viewProcessedCache = App.ProcessedCache.viewProcessedCache;
            window.closeProcessedCacheModal = App.ProcessedCache.closeModal;
        }

        // 日志控制按钮
        window.toggleLogsPause = exports.toggleLogsPause;
        window.clearLogs = exports.clearLogs;
    }

    // ========== 初始化 ==========
    exports.init = function() {
        bindGlobalFunctions();

        if (typeof App.Config !== 'undefined') App.Config.loadConfig();
        if (typeof App.Task !== 'undefined') {
            App.Task.updateStatus();
            App.Task.startStatusPolling();
        }

        if (typeof App.OfflinePreparser !== 'undefined') {
            App.OfflinePreparser.refreshStatus();
        }

        if (typeof App.MediaManager !== 'undefined') {
            App.MediaManager.init();
        }

        // 滑块联动
        const thresholdInput = document.getElementById('matchThresholdInput');
        const thresholdSpan = document.getElementById('thresholdValue');
        if (thresholdInput) {
            thresholdInput.addEventListener('input', e => thresholdSpan.innerText = e.target.value);
        }

        // 映射规则电视字段显示切换
        const mappingMediaType = document.getElementById('mappingMediaType');
        const mappingTvFields = document.getElementById('mappingTvFields');
        if (mappingMediaType) {
            mappingMediaType.addEventListener('change', function() {
                mappingTvFields.style.display = this.value === 'tv' ? 'block' : 'none';
            });
        }

        // 模态框点击外部关闭
        window.onclick = function(e) {
            const modals = ['browseModal', 'failedCacheModal', 'manualSelectModal', 'correctionModal', 'mappingModal', 'batchCorrectionModal', 'processedCacheModal'];
            modals.forEach(id => {
                const modal = document.getElementById(id);
                if (e.target === modal) {
                    if (id === 'browseModal' && typeof App.Browse !== 'undefined') App.Browse.closeModal();
                    else if (id === 'failedCacheModal' && typeof App.FailedCache !== 'undefined') App.FailedCache.closeFailedCacheModal();
                    else if (id === 'manualSelectModal' && typeof App.MediaLibrary !== 'undefined') App.MediaLibrary.closeManualSelectModal();
                    else if (id === 'correctionModal' && typeof App.Correction !== 'undefined') App.Correction.closeCorrectionModal();
                    else if (id === 'mappingModal' && typeof App.MappingRules !== 'undefined') App.MappingRules.closeMappingModal();
                    else if (id === 'batchCorrectionModal' && typeof App.BatchCorrection !== 'undefined') App.BatchCorrection.closeModal();
                    else if (id === 'processedCacheModal' && typeof App.ProcessedCache !== 'undefined') App.ProcessedCache.closeModal();
                }
            });
        };
    };

})(window.App);
