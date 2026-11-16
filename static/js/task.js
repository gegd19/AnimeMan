/**
 * 任务控制模块
 * 负责启动/停止任务，轮询状态，显示日志
 * 停止请求后继续轮询，直到工作线程退出
 */
window.App = window.App || {};
App.Task = (function(app) {
    'use strict';

    let currentTask = {running:false, status:'idle', task_id:null};

    // ---------- 私有函数 ----------
    async function _updateStatus() {
        try {
            const resp = await app.fetch('/api/status');
            const data = await resp.json();
            if (!resp.ok) throw new Error(data.message || '状态请求失败');
            currentTask = data;
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

            runBtn.disabled = Boolean(data.running);
            stopBtn.disabled = !data.running || data.status === 'stopping';
            const labels = {idle:'空闲', running:'运行中', stopping:'正在停止，等待工作线程退出',
                            completed:'已完成', failed:'失败', cancelled:'已取消'};
            const result = data.result || {};
            const counts = typeof result.success === 'number' ? ` 成功 ${result.success}，失败 ${result.failed || 0}` : '';
            const text = `${labels[data.status] || (data.running ? '运行中' : '空闲')}${counts} ${data.message || ''}`;
            // 文字不变时不重写节点，避免读屏软件每秒重复播报。
            if (statusText.textContent !== text) statusText.textContent = text;

            app.renderLogs(data.log || []);
            if (typeof app.onTaskStatus === 'function') app.onTaskStatus(data);
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
            document.getElementById('statusText').textContent = '启动中...';
            try {
                const resp = await app.fetch('/api/run', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'started') {
                    document.getElementById('statusText').textContent = '运行中';
                    currentTask = {running:true, status:'running', task_id:data.task_id};
                    stopBtn.disabled = false;
                    if (typeof app.onTaskStatus === 'function') app.onTaskStatus(currentTask);
                    this.startStatusPolling();
                } else {
                    app.showToast('启动失败：' + (data.message || '未知错误'), 'error');
                    await _updateStatus();
                }
            } catch (e) {
                // App.fetch 已经给出具体原因；这里只恢复按钮和状态。
                await _updateStatus();
            }
        },

        /** 请求停止；线程退出前不解锁运行按钮。 */
        stopTask: async function() {
            if (!currentTask.running || currentTask.status === 'stopping') return;
            const identity = currentTask.task_id;
            currentTask.status = 'stopping';
            document.getElementById('runBtn').disabled = true;
            document.getElementById('stopBtn').disabled = true;
            document.getElementById('statusText').textContent = '正在停止，等待工作线程退出...';
            if (typeof app.onTaskStatus === 'function') app.onTaskStatus(currentTask);
            try {
                const suffix = identity ? '?task_id=' + encodeURIComponent(identity) : '';
                const resp = await app.fetch('/api/stop' + suffix, {method:'POST'});
                const data = await resp.json();
                if (!resp.ok) app.showToast(data.message || '停止请求失败', 'error');
                await _updateStatus();
            } catch (e) {
                app.showToast('停止请求状态未知，请刷新状态', 'error');
            }
            this.startStatusPolling();
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
            const resp = await app.fetch('/api/log');
            const data = await resp.json();
            const win = window.open("", "Log", "width=900,height=600");
            if (!win) return app.showToast('请允许弹出日志窗口', 'warning');
            const pre = win.document.createElement('pre');
            pre.style.cssText = 'background:#1a1e2b;color:#e3e8f0;padding:20px;white-space:pre-wrap;';
            pre.textContent = data.log;
            win.document.body.replaceChildren(pre);
        }
    };

})(window.App);
