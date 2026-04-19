/**
 * 手动修正模态框模块
 * 用于手动指定 TMDB ID 并重新处理文件
 */
window.App = window.App || {};
App.Correction = (function(app) {
    'use strict';

    const modalId = 'correctionModal';
    const searchBtnId = 'correctionSearchBtn';

    function _closeModal() {
        document.getElementById(modalId).style.display = 'none';
    }

    return {
        openCorrectionModal: function(srcPath, fileName) {
            app.currentCorrectionPath = srcPath;
            document.getElementById('correctionSrcPath').value = srcPath;

            // 提取源文件名（路径最后一部分）
            const srcFileName = srcPath.split(/[\\/]/).pop();

            // 显示文件名
            document.getElementById('correctionFileName').innerHTML = `${app.escapeHtml(fileName)} <span style="color:#6c757d; font-weight:normal;">(源文件: ${app.escapeHtml(srcFileName)})</span>`;

            // 解析目录层级并显示位置
            const pathParts = srcPath.replace(/\\/g, '/').split('/');
            const fileOnly = pathParts.pop();           // 文件名
            const parentDir = pathParts.pop() || '';    // 父目录
            const grandparentDir = pathParts.pop() || ''; // 祖父目录

            let locationText = '';
            if (grandparentDir) {
                locationText = `${grandparentDir} / ${parentDir} / ${fileOnly}`;
            } else if (parentDir) {
                locationText = `${parentDir} / ${fileOnly}`;
            } else {
                locationText = fileOnly;
            }
            document.getElementById('correctionFileLocation').textContent = locationText;

            // 重置搜索相关
            document.getElementById('tmdbSearchInput').value = '';
            document.getElementById('tmdbResultsBody').innerHTML = '<tr><td colspan="5" style="text-align:center;">输入关键词搜索</td></tr>';
            document.getElementById('selectedTmdbInfo').style.display = 'none';
            app.selectedTmdbId = null;
            document.getElementById(modalId).style.display = 'block';
        },

        closeCorrectionModal: _closeModal,

        searchTmdbForCorrection: async function() {
            const query = document.getElementById('tmdbSearchInput').value.trim();
            const mediaType = document.getElementById('tmdbSearchType').value;
            const searchBtn = document.getElementById(searchBtnId);

            if (!query) {
                app.showToast('请输入搜索关键词', 'warning');
                return;
            }

            const originalText = searchBtn.textContent;
            searchBtn.disabled = true;
            searchBtn.textContent = '搜索中...';

            const tbody = document.getElementById('tmdbResultsBody');
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">🔍 正在搜索 TMDB...</td></tr>';

            const controller = new AbortController();
            const timeoutId = setTimeout(() => controller.abort(), 25000);

            try {
                const resp = await fetch(`/api/tmdb/search_proxy?query=${encodeURIComponent(query)}&media_type=${mediaType}`, {
                    signal: controller.signal
                });
                clearTimeout(timeoutId);

                if (!resp.ok) {
                    const errorText = await resp.text();
                    throw new Error(`HTTP ${resp.status}: ${errorText}`);
                }

                const data = await resp.json();
                if (data.error) {
                    throw new Error(data.error);
                }

                if (!data.results || data.results.length === 0) {
                    tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">❌ 无搜索结果</td></tr>';
                    app.showToast(`未找到与 "${query}" 相关的${mediaType === 'tv' ? '剧集' : '电影'}`, 'warning');
                    return;
                }

                let html = '';
                data.results.forEach(item => {
                    const title = app.escapeHtml(item.title);
                    const year = item.year || '';

                    const posterHtml = item.poster_url
                        ? `<img src="${item.poster_url}" style="width:45px; height:68px; object-fit:cover; border-radius:6px;">`
                        : '<div style="width:45px;height:68px;background:#e9ecef;border-radius:6px;display:flex;align-items:center;justify-content:center;color:#6c757d;font-size:10px;">无图</div>';

                    let seasonInfo = '';
                    if (item.media_type === 'tv' && item.seasons_detail && item.seasons_detail.length > 0) {
                        const parts = item.seasons_detail.map(s => `S${s.season_number}(${s.episode_count}集)`);
                        seasonInfo = parts.join(', ');
                        const fullNames = item.seasons_detail.map(s => `S${s.season_number}: ${s.name} (${s.episode_count}集)`).join('\n');
                        seasonInfo = `<span title="${app.escapeHtml(fullNames)}" style="cursor:help; border-bottom:1px dashed #6c757d;">${app.escapeHtml(seasonInfo)}</span>`;
                    } else {
                        seasonInfo = '-';
                    }

                    html += `<tr>
                        <td style="padding:4px;">${posterHtml}</td>
                        <td>${title}</td>
                        <td>${year}</td>
                        <td>${seasonInfo}</td>
                        <td><button onclick="App.Correction.selectTmdbForCorrection(${item.id}, '${title.replace(/'/g, "\\'")}', '${mediaType}')" class="secondary">选择</button></td>
                    </tr>`;
                });
                tbody.innerHTML = html;

                const thead = document.querySelector('#tmdbSearchResults thead');
                if (thead) {
                    thead.innerHTML = '<tr><th>海报</th><th>标题</th><th>年份</th><th>季集数</th><th>操作</th></tr>';
                }

                app.showToast(`✅ 找到 ${data.results.length} 个结果`, 'success');

            } catch (e) {
                clearTimeout(timeoutId);
                let errorMsg = '搜索失败';
                if (e.name === 'AbortError') {
                    errorMsg = '请求超时，请检查网络后重试';
                } else {
                    errorMsg = e.message || '网络错误';
                }
                tbody.innerHTML = `<tr><td colspan="5" style="text-align:center; color:#dc3545;">❌ ${app.escapeHtml(errorMsg)}</td></tr>`;
                app.showToast(errorMsg, 'error');
            } finally {
                searchBtn.disabled = false;
                searchBtn.textContent = originalText;
            }
        },

        selectTmdbForCorrection: function(id, title, mediaType) {
            app.selectedTmdbId = id;
            app.selectedMediaType = mediaType;
            document.getElementById('selectedTmdbTitle').innerText = title;
            document.getElementById('selectedTmdbId').innerText = id;
            document.getElementById('selectedTmdbInfo').style.display = 'block';
            document.getElementById('correctionSeason').disabled = (mediaType === 'movie');
            document.getElementById('correctionEpisode').disabled = (mediaType === 'movie');
            app.showToast(`已选择: ${title}`, 'info', 1500);
        },

        executeCorrection: async function() {
            if (!app.selectedTmdbId) {
                app.showToast('请先搜索并选择一个 TMDB 条目', 'warning');
                return;
            }
            const srcPath = app.currentCorrectionPath;
            const season = parseInt(document.getElementById('correctionSeason').value) || 1;
            const episode = parseInt(document.getElementById('correctionEpisode').value) || 1;
            const payload = {
                src_path: srcPath,
                tmdb_id: app.selectedTmdbId,
                media_type: app.selectedMediaType,
                season: app.selectedMediaType === 'tv' ? season : null,
                episode: app.selectedMediaType === 'tv' ? episode : null
            };
            const confirmBtn = document.querySelector(`#${modalId} .success`);
            const originalText = confirmBtn.textContent;
            confirmBtn.disabled = true;
            confirmBtn.textContent = '⏳ 处理中...';
            try {
                const resp = await fetch('/api/failed_cache/correct', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast('✅ 修正成功！文件已重新处理。', 'success');
                    _closeModal();
                    if (typeof App.FailedCache !== 'undefined') App.FailedCache.loadFailedCache();
                    if (typeof App.History !== 'undefined') App.History.loadProcessedHistory();
                    if (typeof App.MediaManager !== 'undefined') App.MediaManager.refreshLibrary();
                } else {
                    app.showToast('❌ 修正失败：' + (data.message || '未知错误'), 'error');
                }
            } catch (e) {
                app.showToast('请求失败：' + e.message, 'error');
            } finally {
                confirmBtn.disabled = false;
                confirmBtn.textContent = originalText;
            }
        }
    };
})(window.App);
