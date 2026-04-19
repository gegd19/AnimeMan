/**
 * 字幕智能匹配中心模块（完整版）
 * 功能：双模式匹配、AI分组优化、多级目录显示、分页、已处理字幕展示、按匹配度排序
 */
window.App = window.App || {};
App.SubtitleCenter = (function(app) {
    'use strict';

    console.log('✅ subtitleCenter.js 完整版已加载');

    // DOM 元素
    const thresholdInput = document.getElementById('matchThresholdInput');
    const thresholdSpan = document.getElementById('thresholdValue');
    if (thresholdInput) {
        thresholdInput.addEventListener('input', e => thresholdSpan.innerText = e.target.value);
    }

    // 状态变量
    let selectedShowInfo = null;          // AI 匹配用的目标剧集
    let aiMatchResults = [];
    let forceMatchTarget = null;          // 强制匹配目标
    let selectedIndices = new Set();      // 全局勾选索引

    // 分页与排序
    const PAGE_SIZE = 30;
    let currentPage = 1;
    let currentSortMode = 'name';          // 'name' 或 'confidence'

    // 中文数字映射（用于提取季号）
    const chineseNumMap = {
        '一':1,'二':2,'三':3,'四':4,'五':5,'六':6,'七':7,'八':8,'九':9,'十':10,
        '十一':11,'十二':12,'十三':13,'十四':14,'十五':15,'十六':16,'十七':17,'十八':18,'十九':19,'二十':20
    };

    // ---------- 辅助函数 ----------
    function cleanTitle(title) {
        if (!title) return '';
        return title.replace(/\s*\(\)\s*$/, '').trim();
    }

    function getDirectoryDisplay(sub) {
        const parent = sub.parent_dir || '';
        const grandparent = sub.grandparent_dir || '';
        if (grandparent && grandparent !== parent) return `${grandparent}/${parent}`;
        if (parent) return parent;
        return '';
    }

    function extractSeriesTitle(filename) {
        let base = filename.replace(/\.[^/.]+$/, '');
        base = base.replace(/\.(srd|synced|chs|cht|eng|jpn|sc|tc|gb|big5|danmu)/gi, '');
        base = base.replace(/[Ss]\d{1,2}[Ee]\d{1,3}/g, '');
        base = base.replace(/第\s*\d+\s*[集話话]/g, '');
        base = base.replace(/[-_\s]+\d{1,3}(?:\.|$)/g, '');
        base = base.replace(/[【】\[\]\(\)]/g, ' ');
        base = base.replace(/\s*-\s*$/, '');
        base = base.replace(/\s+/g, ' ').trim();
        return base || filename;
    }

    function extractSeasonNumber(filename) {
        const match = filename.match(/[Ss](\d{1,2})/);
        return match ? parseInt(match[1]) : 1;
    }

    function normalizeFileNameForSort(filename) {
        let normalized = filename.replace(/\.[^/.]+$/, '');
        normalized = normalized.replace(/\.(srd|synced|chs|cht|eng|jpn|sc|tc|gb|big5|zh-Hans|zh-Hant|danmu)/gi, '');
        normalized = normalized.replace(/\.+/g, ' ').trim();
        return normalized || filename;
    }

    function extractEpisodeNumber(filename) {
        let match = filename.match(/[Ss]\d{1,2}[Ee](\d{1,3})/);
        if (match) return parseInt(match[1]);
        match = filename.match(/第\s*(\d{1,3})\s*[集話话]/);
        if (match) return parseInt(match[1]);
        const parts = filename.split(/[-_.\s]+/);
        for (const part of parts) {
            if (/^[\u4e00-\u9fa5]+$/.test(part)) continue;
            if (/^[a-zA-Z]+$/.test(part)) continue;
            if (/^(19|20)\d{2}$/.test(part)) continue;
            const numMatch = part.match(/^(\d{1,3})$/);
            if (numMatch) {
                const num = parseInt(numMatch[1]);
                if (num >= 1 && num <= 999) return num;
            }
        }
        const normalized = normalizeFileNameForSort(filename);
        match = normalized.match(/[^\d](\d{1,3})$/);
        if (match) {
            let num = parseInt(match[1]);
            if (num < 1900 || num > 2100) return num;
        }
        match = normalized.match(/[-_\s]+(\d{1,3})(?:\.|$)/);
        if (match) return parseInt(match[1]);
        return null;
    }

    function getLangPriority(filename) {
        const lower = filename.toLowerCase();
        if (lower.includes('zh-hans') || lower.includes('.chs') || lower.includes('简体')) return 0;
        if (lower.includes('zh-hant') || lower.includes('.cht') || lower.includes('繁体')) return 1;
        return 2;
    }

    function sortByName(a, b) {
        const nameA = a.subtitle?.name || a.name || '';
        const nameB = b.subtitle?.name || b.name || '';
        const titleA = extractSeriesTitle(nameA);
        const titleB = extractSeriesTitle(nameB);
        const titleCompare = titleA.localeCompare(titleB, 'zh-CN');
        if (titleCompare !== 0) return titleCompare;
        const seasonA = extractSeasonNumber(nameA);
        const seasonB = extractSeasonNumber(nameB);
        if (seasonA !== seasonB) return seasonA - seasonB;
        const epA = extractEpisodeNumber(nameA) ?? 9999;
        const epB = extractEpisodeNumber(nameB) ?? 9999;
        if (epA !== epB) return epA - epB;
        const langA = getLangPriority(nameA);
        const langB = getLangPriority(nameB);
        if (langA !== langB) return langA - langB;
        return nameA.localeCompare(nameB);
    }

    function sortByConfidence(a, b) {
        const scoreA = a.best_match ? a.best_match.score : -1;
        const scoreB = b.best_match ? b.best_match.score : -1;
        return scoreB - scoreA; // 降序，高分在前
    }

    function sortMatchResults(mode) {
        if (!app.matchResults || !app.matchResults.length) return;
        if (mode === 'confidence') {
            app.matchResults.sort(sortByConfidence);
        } else {
            app.matchResults.sort(sortByName);
        }
    }

    // 用于 AI 分组的标题提取
    function extractBaseTitleAndSeason(filename) {
        let base = filename.replace(/\.[^/.]+$/, '');
        let season = 1;
        const seasonMatch = base.match(/[Ss](\d{1,2})(?:[Ee]|$)/);
        if (seasonMatch) {
            season = parseInt(seasonMatch[1]);
        } else {
            const cnSeasonMatch = base.match(/第\s*([一二三四五六七八九十\d]+)\s*季/);
            if (cnSeasonMatch) {
                const s = cnSeasonMatch[1];
                if (/^\d+$/.test(s)) season = parseInt(s);
                else season = chineseNumMap[s] || 1;
            }
        }
        base = base.replace(/[Ss]\d{1,2}[Ee]\d{1,3}/g, '');
        base = base.replace(/第\s*\d+\s*[集話话]/g, '');
        base = base.replace(/[-_\s]+\d{1,3}(?:\.|$)/g, '');
        base = base.replace(/[\[\]\(\)【】]/g, ' ');
        base = base.replace(/\.(chs|cht|eng|jpn|sc|tc|gb|big5|srd|synced|danmu)/gi, '');
        base = base.replace(/\s+/g, ' ').trim();
        return { baseTitle: base, season };
    }

    function findEpisodeInSeason(showInfo, season, episode) {
        const seasons = showInfo.seasons || {};
        const seasonStr = String(season);
        const seasonData = seasons[seasonStr];
        if (!seasonData) return null;
        const episodes = seasonData.episodes || [];
        return episodes.find(ep => ep.episode === episode) || null;
    }

    function buildMatchFromEpisode(episodeData, showInfo, season) {
        return {
            media: {
                media_type: 'tv',
                title: showInfo.title,
                year: showInfo.year,
                season: season,
                episode: episodeData.episode,
                target_path: episodeData.target_path,
                target_dir: episodeData.target_dir,
                cache_key: episodeData.cache_key,
                tmdb_id: showInfo.tmdb_id,
            },
            score: 100,
            match_type: 'force_season_episode'
        };
    }

    function buildMovieMatch(movie) {
        return {
            media: {
                media_type: 'movie',
                title: movie.title,
                year: movie.year,
                target_path: movie.target_path,
                target_dir: movie.target_dir,
                cache_key: movie.cache_key,
                tmdb_id: movie.tmdb_id,
            },
            score: 100,
            match_type: 'force_movie'
        };
    }

    // ---------- 分页与UI更新 ----------
    function renderPagination(totalItems) {
        const container = document.getElementById('subtitlePagination');
        if (!container) return;
        const totalPages = Math.ceil(totalItems / PAGE_SIZE);
        if (totalPages <= 1) { container.innerHTML = ''; return; }
        let html = '<div style="display:flex; align-items:center; justify-content:center; gap:8px; margin-top:12px; flex-wrap:wrap;">';
        html += `<button onclick="App.SubtitleCenter.goToPage(1)" ${currentPage === 1 ? 'disabled' : ''} style="padding:4px 10px;">⏮️</button>`;
        html += `<button onclick="App.SubtitleCenter.goToPage(${currentPage - 1})" ${currentPage === 1 ? 'disabled' : ''} style="padding:4px 10px;">◀</button>`;
        html += `<span style="padding:4px 12px; background:#f0f4ff; border-radius:6px;">第 ${currentPage} / ${totalPages} 页</span>`;
        html += `<button onclick="App.SubtitleCenter.goToPage(${currentPage + 1})" ${currentPage === totalPages ? 'disabled' : ''} style="padding:4px 10px;">▶</button>`;
        html += `<button onclick="App.SubtitleCenter.goToPage(${totalPages})" ${currentPage === totalPages ? 'disabled' : ''} style="padding:4px 10px;">⏭️</button>`;
        html += '</div>';
        container.innerHTML = html;
    }

    function updateSelectionUI(total, selected) {
        const countSpan = document.getElementById('subtitleSelectedCount');
        if (countSpan) countSpan.textContent = selected;
    }

    // ---------- 核心渲染 ----------
    function renderMatchTable() {
        // 应用当前排序模式
        sortMatchResults(currentSortMode);

        const tbody = document.getElementById('subtitleMatchBody');
        if (!tbody) return;
        tbody.innerHTML = '';
        if (!app.matchResults || !app.matchResults.length) {
            tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">暂无数据，请先扫描字幕</td></tr>';
            updateSelectionUI(0, 0);
            renderPagination(0);
            return;
        }

        const totalItems = app.matchResults.length;
        const startIdx = (currentPage - 1) * PAGE_SIZE;
        const endIdx = Math.min(startIdx + PAGE_SIZE, totalItems);
        const pageItems = app.matchResults.slice(startIdx, endIdx);

        let pageSelectedCount = 0;
        pageItems.forEach((_, idx) => { if (selectedIndices.has(startIdx + idx)) pageSelectedCount++; });

        const selectAllCheck = document.getElementById('subtitleSelectAll');
        if (selectAllCheck) {
            selectAllCheck.checked = (pageSelectedCount === pageItems.length && pageItems.length > 0);
            selectAllCheck.indeterminate = (pageSelectedCount > 0 && pageSelectedCount < pageItems.length);
        }

        pageItems.forEach((item, pageIdx) => {
            const globalIdx = startIdx + pageIdx;
            const sub = item.subtitle;
            const best = item.best_match;
            const processed = sub.processed_info;
            const tr = document.createElement('tr');

            // 复选框
            const tdCheck = document.createElement('td');
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.dataset.index = globalIdx;
            checkbox.checked = selectedIndices.has(globalIdx);
            checkbox.addEventListener('change', (e) => {
                if (e.target.checked) selectedIndices.add(globalIdx);
                else selectedIndices.delete(globalIdx);
                renderMatchTable();
            });
            tdCheck.appendChild(checkbox);
            tr.appendChild(tdCheck);

            // 文件名 + 目录
            const tdName = document.createElement('td');
            tdName.title = sub.path;
            const dirDisplay = getDirectoryDisplay(sub);
            tdName.textContent = dirDisplay ? `${sub.name} (${dirDisplay})` : sub.name;
            tr.appendChild(tdName);

            // 匹配结果
            const tdMatch = document.createElement('td');
            if (best) {
                const m = best.media;
                const display = m.media_type === 'tv'
                    ? `${m.title} S${(m.season || '').toString().padStart(2, '0')}E${(m.episode || '').toString().padStart(2, '0')}`
                    : `${m.title} (${m.year || ''})`;
                tdMatch.textContent = display;
            } else if (processed && processed.target_exists) {
                const info = processed;
                const display = info.media_type === 'tv'
                    ? `${info.title} S${(info.season || '').toString().padStart(2, '0')}E${(info.episode || '').toString().padStart(2, '0')}`
                    : `${info.title} (${info.year || ''})`;
                tdMatch.innerHTML = `<span style="color:#28a745;">✅ 已匹配</span><br><span style="font-size:12px;">${app.escapeHtml(display)}</span>`;
            } else {
                tdMatch.textContent = '无匹配';
                tdMatch.style.color = '#dc3545';
            }
            tr.appendChild(tdMatch);

            // 置信度
            const tdScore = document.createElement('td');
            tdScore.textContent = best ? `${best.score}%` : (processed ? '—' : '-');
            tr.appendChild(tdScore);

            // 操作
            const tdAction = document.createElement('td');
            const hasTarget = best || (processed && processed.target_exists);
            if (hasTarget) {
                const execBtn = document.createElement('button');
                execBtn.textContent = '执行';
                execBtn.className = 'success';
                execBtn.style.padding = '4px 10px';
                execBtn.onclick = () => executeSingle(globalIdx, best, processed);
                tdAction.appendChild(execBtn);
            }
            const manSelectBtn = document.createElement('button');
            manSelectBtn.textContent = '📂 自由选择';
            manSelectBtn.className = 'secondary';
            manSelectBtn.style.padding = '4px 10px';
            manSelectBtn.style.marginLeft = '5px';
            manSelectBtn.onclick = () => {
                if (typeof App.MediaLibrary !== 'undefined') App.MediaLibrary.showManualSelect(globalIdx);
            };
            tdAction.appendChild(manSelectBtn);
            tr.appendChild(tdAction);

            tbody.appendChild(tr);
        });

        // 按钮状态
        const executeAllBtn = document.getElementById('executeAllBtn');
        if (executeAllBtn) {
            const has = app.matchResults.some((item, idx) => {
                const sub = item.subtitle;
                return (item.best_match || (sub.processed_info && sub.processed_info.target_exists)) && selectedIndices.has(idx);
            });
            executeAllBtn.disabled = !has;
        }
        const forceMatchBtn = document.getElementById('forceMatchBtn');
        if (forceMatchBtn) forceMatchBtn.disabled = !(app.scannedSubtitles?.length && selectedIndices.size && forceMatchTarget);
        const autoMatchBtn = document.getElementById('matchBtn');
        if (autoMatchBtn) autoMatchBtn.disabled = !(app.scannedSubtitles?.length);
        const aiMatchBtn = document.getElementById('aiMatchBtn');
        if (aiMatchBtn) aiMatchBtn.disabled = (selectedIndices.size === 0);

        updateSelectionUI(totalItems, selectedIndices.size);
        renderPagination(totalItems);
    }

    // ---------- 执行单条 ----------
    async function executeSingle(idx, match, processedInfo) {
        let targetMedia;
        if (match) {
            targetMedia = match.media;
        } else if (processedInfo) {
            targetMedia = {
                media_type: processedInfo.media_type,
                title: processedInfo.title,
                year: processedInfo.year,
                season: processedInfo.season,
                episode: processedInfo.episode,
                target_path: processedInfo.target,
                target_dir: processedInfo.target.substring(0, processedInfo.target.lastIndexOf('/'))
            };
        } else return;

        const item = {
            subtitle_path: app.matchResults[idx].subtitle.path,
            target_media: targetMedia,
            auto_sync: document.getElementById('subtitleCenterAutoSyncCheck').checked
        };
        const resp = await fetch('/api/subtitle/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items: [item] })
        });
        const data = await resp.json();
        app.showToast(`执行完成: ${data.processed}/${data.total}`, 'success');
        await scanSubtitleFolder(); // 刷新列表
    }

    // 扫描函数（提取以便复用）
    async function scanSubtitleFolder() {
        const folder = document.getElementById('subSourceFolderInput').value.trim();
        if (!folder) return app.showToast('请填写字幕文件夹路径', 'warning');
        const resp = await fetch('/api/subtitle/scan', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ folder })
        });
        const data = await resp.json();
        if (data.subtitles) {
            data.subtitles.sort(sortByName);
            app.scannedSubtitles = data.subtitles;
            selectedIndices.clear();
            app.matchResults = data.subtitles.map(sub => ({ subtitle: sub, candidates: [], best_match: null }));
            currentPage = 1;
            renderMatchTable();
            app.showToast(`扫描完成，发现 ${data.subtitles.length} 个字幕文件`, 'success');
        } else {
            app.showToast('扫描失败: ' + (data.error || '未知错误'), 'error');
        }
    }

    // ---------- 自动匹配 ----------
    async function autoMatchSubtitles() {
        if (!app.scannedSubtitles?.length) return app.showToast('请先扫描字幕', 'warning');
        const threshold = parseInt(thresholdInput.value) || 75;
        const btn = document.getElementById('matchBtn');
        const original = btn.innerText;
        btn.disabled = true;
        btn.innerText = '匹配中...';
        const tbody = document.getElementById('subtitleMatchBody');
        tbody.innerHTML = '<tr><td colspan="5" style="text-align:center;">🔄 正在智能匹配字幕...</td></tr>';
        try {
            const resp = await fetch('/api/subtitle/match', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ subtitles: app.scannedSubtitles, threshold })
            });
            const data = await resp.json();
            if (data.results) data.results.sort(sortByName);
            app.matchResults = data.results;
            selectedIndices.clear();
            app.matchResults.forEach((item, idx) => { if (item.best_match) selectedIndices.add(idx); });
            currentPage = 1;
            renderMatchTable();
            const matched = app.matchResults.filter(i => i.best_match).length;
            app.showToast(`✅ 匹配完成！共 ${app.matchResults.length} 个，${matched} 个找到匹配`, 'success');
        } catch (e) {
            tbody.innerHTML = '<tr><td colspan="5" style="color:#dc3545;">匹配失败，请重试</td></tr>';
            app.showToast('匹配失败: ' + e.message, 'error');
        } finally {
            btn.disabled = false;
            btn.innerText = original;
        }
    }

    // ---------- 强制匹配 ----------
    function forceMatchToShow() {
        if (!app.matchResults?.length) return app.showToast('请先扫描字幕', 'warning');
        if (!forceMatchTarget) return app.showToast('请先选择目标媒体', 'warning');
        if (!selectedIndices.size) return app.showToast('请至少勾选一个字幕', 'warning');
        let matched = 0;
        if (forceMatchTarget.type === 'movie') {
            const movie = forceMatchTarget.data;
            for (let idx of selectedIndices) {
                app.matchResults[idx].best_match = buildMovieMatch(movie);
                app.matchResults[idx].candidates = [app.matchResults[idx].best_match];
                matched++;
            }
        } else {
            const show = forceMatchTarget.data.showInfo;
            const targetSeason = forceMatchTarget.data.selectedSeason;
            for (let idx of selectedIndices) {
                const ep = extractEpisodeNumber(app.matchResults[idx].subtitle.name);
                if (ep !== null) {
                    const epData = findEpisodeInSeason(show, targetSeason, ep);
                    if (epData) {
                        app.matchResults[idx].best_match = buildMatchFromEpisode(epData, show, targetSeason);
                        app.matchResults[idx].candidates = [app.matchResults[idx].best_match];
                        matched++;
                    } else { app.matchResults[idx].best_match = null; app.matchResults[idx].candidates = []; }
                } else { app.matchResults[idx].best_match = null; app.matchResults[idx].candidates = []; }
            }
        }
        app.matchResults.sort(sortByName);
        renderMatchTable();
        app.showToast(`强制匹配完成：${matched}/${selectedIndices.size} 个成功`, matched ? 'success' : 'warning');
    }

    // ---------- 全部执行 ----------
    async function executeAllMatches() {
        const items = [];
        const autoSync = document.getElementById('subtitleCenterAutoSyncCheck').checked;
        for (let idx of selectedIndices) {
            const item = app.matchResults[idx];
            const sub = item.subtitle;
            let target = null;
            if (item.best_match) target = item.best_match.media;
            else if (sub.processed_info && sub.processed_info.target_exists) {
                const p = sub.processed_info;
                target = {
                    media_type: p.media_type,
                    title: p.title,
                    year: p.year,
                    season: p.season,
                    episode: p.episode,
                    target_path: p.target,
                    target_dir: p.target.substring(0, p.target.lastIndexOf('/'))
                };
            }
            if (target) {
                items.push({ subtitle_path: sub.path, target_media: target, auto_sync: autoSync });
            }
        }
        if (!items.length) return app.showToast('没有可执行的项目', 'warning');
        const resp = await fetch('/api/subtitle/execute', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ items })
        });
        const data = await resp.json();
        app.showToast(`批量执行完成: ${data.processed}/${data.total}`, 'success');
        await scanSubtitleFolder();
    }

    // ---------- AI 智能匹配（分组优化）----------
    async function aiMatchToShow() {
        if (!app.matchResults?.length) return app.showToast('请先扫描字幕', 'warning');
        if (!selectedIndices.size) return app.showToast('请至少勾选一个字幕', 'warning');
        const selectedFiles = [];
        for (let idx of selectedIndices) selectedFiles.push(app.matchResults[idx].subtitle);
        if (selectedFiles.length > 30 && !confirm(`您选择了 ${selectedFiles.length} 个文件，AI 匹配可能需要较长时间，确定继续吗？`)) return;

        const btn = document.getElementById('aiMatchBtn');
        const original = btn.textContent;
        btn.disabled = true;

        const groups = new Map();
        selectedFiles.forEach(sub => {
            const { baseTitle, season } = extractBaseTitleAndSeason(sub.name);
            const key = `${baseTitle}|S${season}`;
            if (!groups.has(key)) groups.set(key, { baseTitle, season, subs: [] });
            groups.get(key).subs.push(sub);
        });

        console.log(`📦 共 ${groups.size} 组`);
        let totalMatched = 0, processed = 0;

        for (const [key, group] of groups.entries()) {
            processed++;
            btn.textContent = `⏳ AI 识别中 (${processed}/${groups.size})`;
            let aiTitle = group.baseTitle;
            let aiSeason = group.season;
            const rep = group.subs[0];
            try {
                const aiResp = await fetch('/api/subtitle/ai_parse', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ files: [{ path: rep.path, name: rep.name, parent_dir: rep.parent_dir, grandparent_dir: rep.grandparent_dir }] })
                });
                const aiData = await aiResp.json();
                if (aiData.results?.length) {
                    const parsed = aiData.results[0];
                    aiTitle = parsed.title || group.baseTitle;
                    aiSeason = parsed.season || group.season;
                }
            } catch (e) { console.warn('AI 解析失败:', e); }

            for (const sub of group.subs) {
                try {
                    const matchResp = await fetch('/api/subtitle/match_single', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ subtitle: sub, threshold: 60, force_title: aiTitle })
                    });
                    const matchData = await matchResp.json();
                    let best = matchData.best_match;
                    if (best && best.media.media_type === 'tv' && best.media.season !== aiSeason) {
                        const seasonMatch = matchData.candidates?.find(c => c.media.media_type === 'tv' && c.media.season === aiSeason);
                        if (seasonMatch) best = seasonMatch;
                    }
                    const targetIdx = app.matchResults.findIndex(r => r.subtitle.path === sub.path);
                    if (targetIdx >= 0) {
                        app.matchResults[targetIdx].best_match = best;
                        app.matchResults[targetIdx].candidates = matchData.candidates || [];
                        if (best) totalMatched++;
                    }
                } catch (e) { console.error('匹配失败:', sub.name, e); }
            }
        }
        app.matchResults.sort(sortByName);
        renderMatchTable();
        btn.disabled = false;
        btn.textContent = original;
        app.showToast(`AI 匹配完成：${totalMatched}/${selectedFiles.length} 个成功`, 'success');
    }

    // ---------- 公开API ----------
    return {
        renderMatchTable,
        toggleSelectAllSubtitle: function(checked) {
            if (!app.matchResults) return;
            const startIdx = (currentPage - 1) * PAGE_SIZE;
            const endIdx = Math.min(startIdx + PAGE_SIZE, app.matchResults.length);
            for (let i = startIdx; i < endIdx; i++) {
                if (checked) selectedIndices.add(i);
                else selectedIndices.delete(i);
            }
            renderMatchTable();
        },
        clearAllSelections: function() { selectedIndices.clear(); renderMatchTable(); },
        goToPage: function(page) {
            const totalPages = Math.ceil(app.matchResults.length / PAGE_SIZE);
            if (page < 1) page = 1;
            if (page > totalPages) page = totalPages;
            currentPage = page;
            renderMatchTable();
        },
        setSortMode: function(mode) {
            currentSortMode = mode;
            currentPage = 1;
            renderMatchTable();
            // 更新下拉框选中状态（保持UI同步）
            const select = document.getElementById('subtitleSortSelect');
            if (select) select.value = mode;
        },
        selectForceMatchShow: function() {
            if (typeof App.MediaLibrary === 'undefined') { app.showToast('媒体库模块未加载', 'error'); return; }
            App.MediaLibrary.showTargetSelector((target) => {
                forceMatchTarget = target;
                const span = document.getElementById('forceMatchShowDisplay');
                if (span) {
                    if (target.type === 'movie') {
                        const m = target.data;
                        span.innerHTML = `🎬 ${app.escapeHtml(cleanTitle(m.title))}${m.year ? ' ('+m.year+')' : ''}`;
                    } else {
                        const show = target.data.showInfo;
                        const season = target.data.selectedSeason;
                        span.innerHTML = `📺 ${app.escapeHtml(cleanTitle(show.title))}${show.year ? ' ('+show.year+')' : ''} - 第 ${season} 季`;
                    }
                }
                app.showToast(`已选择${target.type==='movie'?'电影':'剧集'}`, 'success');
                renderMatchTable();
            });
        },
        scanSubtitleFolder: scanSubtitleFolder,
        autoMatchSubtitles: autoMatchSubtitles,
        forceMatchToShow: forceMatchToShow,
        executeAllMatches: executeAllMatches,
        selectTargetShow: function() {
            if (!app.scannedSubtitles?.length) return app.showToast('请先扫描字幕', 'warning');
            if (typeof App.MediaLibrary !== 'undefined') {
                App.MediaLibrary.showShowSelector((showInfo) => {
                    const clean = cleanTitle(showInfo.title || '');
                    selectedShowInfo = showInfo;
                    selectedShowInfo.title = clean;
                    document.getElementById('selectedShowDisplay').innerHTML = `📺 ${clean} (${showInfo.year||''})`;
                    app.showToast(`已选择剧集: ${clean}`, 'success');
                });
            } else app.showToast('媒体库模块未加载', 'error');
        },
        // AI 智能匹配
        aiMatchToShow: aiMatchToShow,
        applyAiMatches: async function() {
            const checkboxes = document.querySelectorAll('.ai-match-check:checked');
            if (!checkboxes.length) return app.showToast('请至少勾选一个文件', 'warning');

            const renames = [], items = [];
            const autoSync = document.getElementById('subtitleCenterAutoSyncCheck').checked;

            for (let cb of checkboxes) {
                const idx = parseInt(cb.dataset.index);
                const match = aiMatchResults[idx];
                if (!match?.path || !match.suggested_name) continue;

                const old = match.path;
                const newPath = old.substring(0, old.lastIndexOf('/') + 1) + match.suggested_name;
                renames.push({ old_path: old, new_path: newPath });

                const season = String(match.season || 1);
                const ep = match.episode;
                const seasons = selectedShowInfo?.seasons || {};
                const sData = seasons[season];
                if (!sData) continue;
                const targetEp = sData.episodes?.find(e => e.episode === ep);
                if (!targetEp) continue;

                items.push({
                    subtitle_path: newPath,
                    target_media: { target_path: targetEp.target_path, target_dir: targetEp.target_dir },
                    auto_sync: autoSync
                });
            }

            if (!renames.length) return app.showToast('无有效重命名项', 'error');

            const btn = document.getElementById('applyAiMatchBtn');
            const original = btn.textContent;
            btn.disabled = true;
            btn.textContent = '⏳ 处理中...';

            try {
                const r1 = await fetch('/api/subtitle/batch_rename', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ renames })
                });
                const d1 = await r1.json();
                if (d1.success === 0) return app.showToast('重命名失败', 'error');

                let msg = '';
                if (items.length) {
                    const r2 = await fetch('/api/subtitle/execute', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ items })
                    });
                    const d2 = await r2.json();
                    msg = `，移动成功 ${d2.processed}`;
                } else msg = '，但未找到对应视频';

                app.showToast(`入库完成：重命名成功 ${d1.success}${msg}`, 'success');
                await this.scanSubtitleFolder();
                aiMatchResults = [];
                renderAiMatchResults();
            } catch (e) {
                app.showToast('请求失败: ' + e.message, 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = original;
            }
        }
    };
})(window.App);
