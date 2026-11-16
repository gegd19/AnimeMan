/**
 * 媒体库管理模块（性能优化版 + 影剧分离）
 * - 懒加载集数详情
 * - 电影/剧集独立无限滚动（每批 30 个）
 * - 视图切换（全部 / 仅电影 / 仅剧集）
 * - 完整的批量修正、批量删除功能
 */
window.App = window.App || {};
App.MediaManager = (function(app) {
    'use strict';

    console.log('✅ MediaManager 模块已加载（影剧分离 + 无限滚动）');

    // 数据状态
    let fullLibrary = { movies: [], tv_shows: [] };
    let filteredMovies = [];
    let filteredShows = [];

    // UI 状态
    let expandedShows = {};
    let expandedSeasons = {};
    let renderedSeasons = {};
    let selectedEpisodes = new Set();

    // 视图模式：'all', 'movies', 'tv'
    let viewMode = 'all';

    // 分页状态
    const PAGE_SIZE = 30;
    let moviePage = 1;
    let showPage = 1;
    let isLoadingMovies = false;
    let isLoadingShows = false;
    let hasMoreMovies = true;
    let hasMoreShows = true;

    // 观察器
    let movieObserver = null;
    let showObserver = null;

    const containerId = 'mediaLibraryManagerContainer';

    // ---------- 辅助函数 ----------
    function cleanTitle(title) {
        if (!title) return '';
        return title.replace(/\s*\(\)\s*$/, '').trim();
    }

    function updateBatchButtons() {
        const btnCorrect = document.getElementById('mediaBatchCorrectBtn');
        const btnDelete = document.getElementById('mediaBatchDeleteBtn');
        const total = selectedEpisodes.size;
        if (btnCorrect) btnCorrect.disabled = (total === 0);
        if (btnDelete) btnDelete.disabled = (total === 0);
        const countSpan = document.getElementById('mediaSelectedCount');
        if (countSpan) countSpan.textContent = total;
    }

    function resetPagination() {
        moviePage = 1;
        showPage = 1;
        hasMoreMovies = true;
        hasMoreShows = true;
        isLoadingMovies = false;
        isLoadingShows = false;
        renderedSeasons = {};
    }

    function getMovieSlice() {
        const end = moviePage * PAGE_SIZE;
        const slice = filteredMovies.slice(0, end);
        hasMoreMovies = end < filteredMovies.length;
        return slice;
    }

    function getShowSlice() {
        const end = showPage * PAGE_SIZE;
        const slice = filteredShows.slice(0, end);
        hasMoreShows = end < filteredShows.length;
        return slice;
    }

    // ---------- 渲染主入口 ----------
    function render(appendMovies = false, appendShows = false) {
        const container = document.getElementById(containerId);
        if (!container) return;

        // 非追加模式：完全重建
        if (!appendMovies && !appendShows) {
            container.innerHTML = '';
            renderedSeasons = {};

            // 视图切换按钮
            const viewBar = document.createElement('div');
            viewBar.className = 'view-toggle-bar';
            for (const [mode, text] of [['all', '📚 全部'], ['movies', '🎬 电影'], ['tv', '📺 剧集']]) {
                viewBar.append(app.el('button', {type: 'button', text,
                    className: `view-btn ${viewMode === mode ? 'active' : ''}`,
                    dataset: {action: 'switchView', view: mode}}));
            }
            container.appendChild(viewBar);

            // 电影区域
            if (viewMode !== 'tv') {
                const movieSection = document.createElement('div');
                movieSection.className = 'media-section';
                movieSection.innerHTML = '<h4>🎬 电影</h4><div class="media-card-grid" id="movieGrid"></div>';
                container.appendChild(movieSection);
            }

            // 剧集区域
            if (viewMode !== 'movies') {
                const showSection = document.createElement('div');
                showSection.className = 'media-section';
                showSection.innerHTML = '<h4>📺 剧集</h4><div class="media-card-grid" id="showGrid"></div>';
                container.appendChild(showSection);
            }
        }

        // 渲染电影网格
        if (viewMode !== 'tv') {
            renderMovieGrid(appendMovies);
        }

        // 渲染剧集网格
        if (viewMode !== 'movies') {
            renderShowGrid(appendShows);
        }

        // 渲染已展开的季面板（仅剧集相关）
        if (viewMode !== 'movies') {
            renderExpandedSeasonsPanels(appendShows);
        }

        updateBatchButtons();
        setupObservers();
    }

    // ---------- 电影网格渲染 ----------
    function actionButton(text, action, key, className = 'secondary') {
        return app.el('button', {type: 'button', text, className, dataset: {action, key}});
    }

    function renderMovieGrid(append = false) {
        const grid = document.getElementById('movieGrid');
        if (!grid) return;
        const movies = getMovieSlice();
        if (!append) grid.replaceChildren();
        if (!movies.length && !append) { grid.textContent = '暂无电影'; return; }
        for (const movie of movies) {
            const checkbox = app.el('input', {type: 'checkbox', checked: selectedEpisodes.has(movie.cache_key),
                dataset: {action: 'toggleSelect', type: 'movie', key: movie.cache_key}});
            grid.append(app.el('div', {className: 'media-card movie-card', dataset: {movieKey: movie.cache_key}},
                app.el('div', {className: 'media-card-poster'}, app.poster(app.mediaPosterUrl('movie', movie.tmdb_id)),
                    app.el('div', {className: 'media-card-check'}, checkbox)),
                app.el('div', {className: 'media-card-info'},
                    app.el('div', {className: 'media-card-title', title: movie.title, text: cleanTitle(movie.title)}),
                    app.el('div', {className: 'media-card-year', text: movie.year || ''})),
                app.el('div', {className: 'media-card-actions'}, actionButton('🔧', 'correctSingle', movie.cache_key),
                    actionButton('🗑️', 'deleteSingle', movie.cache_key, 'danger'))));
        }
    }

    function renderShowGrid(append = false) {
        const grid = document.getElementById('showGrid');
        if (!grid) return;
        const shows = getShowSlice();
        if (!append) grid.replaceChildren();
        if (!shows.length && !append) { grid.textContent = '暂无剧集'; return; }
        for (const show of shows) {
            const count = Object.keys(show.seasons || {}).length;
            grid.append(app.el('div', {className: 'media-card tv-card', dataset: {showId: show.tmdb_id}},
                app.el('div', {className: 'media-card-poster'}, app.poster(app.mediaPosterUrl('tv', show.tmdb_id))),
                app.el('div', {className: 'media-card-info'},
                    app.el('div', {className: 'media-card-title', title: show.title, text: cleanTitle(show.title)}),
                    app.el('div', {className: 'media-card-year', text: show.year || ''})),
                app.el('div', {className: 'media-card-seasons-toggle'}, app.el('button', {type: 'button', className: 'season-toggle-btn',
                    text: `📋 ${count} 季 ${expandedShows[show.tmdb_id] ? '▲' : '▼'}`,
                    dataset: {action: 'toggleShowSeasons', showId: show.tmdb_id}}))));
        }
    }

    function renderExpandedSeasonsPanels(append = false) {
        const container = document.getElementById(containerId);
        if (!container) return;
        if (!append) container.querySelectorAll('.show-seasons-panel').forEach(panel => panel.remove());
        for (const show of filteredShows) {
            const id = show.tmdb_id;
            if (!expandedShows[id]) continue;
            if (Array.from(container.querySelectorAll('.show-seasons-panel')).some(panel => panel.dataset.showPanel === String(id))) continue;
            const seasons = show.seasons || {};
            const numbers = Object.keys(seasons).sort((a,b) => parseInt(a) - parseInt(b));
            const list = app.el('div', {className: 'season-list'});
            const panel = app.el('div', {className: 'show-seasons-panel', dataset: {showPanel: id}},
                app.el('div', {className: 'show-seasons-header', style: 'display:flex;justify-content:space-between;align-items:center;'},
                    app.el('span', {text: `📁 ${cleanTitle(show.title)} 季列表`}),
                    app.el('button', {type: 'button', className: 'secondary', text: '✕ 收起', dataset: {action: 'toggleShowSeasons', showId: id}})), list);
            for (const number of numbers) {
                const key = `${id}-${number}`;
                const expanded = expandedSeasons[key] || false;
                const count = (seasons[number].episodes || []).length;
                list.append(app.el('div', {className: 'season-row'},
                    app.el('div', {className: 'season-row-header', style: 'display:flex;align-items:center;justify-content:space-between;'},
                        app.el('span', {style: 'cursor:pointer;flex:1;', dataset: {action: 'toggleSeasonEpisodes', seasonKey: key}},
                            `📺 第 ${number} 季 (${count} 集) `, app.el('span', {className: 'expand-arrow', text: expanded ? '▼' : '▶'})),
                        app.el('div', {style: 'display:flex;gap:4px;'},
                            app.button('全选', () => App.MediaManager.selectAllInSeason(key, true)),
                            app.button('反选', () => App.MediaManager.selectAllInSeason(key, false)))),
                    app.el('div', {className: 'episode-grid', id: `episodes-${key}`, style: `display:${expanded ? 'grid' : 'none'};`})));
            }
            container.append(panel);
            for (const number of numbers) {
                const key = `${id}-${number}`;
                if (expandedSeasons[key] && !renderedSeasons[key]) lazyLoadEpisodes(id, number, seasons[number]);
            }
        }
    }

    function lazyLoadEpisodes(showId, seasonNum, seasonData) {
        const key = `${showId}-${seasonNum}`;
        const container = document.getElementById(`episodes-${key}`);
        if (!container || renderedSeasons[key]) return;
        const show = filteredShows.find(s => s.tmdb_id == showId);
        if (!show) return;
        container.replaceChildren();
        for (const episode of seasonData.episodes || []) {
            const title = episode.title || `第 ${episode.episode} 集`;
            const label = app.el('span', {className: 'episode-title episode-title-clickable',
                style: 'cursor:pointer;text-decoration:underline dotted;font-size:12px;', title: title + '\n点击查看源文件详情', text: title});
            label.addEventListener('click', event => App.MediaManager.showEpisodeDetail(event, episode.cache_key, cleanTitle(show.title), seasonNum));
            container.append(app.el('div', {className: 'episode-item-card'},
                app.el('input', {type: 'checkbox', checked: selectedEpisodes.has(episode.cache_key), dataset: {action: 'toggleSelect', type: 'episode', key: episode.cache_key}}),
                app.el('span', {className: 'episode-number', text: `E${String(episode.episode).padStart(2, '0')}`}), label,
                app.el('div', {className: 'episode-actions'}, actionButton('🔧', 'correctSingle', episode.cache_key),
                    actionButton('🗑️', 'deleteSingle', episode.cache_key, 'danger'))));
        }
        renderedSeasons[key] = true;
    }

    // ---------- 无限滚动观察器 ----------
    function setupObservers() {
        if (movieObserver) movieObserver.disconnect();
        if (showObserver) showObserver.disconnect();

        const movieGrid = document.getElementById('movieGrid');
        const showGrid = document.getElementById('showGrid');

        if (movieGrid && (viewMode !== 'tv')) {
            const oldSentinel = document.getElementById('movieSentinel');
            if (oldSentinel) oldSentinel.remove();
            const sentinel = document.createElement('div');
            sentinel.id = 'movieSentinel';
            sentinel.style.height = '10px';
            movieGrid.appendChild(sentinel);
            movieObserver = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting && hasMoreMovies && !isLoadingMovies) {
                    loadMoreMovies();
                }
            }, { rootMargin: '200px' });
            movieObserver.observe(sentinel);
        }

        if (showGrid && (viewMode !== 'movies')) {
            const oldSentinel = document.getElementById('showSentinel');
            if (oldSentinel) oldSentinel.remove();
            const sentinel = document.createElement('div');
            sentinel.id = 'showSentinel';
            sentinel.style.height = '10px';
            showGrid.appendChild(sentinel);
            showObserver = new IntersectionObserver((entries) => {
                if (entries[0].isIntersecting && hasMoreShows && !isLoadingShows) {
                    loadMoreShows();
                }
            }, { rootMargin: '200px' });
            showObserver.observe(sentinel);
        }
    }

    function loadMoreMovies() {
        if (isLoadingMovies || !hasMoreMovies) return;
        isLoadingMovies = true;
        moviePage++;
        renderMovieGrid(true);
        isLoadingMovies = false;
        setupObservers();
    }

    function loadMoreShows() {
        if (isLoadingShows || !hasMoreShows) return;
        isLoadingShows = true;
        showPage++;
        renderShowGrid(true);
        isLoadingShows = false;
        setupObservers();
    }

    // ---------- 视图切换 ----------
    function switchView(mode) {
        if (viewMode === mode) return;
        viewMode = mode;
        resetPagination();
        render(false);
    }

    // ---------- 过滤与排序 ----------
    function filterAndSort() {
        resetPagination();
        render(false);
    }

    function sortData(field, order) {
        const multiplier = order === 'desc' ? -1 : 1;
        filteredMovies.sort((a, b) => {
            if (field === 'title') return multiplier * (a.title || '').localeCompare(b.title || '');
            if (field === 'year') return multiplier * ((parseInt(a.year) || 0) - (parseInt(b.year) || 0));
            if (field === 'processed_time') return multiplier * ((a.processed_time || 0) - (b.processed_time || 0));
            return 0;
        });
        filteredShows.sort((a, b) => {
            if (field === 'title') return multiplier * (a.title || '').localeCompare(b.title || '');
            if (field === 'year') return multiplier * ((parseInt(a.year) || 0) - (parseInt(b.year) || 0));
            if (field === 'processed_time') return multiplier * (getShowLatestProcessedTime(a) - getShowLatestProcessedTime(b));
            return 0;
        });
    }

    function getShowLatestProcessedTime(show) {
        let latest = 0;
        for (const season of Object.values(show.seasons || {})) {
            for (const ep of season.episodes || []) {
                if (ep.processed_time && ep.processed_time > latest) latest = ep.processed_time;
            }
        }
        return latest;
    }

    // 查找条目
    function findEntryByCacheKey(key) {
        for (let m of fullLibrary.movies) if (m.cache_key === key) return { type: 'movie', data: m };
        for (let s of fullLibrary.tv_shows) {
            for (let sn of Object.values(s.seasons || {})) {
                for (let ep of sn.episodes) if (ep.cache_key === key) return { type: 'episode', data: ep, show: s };
            }
        }
        return null;
    }

    // ---------- 批量操作 ----------
    async function batchCorrectSelected() {
        const keys = Array.from(selectedEpisodes);
        if (!keys.length) { app.showToast('请至少勾选一个单集或电影', 'warning'); return; }
        const files = [];
        for (let k of keys) {
            const e = findEntryByCacheKey(k);
            if (e) {
                let name = e.type === 'movie' ? (e.data.title || '电影') : `${e.show.title} S${String(e.data.season||1).padStart(2,'0')}E${String(e.data.episode||1).padStart(2,'0')}`;
                files.push({ path: e.type === 'movie' ? e.data.cache_key : e.data.cache_key, name });
            }
        }
        if (files.length === 0) { app.showToast('无有效文件', 'warning'); return; }
        if (typeof App.BatchCorrection !== 'undefined') {
            App.BatchCorrection.openModalWithFiles('📋 媒体库选中项', files);
        } else {
            app.showToast('批量修正模块未加载', 'error');
        }
    }

    async function batchDeleteSelected() {
        const keys = Array.from(selectedEpisodes);
        if (!keys.length) { app.showToast('请至少勾选一个单集或电影', 'warning'); return; }
        if (!confirm(`确定要删除选中的 ${keys.length} 个媒体文件吗？此操作仅删除目标文件（链接），不会删除源文件。`)) return;

        const paths = keys.map(k => {
            const e = findEntryByCacheKey(k);
            return e ? (e.type === 'movie' ? e.data.cache_key : e.data.cache_key) : null;
        }).filter(p => p);

        try {
            const resp = await app.fetch('/api/media/batch_delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ src_paths: paths, delete_source: false })
            });
            const data = await resp.json();
            if (data.status === 'success') {
                app.showToast(`批量删除完成：成功 ${data.success}，失败 ${data.failed}`, 'success');
                selectedEpisodes.clear();
                await loadLibrary();
                updateBatchButtons();
            } else {
                app.showToast('批量删除失败', 'error');
            }
        } catch (e) {
            app.showToast('请求失败：' + e.message, 'error');
        }
    }
    // ---------- 事件委托 ----------
    function handleContainerClick(e) {
        const target = e.target.closest('[data-action]');
        if (!target) return;
        const action = target.dataset.action;

        switch (action) {
            case 'switchView':
                switchView(target.dataset.view);
                break;
            case 'toggleSelect': {
                const key = target.dataset.key;
                const type = target.dataset.type;
                const checkbox = target.tagName === 'INPUT' ? target : target.querySelector('input');
                if (!checkbox) return;
                const checked = checkbox.checked;
                if (type === 'movie' || type === 'episode') {
                    checked ? selectedEpisodes.add(key) : selectedEpisodes.delete(key);
                    updateBatchButtons();
                }
                break;
            }
            case 'toggleShowSeasons': {
                const showId = target.dataset.showId;
                expandedShows[showId] = !expandedShows[showId];
                if (!expandedShows[showId]) {
                    Object.keys(expandedSeasons).forEach(k => {
                        if (k.startsWith(showId + '-')) delete expandedSeasons[k];
                    });
                    const panel = Array.from(document.querySelectorAll('.show-seasons-panel')).find(node => node.dataset.showPanel === String(showId));
                    if (panel) panel.remove();
                } else {
                    renderExpandedSeasonsPanels(true);
                }
                const card = target.closest('.tv-card');
                if (card) {
                    const btn = card.querySelector('.season-toggle-btn');
                    const seasons = filteredShows.find(s => s.tmdb_id == showId)?.seasons || {};
                    const count = Object.keys(seasons).length;
                    btn.textContent = `📋 ${count} 季 ${expandedShows[showId] ? '▲' : '▼'}`;
                }
                break;
            }
            case 'toggleSeasonEpisodes': {
                const seasonKey = target.dataset.seasonKey;
                const [showId, seasonNum] = seasonKey.split('-');
                const isNowExpanded = !expandedSeasons[seasonKey];
                expandedSeasons[seasonKey] = isNowExpanded;

                const container = document.getElementById(`episodes-${seasonKey}`);
                if (container) {
                    container.style.display = isNowExpanded ? 'grid' : 'none';
                    if (isNowExpanded && !renderedSeasons[seasonKey]) {
                        const show = filteredShows.find(s => s.tmdb_id == showId);
                        if (show && show.seasons && show.seasons[seasonNum]) {
                            lazyLoadEpisodes(showId, seasonNum, show.seasons[seasonNum]);
                        }
                    }
                }
                const header = target.closest('.season-row-header');
                if (header) {
                    const arrow = header.querySelector('.expand-arrow');
                    if (arrow) arrow.textContent = isNowExpanded ? '▼' : '▶';
                }
                break;
            }
            case 'correctSingle': {
                const key = target.dataset.key;
                const entry = findEntryByCacheKey(key);
                if (!entry) return;
                const path = entry.type === 'movie' ? entry.data.cache_key : entry.data.cache_key;
                const name = entry.type === 'movie' ? (entry.data.title || '电影') : `${entry.show.title} S${String(entry.data.season||1).padStart(2,'0')}E${String(entry.data.episode||1).padStart(2,'0')}`;
                if (typeof App.Correction !== 'undefined') {
                    App.Correction.openCorrectionModal(path, name);
                } else {
                    app.showToast('修正模块未加载', 'error');
                }
                break;
            }
            case 'deleteSingle': {
                const key = target.dataset.key;
                if (!confirm('确定要删除该媒体文件吗？此操作仅删除目标文件（链接），不会删除源文件。')) return;
                const entry = findEntryByCacheKey(key);
                if (!entry) return;
                const path = entry.type === 'movie' ? entry.data.cache_key : entry.data.cache_key;
                app.fetch('/api/media/delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ src_path: path, delete_source: false })
                }).then(r => r.json()).then(data => {
                    if (data.status === 'success') {
                        app.showToast('删除成功', 'success');
                        selectedEpisodes.delete(key);
                        loadLibrary();
                    } else {
                        app.showToast('删除失败: ' + (data.message || ''), 'error');
                    }
                }).catch(e => app.showToast('请求失败：' + e.message, 'error'));
                break;
            }
            case 'correctShowBatch': {
                const showId = target.dataset.showId;
                const show = fullLibrary.tv_shows.find(s => s.tmdb_id == showId);
                if (!show) return;
                const files = [];
                for (let sn in show.seasons) {
                    (show.seasons[sn].episodes || []).forEach(ep => {
                        files.push({
                            path: ep.cache_key,
                            name: `${show.title} S${String(sn).padStart(2,'0')}E${String(ep.episode).padStart(2,'0')}`
                        });
                    });
                }
                if (files.length === 0) { app.showToast('该剧无集数', 'warning'); return; }
                if (typeof App.BatchCorrection !== 'undefined') {
                    App.BatchCorrection.openModalWithFiles(`📺 ${show.title}`, files);
                } else {
                    app.showToast('批量修正模块未加载', 'error');
                }
                break;
            }
            case 'deleteShowBatch': {
                const showId = target.dataset.showId;
                const show = fullLibrary.tv_shows.find(s => s.tmdb_id == showId);
                if (!show) return;

                const paths = [];
                for (let sn in show.seasons) {
                    (show.seasons[sn].episodes || []).forEach(ep => {
                        if (ep.cache_key) paths.push(ep.cache_key);
                    });
                }
                if (paths.length === 0) {
                    app.showToast('该剧无集数', 'warning');
                    return;
                }
                if (!confirm(`确定要删除《${cleanTitle(show.title)}》的全部 ${paths.length} 个媒体文件吗？\n\n此操作仅删除目标文件（链接），不会删除源文件。`)) return;

                app.fetch('/api/media/batch_delete', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ src_paths: paths, delete_source: false })
                }).then(r => r.json()).then(data => {
                    if (data.status === 'success') {
                        app.showToast(`批量删除完成：成功 ${data.success}，失败 ${data.failed}`, 'success');
                        paths.forEach(p => selectedEpisodes.delete(p));
                        loadLibrary();
                    } else {
                        app.showToast('删除失败: ' + (data.message || ''), 'error');
                    }
                }).catch(e => app.showToast('请求失败：' + e.message, 'error'));
                break;
            }
        }
    }

    // ---------- 加载数据 ----------
    async function loadLibrary() {
        try {
            const resp = await app.fetch('/api/media/library');
            const data = await resp.json();
            fullLibrary = data;
            filteredMovies = data.movies || [];
            filteredShows = data.tv_shows || [];
            sortData('processed_time', 'desc');
            filterAndSort();
        } catch (e) {
            console.error('加载媒体库失败', e);
            document.getElementById(containerId).textContent = '加载失败：' + e.message;
        }
    }

    // ---------- 公开方法 ----------
    return {
        init: function() {
            const container = document.getElementById(containerId);
            if (container) {
                container.addEventListener('click', handleContainerClick);
            }
            loadLibrary();
        },
        refreshLibrary: loadLibrary,
        filterLibrary: (kw) => {
            const keyword = kw.trim().toLowerCase();
            filteredMovies = fullLibrary.movies.filter(m =>
                (m.title || '').toLowerCase().includes(keyword) || (m.year || '').includes(keyword)
            );
            filteredShows = fullLibrary.tv_shows.filter(s =>
                (s.title || '').toLowerCase().includes(keyword) || (s.year || '').includes(keyword)
            );
            filterAndSort();
        },
        setSort: (field, order) => {
            sortData(field, order);
            filterAndSort();
        },
        selectAllInSeason: (seasonKey, select) => {
            const [showId, sNum] = seasonKey.split('-');
            const show = fullLibrary.tv_shows.find(s => s.tmdb_id == showId);
            if (!show || !show.seasons || !show.seasons[sNum]) return;
            const episodes = show.seasons[sNum].episodes || [];
            episodes.forEach(ep => {
                if (select) {
                    selectedEpisodes.add(ep.cache_key);
                } else {
                    selectedEpisodes.has(ep.cache_key) ? selectedEpisodes.delete(ep.cache_key) : selectedEpisodes.add(ep.cache_key);
                }
            });
            render(false);
            updateBatchButtons();
        },
        showEpisodeDetail: (event, cacheKey, showTitle, seasonNum) => {
            const entry = findEntryByCacheKey(cacheKey);
            if (!entry || entry.type !== 'episode') return;
            const epData = entry.data;
            const srcPath = epData.cache_key;
            const pathParts = srcPath.replace(/\\/g, '/').split('/');
            const fileName = pathParts.pop();
            const parentDir = pathParts.pop() || '';
            const grandparentDir = pathParts.pop() || '';
            let popup = document.getElementById('episodeDetailPopup');
            if (!popup) {
                popup = document.createElement('div');
                popup.id = 'episodeDetailPopup';
                popup.style.cssText = `
                    position: fixed; background: white; border: 1px solid #ccc; border-radius: 12px;
                    padding: 16px; box-shadow: 0 8px 20px rgba(0,0,0,0.15); z-index: 1000; max-width: 400px;
                `;
                document.body.appendChild(popup);
                document.addEventListener('click', (e) => {
                    if (!popup.contains(e.target) && !e.target.closest('.episode-title-clickable')) {
                        popup.style.display = 'none';
                    }
                });
            }
            popup.replaceChildren(
                app.el('strong', {text: `📺 ${showTitle} S${String(seasonNum).padStart(2,'0')}E${String(epData.episode).padStart(2,'0')}`}), app.el('br'),
                app.el('span', {style: 'font-size:13px;color:#6c757d;', text: `📁 ${grandparentDir}/${parentDir}`}), app.el('br'),
                app.el('span', {style: 'font-size:12px;word-break:break-all;', text: `📄 ${fileName}`}), app.el('br'),
                app.el('span', {style: 'font-size:12px;', text: `🕒 处理时间: ${epData.processed_time ? new Date(epData.processed_time * 1000).toLocaleString() : '未知'}`}));
            popup.style.display = 'block';
            const rect = event.currentTarget.getBoundingClientRect();
            popup.style.left = rect.left + 'px';
            popup.style.top = (rect.bottom + 5) + 'px';
        },
        batchCorrectSelected: batchCorrectSelected,
        batchDeleteSelected: batchDeleteSelected,
    };
})(window.App);
