/**
 * 已处理缓存管理模块（增强版）
 * - 分页、排序、详细路径
 * - 多选、全选、反选、批量删除
 * - 单条手动修正（替代自动重试）
 * - 批量手动修正（复用 BatchCorrection 模块）
 * - 智能排序（按集号）
 * - 置信度排序支持升/降切换
 */
window.App = window.App || {};
App.ProcessedCache = (function(app) {
    'use strict';

    const modalId = 'processedCacheModal';
    const tableBodyId = 'processedCacheBody';
    const countSpanId = 'processedCacheCount';
    const paginationId = 'processedCachePagination';

    let currentPage = 1;
    let totalPages = 1;
    let currentSort = 'processed_time';
    let currentOrder = 'desc';
    let currentKeyword = '';
    let selectedItems = new Set();
    let allItems = [];

    const chineseNumMap = {
        '一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
        '十一':11,'十二':12,'十三':13,'十四':14,'十五':15,'十六':16,'十七':17,'十八':18,'十九':19,'二十':20
    };

    function formatTime(timestamp) {
        if (!timestamp) return '未知';
        return new Date(timestamp * 1000).toLocaleString();
    }

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

    function smartSortFiles(files) {
        return files.slice().sort((a, b) => {
            const aEp = extractEpisodeNumber(a.src_name);
            const bEp = extractEpisodeNumber(b.src_name);
            const aSpecial = isSpecialLike(a.src_name);
            const bSpecial = isSpecialLike(b.src_name);

            if (aSpecial !== bSpecial) return aSpecial ? 1 : -1;
            if (aEp === null && bEp !== null) return 1;
            if (aEp !== null && bEp === null) return -1;
            if (aEp === null && bEp === null) return a.src_name.localeCompare(b.src_name);

            const aIsInt = isIntegerEpisode(aEp);
            const bIsInt = isIntegerEpisode(bEp);
            if (aIsInt && !bIsInt) return -1;
            if (!aIsInt && bIsInt) return 1;
            return aEp - bEp;
        });
    }

    function updateBatchButtons() {
        const deleteBtn = document.getElementById('batchDeleteProcessedBtn');
        const correctBtn = document.getElementById('batchCorrectProcessedBtn');
        const selectCountSpan = document.getElementById('selectedProcessedCount');
        const total = selectedItems.size;
        if (deleteBtn) deleteBtn.disabled = (total === 0);
        if (correctBtn) correctBtn.disabled = (total === 0);
        if (selectCountSpan) selectCountSpan.textContent = total;
    }

    function renderTable(items) {
        allItems = items;
        const tbody = document.getElementById(tableBodyId);
        const countSpan = document.getElementById(countSpanId);
        countSpan.textContent = items.length;

        const selectAllCheck = document.getElementById('processedCacheSelectAll');
        if (items.length === 0) {
            tbody.innerHTML = '<tr><td colspan="9" style="text-align:center; padding:20px;">暂无已处理缓存记录</td></tr>';
            if (selectAllCheck) selectAllCheck.checked = false;
            updateBatchButtons();
            return;
        }

        let html = '';
        let pageSelectedCount = 0;
        items.forEach(item => {
            const isChecked = selectedItems.has(item.src);
            if (isChecked) pageSelectedCount++;

            const targetExists = item.target_exists ? '✅' : '⚠️';
            let mediaInfo = item.title || '未知';
            if (item.media_type === 'tv' && item.season && item.episode) {
                mediaInfo += ` S${String(item.season).padStart(2, '0')}E${String(item.episode).padStart(2, '0')}`;
            } else if (item.media_type === 'movie' && item.year) {
                mediaInfo += ` (${item.year})`;
            }

            const dirPath = item.grandparent_dir ? `${item.grandparent_dir}/${item.parent_dir}` : item.parent_dir;

            html += `<tr>
                <td><input type="checkbox" class="processed-cache-checkbox" data-src="${app.escapeHtml(item.src)}" ${isChecked ? 'checked' : ''} onchange="App.ProcessedCache.toggleSelect('${app.escapeHtml(item.src).replace(/'/g, "\\'")}', this.checked)"></td>
                <td title="${app.escapeHtml(item.src)}">${app.escapeHtml(item.src_name)}</td>
                <td title="${app.escapeHtml(item.src)}" style="font-size:12px; color:#6c757d;">${app.escapeHtml(dirPath)}</td>
                <td title="${app.escapeHtml(item.target)}">${targetExists} ${app.escapeHtml(item.target.split('/').pop())}</td>
                <td>${app.escapeHtml(mediaInfo)}</td>
                <td>${item.confidence ? item.confidence + '%' : '-'}</td>
                <td>${formatTime(item.processed_time)}</td>
                <td>
                    <button class="secondary" style="padding:4px 6px;" onclick="App.ProcessedCache.manualCorrectItem('${app.escapeHtml(item.src).replace(/'/g, "\\'")}', '${app.escapeHtml(item.src_name).replace(/'/g, "\\'")}')">🔧 手动修正</button>
                    <button class="danger" style="padding:4px 6px;" onclick="App.ProcessedCache.deleteItem('${app.escapeHtml(item.src).replace(/'/g, "\\'")}')">🗑️ 删除</button>
                </td>
            </tr>`;
        });
        tbody.innerHTML = html;

        if (selectAllCheck) {
            selectAllCheck.checked = (pageSelectedCount === items.length && items.length > 0);
            selectAllCheck.indeterminate = (pageSelectedCount > 0 && pageSelectedCount < items.length);
        }
        updateBatchButtons();

        // 更新表头排序图标
        updateSortIndicator();
    }

    function updateSortIndicator() {
        const headers = document.querySelectorAll('#processedCacheTable th[data-sort]');
        headers.forEach(th => {
            const sortField = th.dataset.sort;
            let icon = '';
            if (sortField === currentSort) {
                icon = currentOrder === 'desc' ? ' ↓' : ' ↑';
            }
            // 保留原有文字，追加图标
            if (!th.innerHTML.includes('↓') && !th.innerHTML.includes('↑')) {
                th.innerHTML = th.innerHTML.replace(/(准确率|置信度)/, '$1' + icon);
            } else {
                th.innerHTML = th.innerHTML.replace(/[↓↑]/, '') + icon;
            }
        });
    }

    function renderPagination() {
        const container = document.getElementById(paginationId);
        if (totalPages <= 1) {
            container.innerHTML = '';
            return;
        }

        let html = '<div style="display:flex; align-items:center; justify-content:center; gap:8px; margin-top:12px; flex-wrap:wrap;">';
        html += `<button onclick="App.ProcessedCache.goToPage(1)" ${currentPage === 1 ? 'disabled' : ''}>⏮️</button>`;
        html += `<button onclick="App.ProcessedCache.goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''}>◀</button>`;
        html += `<span>第 ${currentPage} / ${totalPages} 页</span>`;
        html += `<button onclick="App.ProcessedCache.goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''}>▶</button>`;
        html += `<button onclick="App.ProcessedCache.goToPage(${totalPages})" ${currentPage === totalPages ? 'disabled' : ''}>⏭️</button>`;
        html += '</div>';
        container.innerHTML = html;
    }

    async function loadCache() {
        try {
            const resp = await fetch(`/api/processed_cache?page=${currentPage}&per_page=50&sort=${currentSort}&order=${currentOrder}`);
            const data = await resp.json();
            const items = data.items || [];
            totalPages = data.total_pages || 1;
            renderTable(items);
            renderPagination();
        } catch (e) {
            document.getElementById(tableBodyId).innerHTML = '<tr><td colspan="9" style="text-align:center; color:#dc3545;">加载失败，请重试</td></tr>';
            app.showToast('加载已处理缓存失败', 'error');
        }
    }

    function setupAutoRefresh() {
        window.addEventListener('batchCorrectionDone', () => {
            loadCache();
            if (typeof App.MediaManager !== 'undefined') {
                App.MediaManager.refreshLibrary();
            }
        });
    }

    function batchCorrectSelected() {
        if (selectedItems.size === 0) {
            app.showToast('请至少勾选一条记录', 'warning');
            return;
        }

        const selectedFiles = allItems.filter(item => selectedItems.has(item.src)).map(item => ({
            path: item.src,
            name: item.src_name,
            reason: `已处理为: ${item.title || '未知'}`
        }));

        if (typeof App.BatchCorrection !== 'undefined') {
            App.BatchCorrection.openModalWithFiles('📋 已处理缓存选中项', selectedFiles);
        } else {
            app.showToast('批量修正模块未加载', 'error');
        }
    }

    function smartSortAndBatchCorrect() {
        if (selectedItems.size === 0) {
            app.showToast('请至少勾选一条记录', 'warning');
            return;
        }

        const selectedFiles = allItems.filter(item => selectedItems.has(item.src)).map(item => ({
            path: item.src,
            name: item.src_name,
            reason: `已处理为: ${item.title || '未知'}`
        }));

        const sorted = smartSortFiles(selectedFiles);

        if (typeof App.BatchCorrection !== 'undefined') {
            App.BatchCorrection.openModalWithFiles('📋 已处理缓存（智能排序）', sorted);
        } else {
            app.showToast('批量修正模块未加载', 'error');
        }
    }

    setupAutoRefresh();

    return {
        viewProcessedCache: function() {
            document.getElementById(modalId).style.display = 'block';
            document.getElementById('processedCacheSearchInput').value = '';
            currentPage = 1;
            currentKeyword = '';
            selectedItems.clear();
            loadCache();
        },

        closeModal: function() {
            document.getElementById(modalId).style.display = 'none';
        },

        goToPage: function(page) {
            if (page < 1) page = 1;
            if (page > totalPages) page = totalPages;
            currentPage = page;
            loadCache();
        },

        setSort: function(sortField) {
            if (currentSort === sortField) {
                currentOrder = currentOrder === 'desc' ? 'asc' : 'desc';
            } else {
                currentSort = sortField;
                currentOrder = 'desc';
            }
            currentPage = 1;
            loadCache();
        },

        toggleSelect: function(src, checked) {
            if (checked) {
                selectedItems.add(src);
            } else {
                selectedItems.delete(src);
            }
            loadCache();
        },

        toggleSelectAll: function(checked) {
            allItems.forEach(item => {
                if (checked) {
                    selectedItems.add(item.src);
                } else {
                    selectedItems.delete(item.src);
                }
            });
            loadCache();
        },

        invertSelection: function() {
            allItems.forEach(item => {
                if (selectedItems.has(item.src)) {
                    selectedItems.delete(item.src);
                } else {
                    selectedItems.add(item.src);
                }
            });
            loadCache();
        },

        filterTable: function(keyword) {
            currentKeyword = keyword;
            loadCache();
        },

        clearAllCache: async function() {
            if (!confirm('确定要清空所有已处理缓存吗？\n\n此操作不会删除实际文件，但清空后，下次扫描会重新处理所有视频文件。')) {
                return;
            }
            try {
                const resp = await fetch('/api/processed_cache/clear', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast(`已清空 ${data.removed} 条缓存记录`, 'success');
                    this.closeModal();
                    if (typeof App.MediaManager !== 'undefined') {
                        App.MediaManager.refreshLibrary();
                    }
                } else {
                    app.showToast('清空失败', 'error');
                }
            } catch (e) {
                app.showToast('请求失败: ' + e.message, 'error');
            }
        },

        deleteItem: async function(srcPath) {
            if (!confirm('确定要删除这条缓存记录吗？\n\n删除后，下次扫描会重新处理该文件。')) {
                return;
            }
            try {
                const resp = await fetch('/api/processed_cache/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ src_path: srcPath })
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast('删除成功', 'success');
                    selectedItems.delete(srcPath);
                    loadCache();
                    if (typeof App.MediaManager !== 'undefined') {
                        App.MediaManager.refreshLibrary();
                    }
                } else {
                    app.showToast('删除失败: ' + data.message, 'error');
                }
            } catch (e) {
                app.showToast('请求失败', 'error');
            }
        },

        batchDeleteSelected: async function() {
            if (selectedItems.size === 0) {
                app.showToast('请至少勾选一条记录', 'warning');
                return;
            }
            if (!confirm(`确定要删除选中的 ${selectedItems.size} 条缓存记录吗？`)) {
                return;
            }
            const paths = Array.from(selectedItems);
            try {
                const resp = await fetch('/api/processed_cache/batch_delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ src_paths: paths })
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast(`成功删除 ${data.deleted} 条记录`, 'success');
                    selectedItems.clear();
                    loadCache();
                    if (typeof App.MediaManager !== 'undefined') {
                        App.MediaManager.refreshLibrary();
                    }
                } else {
                    app.showToast('删除失败: ' + data.message, 'error');
                }
            } catch (e) {
                app.showToast('请求失败', 'error');
            }
        },

        manualCorrectItem: function(srcPath, fileName) {
            if (typeof App.Correction !== 'undefined') {
                App.Correction.openCorrectionModal(srcPath, fileName);
            } else {
                app.showToast('手动修正模块未加载', 'error');
            }
        },

        batchCorrectSelected: batchCorrectSelected,
        smartSortAndBatchCorrect: smartSortAndBatchCorrect
    };
})(window.App);
