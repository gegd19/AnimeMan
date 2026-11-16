/**
 * 批量手动修正模块
 * 支持文件勾选、排序、智能集号提取和预览
 * 新增：绝对集数跨季自动换算（需配合后端）
 */
window.App = window.App || {};
App.BatchCorrection = (function(app) {
    'use strict';

    const modalId = 'batchCorrectionModal';
    let currentFolder = '';
    let originalFiles = [];
    let displayFiles = [];
    let selectedTmdbId = null;
    let selectedMediaType = 'tv';

    const chineseNumMap = {
        '一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
        '十一':11,'十二':12,'十三':13,'十四':14,'十五':15,'十六':16,'十七':17,'十八':18,'十九':19,'二十':20
    };

    function extractEpisodeNumber(filename) {
        let match = filename.match(/\[(\d+(?:\.\d+)?)\]/);
        if (match) return parseFloat(match[1]);

        match = filename.match(/第\s*([一二三四五六七八九十廿卅0-9]+(?:\.[0-9]+)?)\s*[集話话]/);
        if (match) {
            let numStr = match[1];
            if (/^\d+(\.\d+)?$/.test(numStr)) return parseFloat(numStr);
            return chineseNumMap[numStr] || null;
        }

        match = filename.match(/[Ss]\d{1,2}[Ee](\d{1,3})|(\d{1,2})[xX](\d{1,3})/);
        if (match) return parseInt(match[1] || match[2] || match[3]);

        const parts = filename.split(/[-_\s.]+/);
        for (let part of parts) {
            if (/^\d{1,3}$/.test(part)) {
                let num = parseInt(part);
                if (num < 1900 || num > 2100) return num;
            }
        }

        match = filename.match(/#(\d{1,3})/);
        if (match) return parseInt(match[1]);

        return null;
    }

    function isIntegerEpisode(ep) {
        return ep !== null && Number.isFinite(ep) && Math.floor(ep) === ep;
    }

    function isSpecialLike(filename) {
        const lower = filename.toLowerCase();
        const keywords = ['ova', 'oad', 'sp', '特典', 'menu', 'ncop', 'nced', 'pv', 'cm', '预告', ' preview', 'bonus'];
        return keywords.some(kw => lower.includes(kw));
    }

    function smartSort(files) {
        return files.slice().sort((a, b) => {
            const aEp = extractEpisodeNumber(a.name);
            const bEp = extractEpisodeNumber(b.name);
            const aSpecial = isSpecialLike(a.name);
            const bSpecial = isSpecialLike(b.name);

            if (aSpecial !== bSpecial) return aSpecial ? 1 : -1;
            if (aEp === null && bEp !== null) return 1;
            if (aEp !== null && bEp === null) return -1;
            if (aEp === null && bEp === null) return a.name.localeCompare(b.name);

            const aIsInt = isIntegerEpisode(aEp);
            const bIsInt = isIntegerEpisode(bEp);
            if (aIsInt && !bIsInt) return -1;
            if (!aIsInt && bIsInt) return 1;
            return aEp - bEp;
        });
    }

    function renderFileList() {
        const container = document.getElementById('batchFileList');
        const countSpan = document.getElementById('batchFileCount');
        const selectedCount = displayFiles.filter(f => f.selected).length;
        countSpan.textContent = selectedCount + '/' + displayFiles.length;

        const startEp = parseInt(document.getElementById('batchStartEpisode').value) || 1;
        const increment = parseInt(document.getElementById('batchEpisodeIncrement').value) || 1;
        const mediaType = selectedMediaType || 'tv';

        const table = app.el('table', {});
        const selectAll = app.el('input', {type: 'checkbox', id: 'batchSelectAll', title: '全选'});
        selectAll.addEventListener('change', () => App.BatchCorrection.toggleSelectAll(selectAll.checked));
        const header = app.el('tr', {}, app.el('th', {}, selectAll), app.el('th', {text: '顺序'}), app.el('th', {text: '文件名'}));
        if (mediaType === 'tv') header.append(app.el('th', {text: '预览集号'}));
        header.append(app.el('th', {text: '操作'}));
        table.append(header);
        let epCounter = startEp;
        displayFiles.forEach((file, idx) => {
            const previewEp = file.selected && mediaType === 'tv' ? epCounter : '—';
            if (file.selected && mediaType === 'tv') epCounter += increment;
            const statusBadge = file.status === 'success' ? '[已入库]' : file.status === 'failed' ? '[失败]' : file.status === 'unknown' ? '[未处理]' : '';
            const titleInfo = file.title ? ` (${file.title}${file.season ? ` S${String(file.season).padStart(2,'0')}E${String(file.episode).padStart(2,'0')}` : ''})` : '';
            const checkbox = app.el('input', {type: 'checkbox', checked: !!file.selected, dataset: {index: idx}});
            checkbox.addEventListener('change', () => App.BatchCorrection.toggleFile(idx, checkbox.checked));
            const name = app.el('td', {title: file.path},
                app.el('strong', {text: `${statusBadge} ${file.name}${isSpecialLike(file.name) ? ' [特典]' : ''}`.trim()}));
            if (titleInfo) name.append(app.el('br'), app.el('span', {text: titleInfo, className: 'cell-sub'}));
            const row = app.el('tr', {}, app.el('td', {}, checkbox), app.el('td', {text: idx + 1}), name);
            if (mediaType === 'tv') row.append(app.el('td', {text: previewEp, style: 'font-weight:bold;'}));
            row.append(app.el('td', {}, app.button('上移', () => App.BatchCorrection.moveUp(idx), 'secondary', {disabled: idx === 0}),
                app.button('下移', () => App.BatchCorrection.moveDown(idx), 'secondary', {disabled: idx === displayFiles.length - 1})));
            table.append(row);
        });
        container.replaceChildren(table, app.el('div', {className: 'toolbar'},
            app.button('智能排序（按集号）', () => App.BatchCorrection.smartSort()),
            app.button('提取起始集号', () => App.BatchCorrection.autoExtractStartEpisode()),
            app.button('重置顺序', () => App.BatchCorrection.resetOrder())));

        const allChecked = displayFiles.length > 0 && displayFiles.every(f => f.selected);
        const selectAllCheck = document.getElementById('batchSelectAll');
        if (selectAllCheck) selectAllCheck.checked = allChecked;
    }

    return {
        openModal: function(folder, files) {
            currentFolder = folder;
            originalFiles = files.map(f => ({...f, selected: true}));
            displayFiles = [...originalFiles];
            selectedTmdbId = null;
            selectedMediaType = 'tv';
            document.getElementById('batchFolderPath').innerText = folder;

            let defaultQuery = '';
            if (files.length > 0) {
                defaultQuery = files[0].name.replace(/\.[^/.]+$/, '')
                    .replace(/[Ss]\d{1,2}[Ee]\d{1,3}/g, '')
                    .replace(/第\s*\d+\s*[集話话]/g, '')
                    .replace(/[-_\s]+\d{1,3}(?:\.|$)/g, '')
                    .replace(/[\[\]\(\)【】]/g, ' ')
                    .replace(/\s+/g, ' ').trim() || files[0].name.replace(/\.[^/.]+$/, '');
            }
            document.getElementById('batchTmdbSearchInput').value = defaultQuery;

            document.getElementById('batchTmdbResults').innerHTML = '';
            document.getElementById('batchSelectedTmdbInfo').style.display = 'none';
            document.getElementById('batchSeason').value = 1;
            document.getElementById('batchStartEpisode').value = 1;
            document.getElementById('batchEpisodeIncrement').value = 1;
            document.getElementById('batchTmdbSearchType').value = 'tv';
            const autoCheck = document.getElementById('batchAutoSeasonCheck');
            if (autoCheck) autoCheck.checked = false;
            renderFileList();
            document.getElementById(modalId).style.display = 'block';
        },

        openModalWithFiles: function(folderLabel, files) {
            currentFolder = folderLabel;
            const normalizedFiles = files.map(f => ({
                path: f.path,
                name: f.name,
                reason: f.reason || '手动选择',
                selected: true,
                status: f.status,
                title: f.title,
                season: f.season,
                episode: f.episode
            }));
            originalFiles = normalizedFiles;
            displayFiles = [...originalFiles];
            selectedTmdbId = null;
            selectedMediaType = 'tv';
            document.getElementById('batchFolderPath').innerText = folderLabel;

            let defaultQuery = '';
            if (files.length > 0) {
                defaultQuery = files[0].name.replace(/\.[^/.]+$/, '')
                    .replace(/[Ss]\d{1,2}[Ee]\d{1,3}/g, '')
                    .replace(/第\s*\d+\s*[集話话]/g, '')
                    .replace(/[-_\s]+\d{1,3}(?:\.|$)/g, '')
                    .replace(/[\[\]\(\)【】]/g, ' ')
                    .replace(/\s+/g, ' ').trim() || files[0].name.replace(/\.[^/.]+$/, '');
            }
            document.getElementById('batchTmdbSearchInput').value = defaultQuery;

            document.getElementById('batchTmdbResults').innerHTML = '';
            document.getElementById('batchSelectedTmdbInfo').style.display = 'none';
            document.getElementById('batchSeason').value = 1;
            document.getElementById('batchStartEpisode').value = 1;
            document.getElementById('batchEpisodeIncrement').value = 1;
            document.getElementById('batchTmdbSearchType').value = 'tv';
            const autoCheck = document.getElementById('batchAutoSeasonCheck');
            if (autoCheck) autoCheck.checked = false;
            renderFileList();
            document.getElementById(modalId).style.display = 'block';
        },

        closeModal: function() {
            document.getElementById(modalId).style.display = 'none';
        },

        toggleSelectAll: function(checked) {
            displayFiles.forEach(f => f.selected = checked);
            renderFileList();
        },

        toggleFile: function(idx, checked) {
            if (idx >= 0 && idx < displayFiles.length) {
                displayFiles[idx].selected = checked;
                renderFileList();
            }
        },

        moveUp: function(idx) {
            if (idx > 0) {
                [displayFiles[idx-1], displayFiles[idx]] = [displayFiles[idx], displayFiles[idx-1]];
                renderFileList();
            }
        },

        moveDown: function(idx) {
            if (idx < displayFiles.length-1) {
                [displayFiles[idx], displayFiles[idx+1]] = [displayFiles[idx+1], displayFiles[idx]];
                renderFileList();
            }
        },

        smartSort: function() {
            displayFiles = smartSort(displayFiles);
            renderFileList();
        },

        resetOrder: function() {
            displayFiles = originalFiles.map(f => ({...f}));
            renderFileList();
        },

        autoExtractStartEpisode: function() {
            for (let f of displayFiles) {
                if (f.selected) {
                    const ep = extractEpisodeNumber(f.name);
                    if (ep !== null) {
                        document.getElementById('batchStartEpisode').value = Math.floor(ep);
                        app.showToast(`起始集号已设为 ${Math.floor(ep)}`, 'info', 1500);
                        renderFileList();
                        return;
                    }
                }
            }
            app.showToast('未能从文件名提取集号', 'warning');
        },

        searchTmdb: async function() {
            const query = document.getElementById('batchTmdbSearchInput').value.trim();
            const mediaType = document.getElementById('batchTmdbSearchType').value;
            if (!query) {
                app.showToast('请输入搜索关键词', 'warning');
                return;
            }
            const resultsDiv = document.getElementById('batchTmdbResults');
            resultsDiv.innerHTML = '<div class="text-muted">正在搜索 TMDB…</div>';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 25000);

            try {
                const resp = await app.fetch(`/api/tmdb/search_proxy?query=${encodeURIComponent(query)}&media_type=${mediaType}`, {
                    signal: controller.signal
                });
                clearTimeout(timeoutId);

                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
                const data = await resp.json();
                if (data.error) throw new Error(data.error);

                if (!data.results || data.results.length === 0) {
                    resultsDiv.innerHTML = '<div class="text-muted">没有搜索结果，换个关键词试试</div>';
                    return;
                }

                app.renderTmdbResults(resultsDiv, data.results, mediaType,
                    (id, title, type) => App.BatchCorrection.selectTmdb(id, title, type));
            } catch (e) {
                clearTimeout(timeoutId);
                let errMsg = e.message || '网络错误';
                resultsDiv.replaceChildren(app.el('div', {className: 'text-danger', text: '搜索失败：' + errMsg}));
                app.showToast(errMsg, 'error');
            }
        },

        selectTmdb: function(id, title, mediaType) {
            selectedTmdbId = id;
            selectedMediaType = mediaType;
            document.getElementById('batchSelectedTmdbTitle').innerText = title;
            document.getElementById('batchSelectedTmdbId').innerText = id;
            document.getElementById('batchSelectedTmdbInfo').style.display = 'block';
            const isMovie = (mediaType === 'movie');
            document.getElementById('batchSeason').disabled = isMovie;
            document.getElementById('batchStartEpisode').disabled = isMovie;
            document.getElementById('batchEpisodeIncrement').disabled = isMovie;
            const autoCheck = document.getElementById('batchAutoSeasonCheck');
            if (autoCheck) autoCheck.disabled = isMovie;
            renderFileList();
        },

        // ========== 异步执行批量修正（支持自动跨季换算） ==========
        execute: async function() {
            if (!selectedTmdbId) {
                app.showToast('请先搜索并选择 TMDB 条目', 'warning');
                return;
            }
            const selectedFiles = displayFiles.filter(f => f.selected);
            if (selectedFiles.length === 0) {
                app.showToast('请至少勾选一个文件', 'warning');
                return;
            }
            const seasonInput = document.getElementById('batchSeason');
            const startEpisode = parseInt(document.getElementById('batchStartEpisode').value) || 1;
            const increment = parseInt(document.getElementById('batchEpisodeIncrement').value) || 1;
            const mediaType = selectedMediaType;

            // 检查是否启用自动跨季换算
            const autoSeasonCheck = document.getElementById('batchAutoSeasonCheck');
            const useAutoSeason = autoSeasonCheck && autoSeasonCheck.checked && mediaType === 'tv';

            // 如果启用自动换算，season 传 null；否则使用输入框的值
            const season = useAutoSeason ? null : (parseInt(seasonInput.value) || 1);

            const srcPaths = selectedFiles.map(f => f.path);
            const payload = {
                src_paths: srcPaths,
                tmdb_id: selectedTmdbId,
                media_type: mediaType,
                season: season,
                start_episode: mediaType === 'tv' ? startEpisode : null,
                episode_increment: mediaType === 'tv' ? increment : null
            };

            this.closeModal();
            const statusText = document.getElementById('statusText');
            const runBtn = document.getElementById('runBtn');
            const stopBtn = document.getElementById('stopBtn');
            if (statusText) statusText.textContent = '批量修正中...';
            if (runBtn) runBtn.disabled = true;
            if (stopBtn) stopBtn.disabled = false;

            try {
                const resp = await app.fetch('/api/failed_cache/batch_correct', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (data.status === 'started') {
                    app.showToast(`批量修正任务已启动，共 ${data.total} 个文件`, 'success');
                    if (typeof App.Task !== 'undefined') {
                        App.Task.startStatusPolling();
                    }
                } else {
                    app.showToast('启动失败：' + (data.message || '未知错误'), 'error');
                    if (statusText) statusText.textContent = '空闲';
                    if (runBtn) runBtn.disabled = false;
                    if (stopBtn) stopBtn.disabled = true;
                }
            } catch (e) {
                app.showToast('请求失败：' + e.message, 'error');
                if (statusText) statusText.textContent = '空闲';
                if (runBtn) runBtn.disabled = false;
                if (stopBtn) stopBtn.disabled = true;
            }
        }
    };
})(window.App);
