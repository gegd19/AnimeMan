/**
 * 处理记录模块
 * 支持排序、最多显示300条、自动重试、手动修正入口、批量选择与批量修正
 */
window.App = window.App || {};
App.History = (function(app) {
    'use strict';

    const tableBodyId = 'historyBody';
    const sortSelectId = 'historySortSelect';

    let currentHistoryData = [];          // 当前加载的历史数据
    let selectedItems = new Set();        // 选中的项目 src 集合

    // 渲染表格
    function renderTable(history) {
        const tbody = document.getElementById(tableBodyId);
        const selectAllCheck = document.getElementById('historySelectAll');

        if (history.length === 0) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">暂无记录</td></tr>';
            if (selectAllCheck) selectAllCheck.checked = false;
            updateBatchButtons();
            return;
        }

        let html = '';
        history.forEach(item => {
            const conf = item.confidence || 0;
            let color = '#28a745';
            if (conf < 60) color = '#dc3545';
            else if (conf < 80) color = '#fd7e14';

            let displayTitle = item.title || '未知标题';
            if (item.media_type === 'tv' && item.season !== undefined && item.episode !== undefined) {
                displayTitle += ` S${item.season.toString().padStart(2, '0')}E${item.episode.toString().padStart(2, '0')}`;
            } else if (item.media_type === 'movie' && item.year) {
                displayTitle += ` (${item.year})`;
            }

            const escapedSrc = app.escapeHtml(item.src || '');
            const escapedSrcName = app.escapeHtml(item.src_name || '');
            const escapedDisplayTitle = app.escapeHtml(displayTitle);
            const isChecked = selectedItems.has(item.src) ? 'checked' : '';

            html += `<tr>
                <td><input type="checkbox" class="history-checkbox" data-src="${escapedSrc}" ${isChecked} onchange="App.History.toggleSelect('${escapedSrc}', this.checked)"></td>
                <td title="${escapedSrc}" style="max-width: 200px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapedSrcName}</td>
                <td title="${escapedDisplayTitle}" style="max-width: 250px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;">${escapedDisplayTitle}</td>
                <td style="color:${color};font-weight:bold;">${conf}%</td>
                <td>
                    <button onclick="App.History.retryProcessed('${escapedSrc}')" class="secondary" style="padding:4px 8px;">🔄 重试</button>
                    <button onclick="App.History.openManualCorrectionForHistory('${escapedSrc}', '${escapedSrcName}')" class="warning" style="padding:4px 8px; margin-left:4px;">🔧 修正</button>
                </td>
            </tr>`;
        });
        tbody.innerHTML = html;

        // 更新全选复选框状态
        if (selectAllCheck) {
            selectAllCheck.checked = (selectedItems.size === history.length && history.length > 0);
        }
        updateBatchButtons();
    }

    // 更新批量操作按钮状态
    function updateBatchButtons() {
        const batchBtn = document.getElementById('historyBatchCorrectBtn');
        const countSpan = document.getElementById('historySelectedCount');
        if (batchBtn) {
            batchBtn.disabled = (selectedItems.size === 0);
        }
        if (countSpan) {
            countSpan.textContent = selectedItems.size;
        }
    }

    // 公开接口
    return {
        /**
         * 加载处理记录
         */
        loadProcessedHistory: async function() {
            try {
                const select = document.getElementById(sortSelectId);
                const value = select.value;
                let sort, order;
                if (value.startsWith('processed_time')) {
                    sort = 'processed_time';
                    order = value.includes('desc') ? 'desc' : 'asc';
                } else {
                    sort = 'src_name';
                    order = value.includes('desc') ? 'desc' : 'asc';
                }
                const resp = await fetch(`/api/processed_history?sort=${sort}&order=${order}`);
                const data = await resp.json();
                currentHistoryData = data.history || [];
                selectedItems.clear();
                renderTable(currentHistoryData);
            } catch (e) {
                console.error('加载处理记录失败:', e);
                document.getElementById(tableBodyId).innerHTML = '<tr><td colspan="5" style="text-align:center; color:#dc3545;">加载失败，请重试</td></tr>';
            }
        },

        /**
         * 全选/取消全选
         */
        toggleSelectAll: function(checked) {
            if (checked) {
                currentHistoryData.forEach(item => selectedItems.add(item.src));
            } else {
                selectedItems.clear();
            }
            renderTable(currentHistoryData);
        },

        /**
         * 单个选择切换
         */
        toggleSelect: function(src, checked) {
            if (checked) {
                selectedItems.add(src);
            } else {
                selectedItems.delete(src);
            }
            renderTable(currentHistoryData);
        },

        /**
         * 打开批量修正模态框（复用 batchCorrection）
         */
        openBatchCorrectionForHistory: function() {
            if (selectedItems.size === 0) {
                app.showToast('请至少勾选一个文件', 'warning');
                return;
            }

            // 从 currentHistoryData 中提取选中文件的完整信息
            const selectedFiles = currentHistoryData
                .filter(item => selectedItems.has(item.src))
                .map(item => ({
                    path: item.src,
                    name: item.src_name,
                    // 历史记录没有失败原因，给个默认提示
                    reason: `已处理为: ${item.title || '未知'}`
                }));

            // 调用 batchCorrection 的通用打开方法
            if (typeof App.BatchCorrection !== 'undefined') {
                // 使用一个虚拟文件夹名（显示为"历史记录选中项"）
                App.BatchCorrection.openModalWithFiles('📋 历史记录选中项', selectedFiles);
            } else {
                app.showToast('批量修正模块未加载', 'error');
            }
        },

        /**
         * 从历史记录打开手动修正模态框（单文件）
         */
        openManualCorrectionForHistory: function(srcPath, fileName) {
            if (typeof App.Correction !== 'undefined') {
                App.Correction.openCorrectionModal(srcPath, fileName);
            }
        },

        /**
         * 重新处理某个文件（单文件重试）
         */
        retryProcessed: async function(srcPath) {
            if (!confirm('确定重新处理该文件吗？之前的链接和 NFO 将被删除。')) return;
            try {
                const resp = await fetch('/api/processed/retry', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ src_path: srcPath })
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast('重处理成功！', 'success');
                    this.loadProcessedHistory();
                } else {
                    app.showToast('重处理失败：' + (data.message || '未知错误'), 'error');
                }
            } catch (e) {
                app.showToast('请求失败：' + e.message, 'error');
            }
        }
    };
})(window.App);
