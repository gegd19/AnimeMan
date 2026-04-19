/**
 * 离线 AI 预解析控制模块
 */
window.App = window.App || {};
App.OfflinePreparser = (function(app) {
    'use strict';

    let statusInterval = null;

    // 更新状态显示
    async function updateStatus() {
        try {
            const resp = await fetch('/api/offline/status');
            const data = await resp.json();

            // 更新显示
            document.getElementById('offlineScanStatus').innerHTML =
                `📁 已扫描 ${data.total_folders || 0} 个文件夹，共 ${data.total_files || 0} 个视频文件`;
            document.getElementById('offlineCacheStatus').innerHTML =
                `🤖 已缓存 ${data.cached_folders || 0} 个文件夹的 AI 解析结果`;

            const scanBtn = document.getElementById('offlineScanBtn');
            const parseBtn = document.getElementById('offlineParseBtn');

            // 处理扫描中状态
            if (data.scanning) {
                scanBtn.disabled = true;
                scanBtn.textContent = `⏳ 扫描中 ${data.scan_progress || 0}/${data.scan_total || 0}`;
                // 显示进度 toast（可选，避免频繁弹窗）
                if (data.scan_message) {
                    // 不频繁弹 toast，仅在状态栏显示，或者用非阻塞提示
                }
            } else {
                scanBtn.disabled = false;
                scanBtn.textContent = '🔍 扫描源文件夹';
            }

            // 处理解析中状态
            if (data.parsing) {
                parseBtn.disabled = true;
                parseBtn.textContent = `⏳ 解析中 ${data.parse_progress || 0}/${data.parse_total || 0}`;
            } else {
                parseBtn.disabled = false;
                parseBtn.textContent = '⚡ 全量预解析 (按需可选)';
            }

            // 如果扫描刚完成，提示用户
            if (!data.scanning && data.scan_message && data.scan_message.includes('完成')) {
                // 清除轮询
                if (statusInterval) {
                    clearInterval(statusInterval);
                    statusInterval = null;
                }
                app.showToast(data.scan_message, 'success', 3000);
            }
            if (!data.parsing && data.parse_message && data.parse_message.includes('完成')) {
                if (statusInterval) {
                    clearInterval(statusInterval);
                    statusInterval = null;
                }
                app.showToast(data.parse_message, 'success', 3000);
            }

        } catch (e) {
            console.error('获取离线预解析状态失败', e);
        }
    }

    // 开始轮询状态
    function startPolling() {
        if (statusInterval) clearInterval(statusInterval);
        statusInterval = setInterval(updateStatus, 1000);
    }

    return {
        // 扫描源文件夹
        scanFolders: async function() {
            const btn = document.getElementById('offlineScanBtn');
            if (btn.disabled) return;

            try {
                const resp = await fetch('/api/offline/scan', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast('扫描任务已启动', 'info', 1500);
                    startPolling();
                } else {
                    app.showToast('❌ 扫描失败：' + (data.message || '未知错误'), 'error');
                }
            } catch (e) {
                app.showToast('请求失败：' + e.message, 'error');
            }
        },

        // 全量预解析
        runFullPreparse: async function() {
            if (!confirm('全量预解析将对所有未缓存的文件夹调用 AI，可能产生费用。确定继续吗？')) return;
            const btn = document.getElementById('offlineParseBtn');
            if (btn.disabled) return;

            try {
                const resp = await fetch('/api/offline/parse', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast('预解析任务已启动', 'info', 1500);
                    startPolling();
                } else {
                    app.showToast('❌ 预解析失败：' + (data.message || '未知错误'), 'error');
                }
            } catch (e) {
                app.showToast('请求失败：' + e.message, 'error');
            }
        },

        // 刷新状态
        refreshStatus: function() {
            updateStatus();
        }
    };
})(window.App);
