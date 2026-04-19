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

    async function _loadCache() {
        try {
            const resp = await fetch('/api/failed_cache/clusters');
            const data = await resp.json();
            const listDiv = document.getElementById(listDivId);
            const countSpan = document.getElementById(countSpanId);
            currentClusters = data.clusters || [];

            const totalFiles = currentClusters.reduce((sum, c) => sum + c.count, 0);
            countSpan.textContent = totalFiles;

            if (currentClusters.length === 0) {
                listDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#28a745;">✅ 暂无失败缓存记录</div>';
                return;
            }

            let html = '<div style="margin-bottom:10px;"><button onclick="App.FailedCache.switchToListView()" class="secondary">📋 切换为列表视图</button></div>';
            html += '<table class="failed-table">';
            html += '<tr><th>文件夹</th><th>失败数量</th><th>操作</th></tr>';

            for (const cluster of currentClusters) {
                const folderEscaped = app.escapeHtml(cluster.folder);
                // 将失败文件列表转为JSON字符串供批量修正使用
                const filesJson = JSON.stringify(cluster.files).replace(/"/g, '&quot;');
                html += `<tr>
                    <td title="${folderEscaped}" style="max-width:400px; word-break:break-all;">${folderEscaped}</td>
                    <td>${cluster.count}</td>
                    <td>
                        <button onclick="App.BatchCorrection.openModal('${folderEscaped}', ${filesJson})" class="success" style="padding:4px 8px;">📦 批量修正</button>
                        <button onclick="App.FailedCache.showFilesInFolder('${folderEscaped}', ${filesJson})" class="secondary" style="padding:4px 8px;">📂 查看失败文件</button>
                        <button onclick="App.FailedCache.showAllFilesInFolder('${folderEscaped}')" class="secondary" style="padding:4px 8px; margin-left:4px;">📋 查看所有文件</button>
                    </td>
                </tr>`;
            }
            html += '</table>';
            listDiv.innerHTML = html;
        } catch (e) {
            document.getElementById(listDivId).innerHTML = '<div style="padding:20px;color:#dc3545;">加载失败</div>';
        }
    }

    // 显示文件夹内的失败文件列表（原有功能）
    function _showFilesInFolder(folder, files) {
        const listDiv = document.getElementById(listDivId);
        let html = `<div style="margin-bottom:10px;">
            <button onclick="App.FailedCache.loadFailedCache()" class="secondary">🔙 返回聚类视图</button>
            <span style="margin-left:15px;">📁 ${app.escapeHtml(folder)}</span>
        </div>`;
        html += '<table class="failed-table"><tr><th>文件名</th><th>失败原因</th><th>操作</th></tr>';

        files.forEach(file => {
            const escapedPath = app.escapeHtml(file.path);
            const escapedName = app.escapeHtml(file.name);
            const escapedReason = app.escapeHtml(file.reason);
            html += `<tr>
                <td title="${escapedPath}">${escapedName}</td>
                <td style="color:#dc3545;">${escapedReason}</td>
                <td><button onclick="App.Correction.openCorrectionModal('${escapedPath}', '${escapedName}')" class="warning" style="padding:4px 8px;">🔧 单文件修正</button></td>
            </tr>`;
        });
        html += '</table>';
        listDiv.innerHTML = html;
    }

    // 切换回旧版列表视图（简单聚合所有文件）
    async function _switchToListView() {
        try {
            const resp = await fetch('/api/failed_cache');
            const data = await resp.json();
            const listDiv = document.getElementById(listDivId);
            const countSpan = document.getElementById(countSpanId);

            if (!data.failed || data.failed.length === 0) {
                listDiv.innerHTML = '<div style="padding:20px;text-align:center;color:#28a745;">✅ 暂无失败缓存记录</div>';
                countSpan.textContent = '0';
                return;
            }
            countSpan.textContent = data.failed.length;

            let html = '<div style="margin-bottom:10px;"><button onclick="App.FailedCache.loadFailedCache()" class="secondary">🔙 返回聚类视图</button></div>';
            html += '<table class="failed-table"><tr><th>文件名</th><th>失败原因</th><th>时间</th><th>操作</th></tr>';
            for (const item of data.failed) {
                const timeStr = item.failed_time ? new Date(item.failed_time * 1000).toLocaleString() : '未知';
                const escapedPath = app.escapeHtml(item.path);
                const escapedName = app.escapeHtml(item.name);
                const escapedReason = app.escapeHtml(item.reason);
                html += `<tr>
                    <td title="${escapedPath}">${escapedName}</td>
                    <td style="color:#dc3545;">${escapedReason}</td>
                    <td>${timeStr}</td>
                    <td><button onclick="App.Correction.openCorrectionModal('${escapedPath}', '${escapedName}')" class="warning" style="padding:4px 8px;">🔧 修正</button></td>
                </tr>`;
            }
            html += '</table>';
            listDiv.innerHTML = html;
        } catch (e) {
            document.getElementById(listDivId).innerHTML = '<div style="padding:20px;color:#dc3545;">加载失败</div>';
        }
    }

    // ---------- 新增：查看文件夹内所有视频文件（含成功与失败）----------
    async function _showAllFilesInFolder(folder) {
        const listDiv = document.getElementById(listDivId);
        // 显示加载状态
        listDiv.innerHTML = '<div style="padding:20px;text-align:center;">🔄 正在加载文件夹详情...</div>';

        try {
            const resp = await fetch(`/api/failed_cache/folder_details?folder=${encodeURIComponent(folder)}`);
            const data = await resp.json();
            if (!data.files) {
                listDiv.innerHTML = '<div style="padding:20px;color:#dc3545;">获取文件夹详情失败</div>';
                return;
            }

            const files = data.files;
            // 转换为批量修正需要的格式，并附带状态信息
            const filesForBatch = files.map(f => ({
                path: f.path,
                name: f.name,
                status: f.status,
                title: f.title || '',
                season: f.season,
                episode: f.episode,
                reason: f.reason || (f.status === 'success' ? `已识别: ${f.title || '未知'}` : '未处理')
            }));

            // 显示详情表格（可勾选，复用批量修正模块的样式逻辑，但这里我们直接展示一个简化的预览表格，并提供批量修正入口）
            let html = `<div style="margin-bottom:10px;">
                <button onclick="App.FailedCache.loadFailedCache()" class="secondary">🔙 返回聚类视图</button>
                <span style="margin-left:15px;">📁 ${app.escapeHtml(folder)} (共 ${files.length} 个视频文件)</span>
                <button onclick="App.FailedCache.openBatchWithAllFiles('${app.escapeHtml(folder).replace(/'/g, "\\'")}')" class="success" style="margin-left:15px;">📦 批量修正全部</button>
            </div>`;

            html += '<table class="failed-table"><tr><th>状态</th><th>文件名</th><th>识别信息</th><th>操作</th></tr>';

            files.forEach(file => {
                const escapedPath = app.escapeHtml(file.path);
                const escapedName = app.escapeHtml(file.name);
                let statusBadge, statusText;
                if (file.status === 'success') {
                    statusBadge = '✅';
                    statusText = '成功';
                } else if (file.status === 'failed') {
                    statusBadge = '❌';
                    statusText = '失败';
                } else {
                    statusBadge = '❓';
                    statusText = '未处理';
                }

                let infoText = '';
                if (file.status === 'success') {
                    infoText = `${file.title || ''}`;
                    if (file.media_type === 'tv' && file.season && file.episode) {
                        infoText += ` S${String(file.season).padStart(2, '0')}E${String(file.episode).padStart(2, '0')}`;
                    }
                    infoText += ` (置信度: ${file.confidence || 0}%)`;
                } else if (file.status === 'failed') {
                    infoText = `失败原因: ${file.reason || '未知'}`;
                } else {
                    infoText = '尚未处理';
                }

                html += `<tr>
                    <td title="${statusText}">${statusBadge}</td>
                    <td title="${escapedPath}">${escapedName}</td>
                    <td style="font-size:12px;">${app.escapeHtml(infoText)}</td>
                    <td>`;
                if (file.status === 'failed' || file.status === 'unknown') {
                    html += `<button onclick="App.Correction.openCorrectionModal('${escapedPath}', '${escapedName}')" class="warning" style="padding:4px 8px;">🔧 修正</button>`;
                } else {
                    html += `<button onclick="App.Correction.openCorrectionModal('${escapedPath}', '${escapedName}')" class="secondary" style="padding:4px 8px;">🔄 重处理</button>`;
                }
                html += `</td></tr>`;
            });
            html += '</table>';

            // 底部操作：直接调用批量修正（勾选全部文件）
            html += `<div style="margin-top:12px;">
                <button onclick="App.FailedCache.openBatchWithAllFiles('${app.escapeHtml(folder).replace(/'/g, "\\'")}')" class="success">📦 批量修正此文件夹所有文件</button>
                <span class="note" style="margin-left:10px;">💡 点击后将打开批量修正面板，可调整顺序并选择正确 TMDB 条目</span>
            </div>`;

            listDiv.innerHTML = html;
            // 将文件数据暂存到全局，供批量修正调用
            window.__currentFolderAllFiles = filesForBatch;
        } catch (e) {
            listDiv.innerHTML = '<div style="padding:20px;color:#dc3545;">请求失败: ' + e.message + '</div>';
        }
    }

    // 打开批量修正，并传入当前文件夹所有文件
    function _openBatchWithAllFiles(folder) {
        const files = window.__currentFolderAllFiles;
        if (!files || files.length === 0) {
            app.showToast('没有可用的文件', 'warning');
            return;
        }
        if (typeof App.BatchCorrection !== 'undefined') {
            App.BatchCorrection.openModalWithFiles(`📁 ${folder}`, files);
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
            const resp = await fetch('/api/failed_cache/clear', { method: 'POST' });
            const data = await resp.json();
            if (data.status === 'success') {
                alert(`已清空 ${data.removed} 条`);
                await _loadCache();
            } else {
                alert('清空失败');
            }
        }
    };
})(window.App);
