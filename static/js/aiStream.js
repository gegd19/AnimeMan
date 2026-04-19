/**
 * AI 流式简介润色测试模块
 */
window.App = window.App || {};
App.AIStream = (function(app) {
    'use strict';

    return {
        startStreamEnhance: async function() {
            const title = document.getElementById('testTitle').value.trim();
            const plot = document.getElementById('testPlot').value.trim();
            if (!title || !plot) {
                app.showToast('请输入标题和简介', 'warning');
                return;
            }

            const aiConfig = {
                provider: document.getElementById('aiProviderSelect').value,
                api_key: document.getElementById('aiKeyInput').value,
                model: document.getElementById('aiModelInput').value,
                base_url: document.getElementById('aiBaseUrlInput').value,
                temperature: parseFloat(document.getElementById('plotTempInput').value) || 0.7,
                max_tokens: parseInt(document.getElementById('plotTokensInput').value) || 500
            };

            const outputDiv = document.getElementById('streamOutput');
            outputDiv.innerHTML = '';
            app.fullStreamResult = '';

            const btn = document.querySelector('#stream-card button.primary');
            if (btn) {
                btn.disabled = true;
                btn.textContent = '⏳ 生成中...';
            }

            try {
                const resp = await fetch('/api/ai/stream_enhance', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ title, original_plot: plot, ai_config: aiConfig })
                });

                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let buffer = '';

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split('\n');
                    buffer = lines.pop();
                    for (const line of lines) {
                        if (line.startsWith('data: ')) {
                            try {
                                const data = JSON.parse(line.slice(6));
                                if (data.content) {
                                    app.fullStreamResult += data.content;
                                    outputDiv.textContent = app.fullStreamResult;
                                }
                                if (data.error) {
                                    outputDiv.innerHTML = `<span style="color:#ff6b6b;">错误: ${data.error}</span>`;
                                    return;
                                }
                                if (data.done) break;
                            } catch (e) {}
                        }
                    }
                }
            } catch (e) {
                outputDiv.innerHTML = `<span style="color:#ff6b6b;">请求失败: ${e.message}</span>`;
            } finally {
                if (btn) {
                    btn.disabled = false;
                    btn.textContent = '🤖 开始流式生成';
                }
            }
        },

        copyStreamResult: function() {
            if (!app.fullStreamResult) {
                app.showToast('没有可复制的内容', 'warning');
                return;
            }
            navigator.clipboard?.writeText(app.fullStreamResult).then(() => {
                app.showToast('已复制到剪贴板', 'success');
            }).catch(() => {
                // fallback
                const textarea = document.createElement('textarea');
                textarea.value = app.fullStreamResult;
                document.body.appendChild(textarea);
                textarea.select();
                document.execCommand('copy');
                document.body.removeChild(textarea);
                app.showToast('已复制到剪贴板', 'success');
            });
        }
    };
})(window.App);
