/**
 * 媒体库管理模块（性能优化版 + 影剧分离）
 * - 懒加载集数详情
 * - 电影/剧集独立无限滚动（每批 30 个）
 * - 视图切换（全部 / 仅电影 / 仅剧集）
 * - 完整的批量修正、批量删除功能
 * - 「最近入库」聚焦区、海报墙、就地展开的季集面板、底部选择条
 *
 * 展示用的数字（部数、季数、集数、入库时间）全部来自 /api/media/library 的返回值。
 */
window.App = window.App || {};
App.MediaManager = (function(app) {
    'use strict';

    console.log('MediaManager 模块已加载（影剧分离 + 无限滚动）');

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

    // 展示状态：过滤关键词、「最近入库」列表与当前聚焦项
    const RECENT_LIMIT = 8;
    let keyword = '';
    let recentItems = [];
    let spotlightIndex = 0;

    // ---------- 辅助函数 ----------
    function cleanTitle(title) {
        if (!title) return '';
        return title.replace(/\s*\(\)\s*$/, '').trim();
    }

    function compact(...nodes) {
        return nodes.filter(node => node !== null && node !== undefined && node !== false && node !== '');
    }

    function episodeCount(show) {
        return Object.values(show.seasons || {}).reduce((sum, season) => sum + (season.episodes || []).length, 0);
    }

    function findShowCard(showId) {
        return Array.from(document.querySelectorAll(`#${containerId} .tv-card`))
            .find(card => card.dataset.showId === String(showId)) || null;
    }

    function findShowPanel(showId) {
        return Array.from(document.querySelectorAll('.show-seasons-panel'))
            .find(panel => panel.dataset.showPanel === String(showId)) || null;
    }

    function updateBatchButtons() {
        const btnCorrect = document.getElementById('mediaBatchCorrectBtn');
        const btnDelete = document.getElementById('mediaBatchDeleteBtn');
        const total = selectedEpisodes.size;
        if (btnCorrect) btnCorrect.disabled = (total === 0);
        if (btnDelete) btnDelete.disabled = (total === 0);
        const countSpan = document.getElementById('mediaSelectedCount');
        if (countSpan) countSpan.textContent = total;
        // 选择条只在有选中项时出现；有选中项时所有勾选框保持可见。
        const bar = document.getElementById('mediaSelectionBar');
        if (bar) bar.hidden = (total === 0);
        const container = document.getElementById(containerId);
        if (container) container.classList.toggle('has-selection', total > 0);
    }

    function clearSelection() {
        selectedEpisodes.clear();
        document.querySelectorAll(`#${containerId} input[type="checkbox"]`).forEach(input => { input.checked = false; });
        updateBatchButtons();
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

    // ---------- 最近入库：聚焦区、工作台的海报条 ----------
    function buildRecentItems() {
        const items = [];
        for (const movie of fullLibrary.movies || []) {
            items.push({type: 'movie', id: movie.tmdb_id, key: movie.cache_key, title: cleanTitle(movie.title),
                year: movie.year || '', time: movie.processed_time || 0});
        }
        for (const show of fullLibrary.tv_shows || []) {
            items.push({type: 'tv', id: show.tmdb_id, title: cleanTitle(show.title), year: show.year || '',
                time: getShowLatestProcessedTime(show), seasons: Object.keys(show.seasons || {}).length, episodes: episodeCount(show)});
        }
        items.sort((a, b) => b.time - a.time);
        recentItems = items.slice(0, RECENT_LIMIT);
        if (spotlightIndex >= recentItems.length) spotlightIndex = 0;
    }

    function posterFrame(item, className) {
        // 海报加载失败时 App.poster 会隐藏图片，露出下面的片名首字。
        return app.el('span', {className},
            app.el('span', {className: 'poster-fallback', text: (item.title || '?').slice(0, 1), attrs: {'aria-hidden': 'true'}}),
            app.poster(app.mediaPosterUrl(item.type, item.id), {alt: ''}));
    }

    function renderSpotlight() {
        const box = document.getElementById('librarySpotlight');
        if (!box) return;
        const item = recentItems[spotlightIndex];
        box.hidden = !item || !!keyword;
        if (box.hidden) { box.replaceChildren(); return; }

        const meta = app.el('div', {className: 'spotlight-meta'}, ...compact(
            app.el('span', {className: 'spotlight-chip', text: item.type === 'movie' ? '电影' : '剧集'}),
            item.year && app.el('span', {text: item.year}),
            item.type === 'tv' && app.el('span', {text: `${item.seasons} 季 ${item.episodes} 集`}),
            item.time && app.el('span', {text: `入库于 ${new Date(item.time * 1000).toLocaleDateString()}`})));
        const actions = item.type === 'tv'
            ? [app.el('button', {type: 'button', className: 'on-dark is-solid', text: '查看季集', dataset: {action: 'openShow', showId: item.id}}),
               app.el('button', {type: 'button', className: 'on-dark', text: '整部修正', dataset: {action: 'correctShowBatch', showId: item.id}})]
            : [app.el('button', {type: 'button', className: 'on-dark is-solid', text: '修正', dataset: {action: 'correctSingle', key: item.key}}),
               app.el('button', {type: 'button', className: 'on-dark', text: '删除', dataset: {action: 'deleteSingle', key: item.key}})];
        const thumbs = app.el('div', {className: 'spotlight-thumbs', attrs: {role: 'group', 'aria-label': '最近入库的其他条目'}});
        recentItems.forEach((other, index) => {
            const thumb = app.el('button', {type: 'button', className: 'spotlight-thumb', title: other.title,
                dataset: {action: 'spotlight', index}, attrs: {'aria-pressed': index === spotlightIndex, 'aria-label': other.title}});
            thumb.append(posterFrame(other, 'thumb-frame'));
            thumbs.append(thumb);
        });

        box.replaceChildren(
            app.poster(app.mediaPosterUrl(item.type, item.id), {className: 'spotlight-backdrop', alt: ''}),
            posterFrame(item, 'spotlight-poster'),
            app.el('div', {className: 'spotlight-body'},
                app.el('p', {className: 'spotlight-label', text: '最近入库'}),
                app.el('h2', {className: 'spotlight-title', title: item.title, text: item.title}),
                meta,
                app.el('div', {className: 'spotlight-actions'}, ...actions)),
            ...(recentItems.length > 1 ? [thumbs] : []));
    }

    function renderHomeRecent() {
        const section = document.getElementById('homeRecent');
        const row = document.getElementById('homeRecentRow');
        if (!section || !row) return;
        section.hidden = recentItems.length === 0;
        row.replaceChildren(...recentItems.map((item, index) => {
            const button = app.el('button', {type: 'button', className: 'recent-item', title: item.title, dataset: {index}});
            button.append(posterFrame(item, 'recent-poster'),
                app.el('span', {className: 'recent-title', text: item.title}),
                app.el('span', {className: 'recent-sub', text: item.type === 'movie' ? (item.year || '电影') : `${item.seasons} 季 ${item.episodes} 集`}));
            return button;
        }));
    }

    function renderStats() {
        const stats = document.getElementById('libraryStats');
        if (!stats) return;
        const movies = (fullLibrary.movies || []).length;
        const shows = fullLibrary.tv_shows || [];
        const episodes = shows.reduce((sum, show) => sum + episodeCount(show), 0);
        if (!movies && !shows.length) { stats.replaceChildren(); return; }
        // 各项之间留一个空白文本节点：视觉上由 flex 间距分隔，读屏和复制时不会粘在一起。
        stats.replaceChildren(...[[movies, '部电影'], [shows.length, '部剧集'], [episodes, '集']].flatMap(([count, unit], index) =>
            [...(index ? [' '] : []), app.el('span', {}, app.el('b', {text: String(count)}), ' ' + unit)]));
    }

    function renderViewTabs() {
        const bar = document.getElementById('libraryViewTabs');
        if (!bar) return;
        if (!(fullLibrary.movies || []).length && !(fullLibrary.tv_shows || []).length) { bar.replaceChildren(); return; }
        // 数量只在分区标题里显示一次（「电影 6」「剧集 6」），这里不重复。
        bar.replaceChildren(...[['all', '全部'], ['movies', '电影'], ['tv', '剧集']].map(([mode, text]) =>
            app.el('button', {type: 'button', className: `view-btn ${viewMode === mode ? 'active' : ''}`,
                dataset: {action: 'switchView', view: mode}, attrs: {'aria-pressed': viewMode === mode}},
                text)));
    }

    function section(title, count, gridId) {
        return app.el('section', {className: 'media-section'},
            app.el('h2', {className: 'media-section-title'}, title, app.el('span', {text: String(count)})),
            app.el('div', {className: 'media-card-grid', id: gridId}));
    }

    // ---------- 渲染主入口 ----------
    function render(appendMovies = false, appendShows = false) {
        const container = document.getElementById(containerId);
        if (!container) return;

        // 非追加模式：完全重建
        if (!appendMovies && !appendShows) {
            container.innerHTML = '';
            renderedSeasons = {};
            renderStats();
            renderSpotlight();
            renderViewTabs();

            // 媒体库本身为空（不是过滤后为空）时，给出下一步，而不是两块空白网格。
            if (!(fullLibrary.movies || []).length && !(fullLibrary.tv_shows || []).length) {
                container.append(app.el('div', {className: 'empty-state is-library'},
                    app.el('div', {className: 'empty-cel', attrs: {'aria-hidden': 'true'}}),
                    app.el('b', {text: '媒体库还是空的'}),
                    '在「设置」里填好源文件夹和目标文件夹，然后点击顶部的「开始处理」。'));
                updateBatchButtons();
                return;
            }

            const showMovies = viewMode !== 'tv' && (filteredMovies.length > 0 || viewMode === 'movies');
            const showShows = viewMode !== 'movies' && (filteredShows.length > 0 || viewMode === 'tv');
            if (!showMovies && !showShows) {
                // 过滤后没有结果
                container.append(app.el('div', {className: 'empty-state'},
                    app.el('b', {text: '没有符合条件的条目'}),
                    app.el('span', {text: keyword ? `没有标题或年份包含「${keyword}」的电影或剧集。` : '换一个分类看看。'}),
                    ...(keyword ? [app.el('button', {type: 'button', className: 'secondary', text: '清除过滤', dataset: {action: 'clearFilter'}})] : [])));
                updateBatchButtons();
                return;
            }
            if (showMovies) container.appendChild(section('电影', filteredMovies.length, 'movieGrid'));
            if (showShows) container.appendChild(section('剧集', filteredShows.length, 'showGrid'));
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
        const slice = getMovieSlice();
        // 追加时只渲染新的一页，已有卡片不重复生成。
        const movies = append ? slice.slice((moviePage - 1) * PAGE_SIZE) : slice;
        if (!append) grid.replaceChildren();
        if (!slice.length && !append) { grid.append(app.el('p', {className: 'grid-empty', text: '还没有电影'})); return; }
        for (const movie of movies) {
            const checkbox = app.el('input', {type: 'checkbox', checked: selectedEpisodes.has(movie.cache_key),
                title: '选择', dataset: {action: 'toggleSelect', type: 'movie', key: movie.cache_key}});
            grid.append(app.el('div', {className: 'media-card movie-card', dataset: {movieKey: movie.cache_key}},
                app.el('div', {className: 'media-card-poster'}, app.poster(app.mediaPosterUrl('movie', movie.tmdb_id), {alt: '', loading: 'lazy'}),
                    app.el('label', {className: 'media-card-check'}, checkbox),
                    app.el('div', {className: 'media-card-actions'}, actionButton('修正', 'correctSingle', movie.cache_key, 'on-dark'),
                        actionButton('删除', 'deleteSingle', movie.cache_key, 'on-dark danger'))),
                app.el('div', {className: 'media-card-info'},
                    app.el('div', {className: 'media-card-title', title: movie.title, text: cleanTitle(movie.title)}),
                    app.el('div', {className: 'media-card-year', text: movie.year || ''}))));
        }
    }

    function renderShowGrid(append = false) {
        const grid = document.getElementById('showGrid');
        if (!grid) return;
        const slice = getShowSlice();
        const shows = append ? slice.slice((showPage - 1) * PAGE_SIZE) : slice;
        if (!append) grid.replaceChildren();
        if (!slice.length && !append) { grid.append(app.el('p', {className: 'grid-empty', text: '还没有剧集'})); return; }
        for (const show of shows) {
            const count = Object.keys(show.seasons || {}).length;
            const total = episodeCount(show);
            // 点海报或季数按钮都可以展开；按钮负责键盘和读屏。
            grid.append(app.el('div', {className: 'media-card tv-card', dataset: {showId: show.tmdb_id}},
                app.el('div', {className: 'media-card-poster', dataset: {action: 'toggleShowSeasons', showId: show.tmdb_id}},
                    app.poster(app.mediaPosterUrl('tv', show.tmdb_id), {alt: '', loading: 'lazy'}),
                    app.el('div', {className: 'media-card-seasons-toggle'}, app.el('button', {type: 'button', className: 'season-toggle-btn',
                        text: `${count} 季`, attrs: {'aria-expanded': !!expandedShows[show.tmdb_id]},
                        dataset: {action: 'toggleShowSeasons', showId: show.tmdb_id}}))),
                app.el('div', {className: 'media-card-info'},
                    app.el('div', {className: 'media-card-title', title: show.title, text: cleanTitle(show.title)}),
                    app.el('div', {className: 'media-card-year', text: compact(show.year, `${total} 集`).join('  ')}))));
        }
    }

    // 季集面板插在对应海报卡片之后并横跨整行（网格使用 dense 排布，后面的卡片会补上空位）。
    function renderExpandedSeasonsPanels(append = false) {
        const container = document.getElementById(containerId);
        if (!container) return;
        if (!append) container.querySelectorAll('.show-seasons-panel').forEach(panel => panel.remove());
        for (const show of filteredShows) {
            const id = show.tmdb_id;
            if (!expandedShows[id]) continue;
            if (findShowPanel(id)) continue;
            const card = findShowCard(id);
            if (!card) continue;           // 卡片还没滚动加载出来；加载后再插入
            const seasons = show.seasons || {};
            const numbers = Object.keys(seasons).sort((a,b) => parseInt(a) - parseInt(b));
            const list = app.el('div', {className: 'season-list'});
            const posterUrl = app.mediaPosterUrl('tv', id);
            const panel = app.el('div', {className: 'show-seasons-panel', dataset: {showPanel: id}},
                app.el('div', {className: 'show-seasons-header'},
                    app.poster(posterUrl, {className: 'show-panel-backdrop', alt: ''}),
                    app.el('div', {className: 'show-panel-title'},
                        app.el('strong', {text: cleanTitle(show.title)}),
                        app.el('span', {text: compact(show.year, `${numbers.length} 季`, `${episodeCount(show)} 集`).join('  ')})),
                    app.el('div', {className: 'show-panel-actions'},
                        app.el('button', {type: 'button', className: 'on-dark', text: '整部修正', dataset: {action: 'correctShowBatch', showId: id}}),
                        app.el('button', {type: 'button', className: 'on-dark danger', text: '整部删除', dataset: {action: 'deleteShowBatch', showId: id}}),
                        app.el('button', {type: 'button', className: 'on-dark', text: '收起', dataset: {action: 'toggleShowSeasons', showId: id}}))), list);
            for (const number of numbers) {
                const key = `${id}-${number}`;
                const expanded = expandedSeasons[key] || false;
                const count = (seasons[number].episodes || []).length;
                list.append(app.el('div', {className: 'season-row'},
                    app.el('div', {className: 'season-row-header', style: 'display:flex;align-items:center;justify-content:space-between;'},
                        app.el('button', {type: 'button', className: 'ghost season-expand', dataset: {action: 'toggleSeasonEpisodes', seasonKey: key},
                                attrs: {'aria-expanded': expanded}},
                            app.el('span', {className: 'expand-arrow', text: expanded ? '▼' : '▶'}),
                            `${Number(number) === 0 ? '特别篇 (S00)' : `第 ${number} 季`} · ${count} 集`),
                        app.el('div', {style: 'display:flex;gap:4px;'},
                            app.button('全选', () => App.MediaManager.selectAllInSeason(key, true)),
                            app.button('反选', () => App.MediaManager.selectAllInSeason(key, false)))),
                    app.el('div', {className: 'episode-grid', id: `episodes-${key}`, style: `display:${expanded ? 'grid' : 'none'};`})));
            }
            card.after(panel);
            card.classList.add('is-open');
            for (const number of numbers) {
                const key = `${id}-${number}`;
                if (expandedSeasons[key] && !renderedSeasons[key]) lazyLoadEpisodes(id, number, seasons[number]);
            }
        }
    }

    // 从聚焦区或工作台打开某部剧：确保卡片已渲染，再展开并滚动到面板。
    function revealShow(showId) {
        if (keyword) {
            const input = document.getElementById('mediaLibrarySearchInput');
            if (input) input.value = '';
            applyKeyword('');
        }
        if (viewMode === 'movies') viewMode = 'all';
        const index = filteredShows.findIndex(show => String(show.tmdb_id) === String(showId));
        if (index < 0) return;
        showPage = Math.max(showPage, Math.ceil((index + 1) / PAGE_SIZE));
        expandedShows[showId] = true;
        render(false);
        const panel = findShowPanel(showId);
        if (panel) {
            if (panel.scrollIntoView) panel.scrollIntoView({block: 'center'});
            const first = panel.querySelector('.season-expand');
            if (first) first.focus({preventScroll: true});
        }
    }

    function applyKeyword(value) {
        keyword = String(value || '').trim().toLowerCase();
        filteredMovies = (fullLibrary.movies || []).filter(m =>
            (m.title || '').toLowerCase().includes(keyword) || String(m.year || '').includes(keyword)
        );
        filteredShows = (fullLibrary.tv_shows || []).filter(s =>
            (s.title || '').toLowerCase().includes(keyword) || String(s.year || '').includes(keyword)
        );
        applyCurrentSort();
    }

    function applyCurrentSort() {
        const select = document.getElementById('mediaLibrarySortSelect');
        const [field, order] = ((select && select.value) || 'processed_time-desc').split('-');
        sortData(field, order);
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
            const label = app.el('button', {type: 'button', className: 'episode-title episode-title-clickable',
                title: title + '\n点击查看源文件详情', text: title});
            label.addEventListener('click', event => App.MediaManager.showEpisodeDetail(event, episode.cache_key, cleanTitle(show.title), seasonNum));
            container.append(app.el('div', {className: 'episode-item-card'},
                app.el('input', {type: 'checkbox', checked: selectedEpisodes.has(episode.cache_key), title: '选择', dataset: {action: 'toggleSelect', type: 'episode', key: episode.cache_key}}),
                app.el('span', {className: 'episode-number', text: `E${String(episode.episode).padStart(2, '0')}`}), label,
                app.el('div', {className: 'episode-actions'}, actionButton('修正', 'correctSingle', episode.cache_key),
                    actionButton('删除', 'deleteSingle', episode.cache_key, 'danger'))));
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
            sentinel.className = 'grid-sentinel';
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
            sentinel.className = 'grid-sentinel';
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
        renderExpandedSeasonsPanels(true);
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
            App.BatchCorrection.openModalWithFiles('媒体库选中项', files);
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
                const card = findShowCard(showId);
                if (!expandedShows[showId]) {
                    Object.keys(expandedSeasons).forEach(k => {
                        if (k.startsWith(showId + '-')) delete expandedSeasons[k];
                    });
                    const panel = findShowPanel(showId);
                    const hadFocus = panel && panel.contains(document.activeElement);
                    if (panel) panel.remove();
                    if (card) card.classList.remove('is-open');
                    // 从面板里收起时，把焦点还给卡片上的按钮。
                    if (hadFocus && card) card.querySelector('.season-toggle-btn')?.focus({preventScroll: true});
                } else {
                    renderExpandedSeasonsPanels(true);
                    // 面板紧跟在卡片所在行之后；滚动过去，免得展开后看不到变化。
                    const opened = findShowPanel(showId);
                    if (opened && opened.scrollIntoView) opened.scrollIntoView({block: 'nearest'});
                }
                if (card) {
                    const btn = card.querySelector('.season-toggle-btn');
                    const seasons = filteredShows.find(s => s.tmdb_id == showId)?.seasons || {};
                    const count = Object.keys(seasons).length;
                    btn.textContent = `${count} 季`;
                    btn.setAttribute('aria-expanded', String(!!expandedShows[showId]));
                }
                break;
            }
            case 'openShow':
                revealShow(target.dataset.showId);
                break;
            case 'spotlight': {
                const index = Number(target.dataset.index);
                if (Number.isInteger(index) && recentItems[index]) {
                    spotlightIndex = index;
                    renderSpotlight();
                    // 重新渲染后焦点留在同一张缩略图上。
                    document.querySelectorAll('#librarySpotlight .spotlight-thumb')[index]?.focus({preventScroll: true});
                }
                break;
            }
            case 'clearFilter': {
                const input = document.getElementById('mediaLibrarySearchInput');
                if (input) input.value = '';
                applyKeyword('');
                filterAndSort();
                break;
            }
            case 'clearSelection':
                clearSelection();
                break;
            case 'reload':
                loadLibrary();
                break;
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
                    target.setAttribute('aria-expanded', String(isNowExpanded));
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
                    App.BatchCorrection.openModalWithFiles(`${show.title}`, files);
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

    // 工作台「最近入库」：切到媒体库并聚焦这一项
    function handleRecentClick(e) {
        const button = e.target.closest('.recent-item');
        if (!button) return;
        const index = Number(button.dataset.index);
        if (!Number.isInteger(index) || !recentItems[index]) return;
        spotlightIndex = index;
        if (keyword) {
            const input = document.getElementById('mediaLibrarySearchInput');
            if (input) input.value = '';
            applyKeyword('');
            filterAndSort();
        } else {
            renderSpotlight();
        }
        if (app.Shell && typeof app.Shell.show === 'function') app.Shell.show('library', {focus: true});
    }

    // ---------- 加载数据 ----------
    async function loadLibrary() {
        try {
            const resp = await app.fetch('/api/media/library');
            const data = await resp.json();
            fullLibrary = data;
            buildRecentItems();
            renderHomeRecent();
            // 重新加载后沿用当前的过滤关键词和排序方式。
            applyKeyword(keyword);
            filterAndSort();
        } catch (e) {
            console.error('加载媒体库失败', e);
            document.getElementById(containerId).replaceChildren(app.el('div', {className: 'empty-state'},
                app.el('b', {text: '媒体库加载失败'}),
                app.el('span', {text: '加载失败：' + e.message}),
                app.el('button', {type: 'button', className: 'secondary', text: '重试', dataset: {action: 'reload'}})));
        }
    }

    // ---------- 公开方法 ----------
    return {
        init: function() {
            // 同一个处理函数重复绑定会被浏览器去重，init 被调用两次也只响应一次。
            for (const id of [containerId, 'librarySpotlight', 'libraryViewTabs', 'mediaSelectionBar']) {
                const node = document.getElementById(id);
                if (node) node.addEventListener('click', handleContainerClick);
            }
            const recentRow = document.getElementById('homeRecentRow');
            if (recentRow) recentRow.addEventListener('click', handleRecentClick);
            loadLibrary();
        },
        refreshLibrary: loadLibrary,
        filterLibrary: (kw) => {
            applyKeyword(kw);
            filterAndSort();
        },
        clearSelection: clearSelection,
        revealShow: revealShow,
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
                popup.className = 'popover';
                popup.setAttribute('role', 'status');
                document.body.appendChild(popup);
                document.addEventListener('click', (e) => {
                    if (!popup.contains(e.target) && !e.target.closest('.episode-title-clickable')) {
                        popup.style.display = 'none';
                    }
                });
            }
            popup.replaceChildren(
                app.el('strong', {text: `${showTitle} S${String(seasonNum).padStart(2,'0')}E${String(epData.episode).padStart(2,'0')}`}), app.el('br'),
                app.el('span', {className: 'path', text: `目录：${grandparentDir}/${parentDir}`}), app.el('br'),
                app.el('span', {className: 'path', text: `文件：${fileName}`}), app.el('br'),
                app.el('span', {className: 'text-muted', text: `处理时间: ${epData.processed_time ? new Date(epData.processed_time * 1000).toLocaleString() : '未知'}`}));
            popup.style.display = 'block';
            // 贴着被点击的标题显示，并保证不超出视口。
            const rect = event.currentTarget.getBoundingClientRect();
            const margin = 12;
            const left = Math.max(margin, Math.min(rect.left, window.innerWidth - popup.offsetWidth - margin));
            const below = rect.bottom + 6;
            const top = below + popup.offsetHeight + margin > window.innerHeight
                ? Math.max(margin, rect.top - popup.offsetHeight - 6) : below;
            popup.style.left = left + 'px';
            popup.style.top = top + 'px';
        },
        batchCorrectSelected: batchCorrectSelected,
        batchDeleteSelected: batchDeleteSelected,
    };
})(window.App);
