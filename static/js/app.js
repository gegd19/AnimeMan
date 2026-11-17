
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
            else if (key === 'attrs') {
                // ARIA 等没有对应属性的特性；值始终作为文本写入。
                if (typeof node.setAttribute === 'function') {
                    for (const [name, attr] of Object.entries(value)) node.setAttribute(name, String(attr));
                }
            }
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

    exports.recognitionScore = function(item) {
        const manual = item.confirmed_by_user || item.score_origin === 'manual_mapping';
        const score = item.confidence;
        const label = manual ? '人工确认（人工指定）' : score == null ? '未评分' :
            item.score_origin === 'automatic' ? `匹配评分：${score}` : `旧评分：${score}`;
        const evidence = Array.isArray(item.score_evidence) ? item.score_evidence.filter(v => typeof v === 'string') : [];
        const conflicts = Array.isArray(item.score_conflicts) ? item.score_conflicts.filter(v => typeof v === 'string') : [];
        const detail = [evidence.length ? `证据：${evidence.join('、')}` : '',
                        conflicts.length ? `提示：${conflicts.join('、')}` : ''].filter(Boolean).join('；');
        return {label, detail};
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
            colSpan: columns, text, className: 'cell-empty'
        })));
    };

    exports.pagination = function(container, current, total, goTo) {
        container.replaceChildren();
        if (total <= 1) return;
        const bar = exports.el('div', {className: 'pager'});
        const move = (label, page, disabled) => exports.button(label, () => goTo(page), 'secondary btn-sm', {disabled});
        bar.append(move('首页', 1, current === 1), move('上一页', current - 1, current === 1),
            exports.el('span', {text: `第 ${current} / ${total} 页`}),
            move('下一页', current + 1, current === total), move('末页', total, current === total));
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
                exports.el('td', {}, item.poster_url ? exports.poster(item.poster_url, {alt: ''}) : exports.el('span', {className: 'text-muted', text: '无图'})),
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
        // 「清空日志」只清空本页显示：此前的条目不再重新出现，完整日志仍可在新窗口查看。
        if (clearedUntil && logs.length) logs = logs.filter(item => !(item.time <= clearedUntil));

        // 更新暂停按钮状态显示
        const pauseBtn = document.getElementById('pauseLogsBtn');
        if (pauseBtn) {
            pauseBtn.textContent = exports.logsPaused ? '恢复日志' : '暂停日志';
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

    const EMPTY_LOG = '<div class="log-empty">准备就绪。开始处理后，日志会显示在这里。</div>';
    const LOG_LEVELS = ['error', 'success', 'warning', 'progress'];
    let renderedLogKey = null;
    let clearedUntil = 0;

    // 内部函数：实际将日志渲染到 DOM
    function _renderLogsToDOM(logs) {
        const logBox = document.getElementById('logBox');
        if (!logBox) return;

        if (!logs || logs.length === 0) {
            renderedLogKey = null;
            logBox.innerHTML = EMPTY_LOG;
            return;
        }

        // 状态每秒轮询一次；日志没有变化时不重建节点，避免打断阅读和文字选择。
        const last = logs[logs.length - 1];
        const key = `${logs.length}|${logs[0].time}|${last.time}|${last.msg}`;
        if (key === renderedLogKey && logBox.childElementCount === logs.length) return;
        renderedLogKey = key;

        // 只有原本就停在底部时才继续跟随最新日志。
        const follow = logBox.scrollHeight - logBox.scrollTop - logBox.clientHeight < 48;
        const fragment = document.createDocumentFragment();
        logs.forEach(item => {
            const level = LOG_LEVELS.includes(item.level) ? item.level : 'info';
            const time = item.time ? new Date(item.time * 1000).toLocaleTimeString() : '';
            fragment.appendChild(exports.el('div', {className: `log-line log-${level}`},
                exports.el('span', {className: 'log-time', text: time}),
                exports.el('span', {className: 'log-msg', text: item.msg})));
        });
        logBox.replaceChildren(fragment);
        if (follow) logBox.scrollTop = logBox.scrollHeight;
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
            pauseBtn.textContent = exports.logsPaused ? '恢复日志' : '暂停日志';
        }
    };

    /**
     * 清空日志显示
     */
    exports.clearLogs = function() {
        const logBox = document.getElementById('logBox');
        const shown = exports.pendingLogs.length ? exports.pendingLogs : exports.cachedLogsForDisplay;
        if (shown.length) clearedUntil = Math.max(clearedUntil, ...shown.map(item => Number(item.time) || 0));
        if (logBox) {
            renderedLogKey = null;
            logBox.innerHTML = EMPTY_LOG;
        }
        exports.pendingLogs = [];
        exports.cachedLogsForDisplay = [];
    };

    // 外观在 style.css 的 .app-toast 中定义；消息始终作为文本写入。
    // 未指定时长时，错误和警告多停留一会儿，便于读完。
    exports.showToast = function(message, type = 'info', duration) {
        const existingToast = document.querySelector('.app-toast');
        if (existingToast) existingToast.remove();
        if (!['success', 'error', 'info', 'warning'].includes(type)) type = 'info';
        if (duration === undefined) duration = (type === 'error' || type === 'warning') ? 6000 : 3000;

        const toast = document.createElement('div');
        toast.className = `app-toast app-toast-${type}`;
        toast.setAttribute('role', type === 'error' || type === 'warning' ? 'alert' : 'status');
        toast.textContent = message;
        const dismiss = () => {
            toast.classList.add('is-leaving');
            setTimeout(() => toast.remove(), 250);
        };
        toast.addEventListener('click', dismiss);
        document.body.appendChild(toast);

        if (duration > 0) setTimeout(dismiss, duration);
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
