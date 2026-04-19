/**
 * 任务控制模块
 * 负责启动/停止任务，轮询状态，显示日志
 * 支持双击停止按钮强制重置卡住的任务
 */
window.App = window.App || {};
App.Task = (function(app) {
    'use strict';

    let stopClickTimer = null;
    let stopClickCount = 0;

    // ---------- 私有函数 ----------
    async function _updateStatus() {
        try {
            const resp = await fetch('/api/status');
            const data = await resp.json();
            const fill = document.getElementById('progressFill');
            const statusText = document.getElementById('statusText');
            const runBtn = document.getElementById('runBtn');
            const stopBtn = document.getElementById('stopBtn');

            if (data.total > 0) {
                const pct = Math.round((data.progress / data.total) * 100);
                fill.style.width = pct + '%';
                fill.innerText = pct + '%';
            } else {
                fill.style.width = '0%';
                fill.innerText = '0%';
            }

            if (data.running) {
                statusText.innerHTML = `🚀 运行中: ${data.message || ''}`;
                runBtn.disabled = true;
                stopBtn.disabled = false;
            } else {
                statusText.innerHTML = '⚪ 空闲';
                runBtn.disabled = false;
                stopBtn.disabled = true;
                // 停止后清除点击计数和定时器
                stopClickCount = 0;
                if (stopClickTimer) {
                    clearTimeout(stopClickTimer);
                    stopClickTimer = null;
                }
            }

            app.renderLogs(data.log || []);
        } catch (e) {
            console.error('状态更新失败', e);
        }
    }

    // ---------- 公开接口 ----------
    return {
        /**
         * 启动处理任务
         */
        startTask: async function() {
            const runBtn = document.getElementById('runBtn');
            const stopBtn = document.getElementById('stopBtn');
            runBtn.disabled = true;
            document.getElementById('statusText').innerHTML = '⏳ 启动中...';
            try {
                const resp = await fetch('/api/run', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'started') {
                    document.getElementById('statusText').innerHTML = '🚀 运行中';
                    stopBtn.disabled = false;
                    this.startStatusPolling();
                } else {
                    alert('启动失败: ' + (data.message || '未知错误'));
                    runBtn.disabled = false;
                    document.getElementById('statusText').innerHTML = '⚪ 空闲';
                }
            } catch (e) {
                alert('网络错误');
                runBtn.disabled = false;
            }
        },

        /**
         * 停止任务（支持双击强制重置）
         */
        stopTask: async function() {
            const statusText = document.getElementById('statusText');
            const runBtn = document.getElementById('runBtn');
            const stopBtn = document.getElementById('stopBtn');

            // 检测双击
            stopClickCount++;
            if (stopClickTimer) {
                clearTimeout(stopClickTimer);
            }

            if (stopClickCount >= 2) {
                // 双击：强制重置
                stopClickCount = 0;
                stopClickTimer = null;

                stopBtn.disabled = true;
                statusText.innerHTML = '⏳ 强制重置中...';

                try {
                    const resp = await fetch('/api/stop?force=1', { method: 'POST' });
                    const data = await resp.json();
                    if (data.status === 'reset') {
                        app.showToast('任务状态已强制重置', 'warning');
                        statusText.innerHTML = '⚪ 空闲';
                        runBtn.disabled = false;
                        stopBtn.disabled = true;
                        // 立即刷新状态
                        await _updateStatus();
                    } else {
                        app.showToast('重置失败', 'error');
                        stopBtn.disabled = false;
                    }
                } catch (e) {
                    app.showToast('网络错误', 'error');
                    stopBtn.disabled = false;
                }
                return;
            }

            // 单击：正常停止，设置定时器等待第二次点击
            stopClickTimer = setTimeout(() => {
                stopClickCount = 0;
                stopClickTimer = null;
            }, 500);  // 500ms 内双击有效

            // 如果任务不在运行中，提示并重置
            if (!isTaskRunning()) {
                app.showToast('当前没有运行中的任务', 'info');
                stopBtn.disabled = true;
                return;
            }

            stopBtn.disabled = true;
            statusText.innerHTML = '⏳ 正在停止...';

            try {
                const resp = await fetch('/api/stop', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'stopping') {
                    app.showToast('正在停止任务...', 'info');
                    // 停止按钮保持禁用，等待任务自然结束
                } else {
                    alert('停止失败: ' + (data.message || '未知错误'));
                    stopBtn.disabled = false;
                    statusText.innerHTML = '⚪ 空闲';
                }
            } catch (e) {
                alert('网络错误');
                stopBtn.disabled = false;
            }
        },

        /**
         * 更新状态（供外部调用）
         */
        updateStatus: _updateStatus,

        /**
         * 开始轮询状态
         */
        startStatusPolling: function() {
            if (app.statusInterval) clearInterval(app.statusInterval);
            app.statusInterval = setInterval(_updateStatus, 1000);
        },

        /**
         * 刷新状态和配置（供按钮调用）
         */
        refreshStatus: async function() {
            await _updateStatus();
            if (typeof App.Config !== 'undefined') await App.Config.loadConfig();
        },

        /**
         * 在新窗口查看完整日志
         */
        viewFullLog: async function() {
            const resp = await fetch('/api/log');
            const data = await resp.json();
            const win = window.open("", "Log", "width=900,height=600");
            win.document.write(`<pre style="background:#1a1e2b;color:#e3e8f0;padding:20px;white-space:pre-wrap;">${app.escapeHtml(data.log)}</pre>`);
        }
    };

    // 辅助函数：检查任务是否运行中（用于前端判断）
    function isTaskRunning() {
        const statusText = document.getElementById('statusText');
        return statusText && statusText.innerHTML.includes('运行中');
    }
})(window.App);
