/**
 * 媒体库选择模块（弹窗专用 - 默认展开剧集季，集数折叠）
 */
window.App = window.App || {};
App.MediaLibrary = (function(app) {
    'use strict';

    const modalId = 'manualSelectModal';
    const currentSubtitleSpan = 'currentSubtitleName';
    const searchInput = 'mediaSearchInput';
    const containerId = 'mediaLibraryContainer';

    let currentSubtitleIndex = -1;
    let fullLibrary = { movies: [], tv_shows: [] };
    let filteredMovies = [];
    let filteredShows = [];
    let expandedShows = new Set();      // 展开的剧集 tmdb_id（季列表可见）
    let expandedSeasons = new Set();    // 展开的季 key (tmdb_id-season)（集数可见）
    let selectorMode = 'episode';
    let selectionCallback = null;

    function cleanTitle(title) {
        if (!title) return '';
        return title.replace(/\s*\(\)\s*$/, '').trim();
    }

    function getSeasonSummary(show) {
        const seasons = show.seasons || {};
        const parts = [];
        Object.keys(seasons).sort((a,b)=>parseInt(a)-parseInt(b)).forEach(sn => {
            const eps = seasons[sn].episodes || [];
            if (eps.length > 0) parts.push(`S${sn}(${eps.length}集)`);
        });
        return parts.join(', ') || '暂无集数';
    }

    function renderLibrary() {
        const container = document.getElementById(containerId);
        if (!container) return;
        container.replaceChildren();
        if (filteredMovies.length && ['episode', 'target'].includes(selectorMode)) {
            const list = app.el('div', {className: 'movie-list'});
            container.append(app.el('div', {className: 'media-section'}, app.el('h4', {text: '🎬 电影'}), list));
            for (const movie of filteredMovies) {
                const button = app.el('button', {type: 'button', className: `${selectorMode === 'target' ? 'select-movie-btn' : 'select-media-btn'} success`,
                    text: selectorMode === 'target' ? '选择此电影' : '选择'});
                button.dataset[selectorMode === 'target' ? 'movie' : 'media'] = JSON.stringify(movie);
                list.append(app.el('div', {className: 'movie-item', style: 'display:flex;align-items:center;gap:12px;'},
                    app.poster(app.mediaPosterUrl('movie', movie.tmdb_id), {style: 'width:45px;height:68px;object-fit:cover;border-radius:6px;'}),
                    app.el('span', {className: 'movie-title', style: 'flex:1;', text: `${cleanTitle(movie.title)} ${movie.year ? '(' + movie.year + ')' : ''}`}), button));
            }
        }
        if (filteredShows.length) {
            const list = app.el('div', {className: 'tv-show-list'});
            container.append(app.el('div', {className: 'media-section'}, app.el('h4', {text: '📺 剧集'}), list));
            for (const show of filteredShows) {
                const seasons = show.seasons || {};
                const numbers = Object.keys(seasons).sort((a,b) => parseInt(a) - parseInt(b));
                const header = app.el('div', {className: 'tv-show-header'},
                    app.poster(app.mediaPosterUrl('tv', show.tmdb_id), {className: 'show-poster'}),
                    app.el('div', {className: 'show-info'},
                        app.el('span', {className: 'show-title', text: `${cleanTitle(show.title)} ${show.year ? '(' + show.year + ')' : ''}`}),
                        app.el('span', {className: 'show-seasons-count', title: getSeasonSummary(show), text: `${numbers.length} 季 · ${getSeasonSummary(show)}`})));
                header.addEventListener('click', event => {
                    if (!event.target.closest('button')) App.MediaLibrary.toggleShowExpand(show.tmdb_id);
                });
                if (selectorMode === 'show') header.append(app.el('button', {type: 'button', className: 'select-show-btn success',
                    text: '选择此剧集', style: 'margin-left:auto;', dataset: {show: JSON.stringify(show)}}));
                header.append(app.el('span', {className: 'expand-icon', text: expandedShows.has(show.tmdb_id) ? '▼' : '▶'}));
                const seasonList = app.el('div', {className: 'tv-show-seasons', id: `seasons-${show.tmdb_id}`,
                    style: `display:${expandedShows.has(show.tmdb_id) ? 'block' : 'none'};`});
                for (const number of numbers) {
                    const episodes = seasons[number].episodes || [];
                    const key = `${show.tmdb_id}-${number}`;
                    const expanded = expandedSeasons.has(key);
                    const seasonHeader = app.el('div', {className: 'season-header'},
                        app.el('span', {className: 'season-title', text: `第 ${number} 季 (${episodes.length} 集)`}));
                    seasonHeader.addEventListener('click', event => {
                        if (!event.target.closest('button')) App.MediaLibrary.toggleSeasonExpand(key);
                    });
                    if (['season', 'target'].includes(selectorMode)) seasonHeader.append(app.el('button', {
                        type: 'button', className: 'select-season-btn success', text: '选择此季', style: 'margin-left:10px;',
                        dataset: {show: JSON.stringify(show), season: number}}));
                    seasonHeader.append(app.el('span', {className: 'expand-icon', text: expanded ? '▼' : '▶'}));
                    const episodeList = app.el('div', {className: 'season-episodes', id: `episodes-${key}`, style: `display:${expanded ? 'block' : 'none'};`});
                    for (const ep of episodes) {
                        const media = {media_type: 'tv', title: show.title, year: show.year, season: number, episode: ep.episode,
                            target_path: ep.target_path, target_dir: ep.target_dir, cache_key: ep.cache_key, tmdb_id: show.tmdb_id};
                        const row = app.el('div', {className: 'episode-item'}, app.el('span', {text: `第 ${ep.episode} 集${ep.title ? ' - ' + ep.title : ''}`}));
                        if (selectorMode === 'episode') row.append(app.el('button', {type: 'button', className: 'select-media-btn success',
                            text: '选择', dataset: {media: JSON.stringify(media)}}));
                        episodeList.append(row);
                    }
                    seasonList.append(app.el('div', {className: 'season-item'}, seasonHeader, episodeList));
                }
                list.append(app.el('div', {className: 'tv-show-card'}, header, seasonList));
            }
        }
        if (!filteredMovies.length && !filteredShows.length) container.textContent = '没有匹配的媒体';
    }

    function filterLibrary(keyword) {
        const kw = keyword.trim().toLowerCase();
        if (!kw) {
            filteredMovies = fullLibrary.movies || [];
            filteredShows = fullLibrary.tv_shows || [];
        } else {
            filteredMovies = (fullLibrary.movies || []).filter(m =>
                (m.title || '').toLowerCase().includes(kw) || (m.year || '').includes(kw)
            );
            filteredShows = (fullLibrary.tv_shows || []).filter(show =>
                (show.title || '').toLowerCase().includes(kw) || (show.year || '').includes(kw)
            );
        }
        renderLibrary();
    }

    async function loadLibrary() {
        try {
            const resp = await app.fetch('/api/media/library');
            fullLibrary = await resp.json();
            filteredMovies = fullLibrary.movies || [];
            filteredShows = fullLibrary.tv_shows || [];
        } catch (e) {
            fullLibrary = { movies: [], tv_shows: [] };
            throw e;
        }
    }

    // 重置展开状态：所有剧集默认展开（显示季列表），季内集数折叠
    function resetExpandState() {
        expandedShows.clear();
        expandedSeasons.clear();
        filteredShows.forEach(show => expandedShows.add(show.tmdb_id));
    }

    // 事件委托
    function initEventDelegation() {
        document.addEventListener('click', function(e) {
            if (e.target.classList.contains('select-movie-btn')) {
                const movieStr = e.target.dataset.movie;
                if (movieStr && selectionCallback && selectorMode === 'target') {
                    const movie = JSON.parse(movieStr);
                    selectionCallback({ type: 'movie', data: movie });
                    App.MediaLibrary.closeManualSelectModal();
                    app.showToast(`已选择电影: ${cleanTitle(movie.title)}`, 'success');
                }
            }

            if (e.target.classList.contains('select-media-btn')) {
                const mediaStr = e.target.dataset.media;
                if (mediaStr && selectionCallback) {
                    const media = JSON.parse(mediaStr);
                    selectionCallback(media);
                    App.MediaLibrary.closeManualSelectModal();
                    app.showToast(`已选择: ${media.title}${media.media_type==='tv'?` S${media.season.toString().padStart(2,'0')}E${media.episode.toString().padStart(2,'0')}`:''}`, 'success');
                } else if (mediaStr && currentSubtitleIndex >= 0 && !selectionCallback) {
                    const media = JSON.parse(mediaStr);
                    app.matchResults[currentSubtitleIndex].best_match = { media, score: 100, match_type: 'manual' };
                    app.matchResults[currentSubtitleIndex].candidates = [{ media, score: 100 }];
                    App.MediaLibrary.closeManualSelectModal();
                    if (typeof App.SubtitleCenter !== 'undefined' && App.SubtitleCenter.renderMatchTable) {
                        App.SubtitleCenter.renderMatchTable();
                    }
                    app.showToast(`已手动匹配到: ${media.title}`, 'success');
                }
            }

            if (e.target.classList.contains('select-show-btn')) {
                const showStr = e.target.dataset.show;
                if (showStr && selectionCallback) {
                    const show = JSON.parse(showStr);
                    selectionCallback(show);
                    App.MediaLibrary.closeManualSelectModal();
                    app.showToast(`已选择剧集: ${cleanTitle(show.title)}`, 'success');
                }
            }

            if (e.target.classList.contains('select-season-btn')) {
                const showStr = e.target.dataset.show;
                const seasonNum = parseInt(e.target.dataset.season);
                if (showStr && selectionCallback) {
                    const show = JSON.parse(showStr);
                    if (selectorMode === 'target') {
                        selectionCallback({ type: 'tv', data: { showInfo: show, selectedSeason: seasonNum } });
                    } else if (selectorMode === 'season') {
                        selectionCallback({ showInfo: show, selectedSeason: seasonNum });
                    }
                    App.MediaLibrary.closeManualSelectModal();
                    app.showToast(`已选择: ${cleanTitle(show.title)} 第 ${seasonNum} 季`, 'success');
                }
            }
        });
    }

    document.addEventListener('DOMContentLoaded', initEventDelegation);

    // ---------- 公开 API ----------
    return {
        showMediaSelector: async function(callback, title = '选择目标媒体') {
            selectorMode = 'episode';
            selectionCallback = callback;
            currentSubtitleIndex = -1;
            document.getElementById(currentSubtitleSpan).innerText = title;
            document.getElementById(modalId).style.display = 'block';
            document.getElementById(searchInput).value = '';

            const container = document.getElementById(containerId);
            if (container) container.innerHTML = '<div style="text-align:center; padding:20px;">📚 正在加载媒体库...</div>';

            try {
                await loadLibrary();
                resetExpandState();   // ⭐ 默认展开所有剧集
                filterLibrary('');
            } catch (e) {
                container.textContent = '加载媒体库失败：' + e.message;
            }
        },

        showManualSelect: async function(idx) {
            currentSubtitleIndex = idx;
            selectorMode = 'episode';
            selectionCallback = null;
            document.getElementById(currentSubtitleSpan).innerText = app.matchResults[idx].subtitle.name;
            document.getElementById(modalId).style.display = 'block';
            document.getElementById(searchInput).value = '';

            const container = document.getElementById(containerId);
            if (container) container.innerHTML = '<div style="text-align:center; padding:20px;">📚 正在加载媒体库...</div>';

            try {
                await loadLibrary();
                resetExpandState();
                filterLibrary('');
            } catch (e) {
                container.textContent = '加载媒体库失败：' + e.message;
            }
        },

        showShowSelector: async function(callback) {
            selectorMode = 'show';
            selectionCallback = callback;
            currentSubtitleIndex = -1;
            document.getElementById(currentSubtitleSpan).innerText = '选择目标剧集';
            document.getElementById(modalId).style.display = 'block';
            document.getElementById(searchInput).value = '';

            const container = document.getElementById(containerId);
            if (container) container.innerHTML = '<div style="text-align:center; padding:20px;">📚 正在加载媒体库...</div>';

            try {
                await loadLibrary();
                resetExpandState();
                filterLibrary('');
            } catch (e) {
                container.textContent = '加载媒体库失败：' + e.message;
            }
        },

        showShowAndSeasonSelector: async function(callback) {
            selectorMode = 'season';
            selectionCallback = callback;
            currentSubtitleIndex = -1;
            document.getElementById(currentSubtitleSpan).innerText = '选择目标剧集，并点击“选择此季”';
            document.getElementById(modalId).style.display = 'block';
            document.getElementById(searchInput).value = '';

            const container = document.getElementById(containerId);
            if (container) container.innerHTML = '<div style="text-align:center; padding:20px;">📚 正在加载媒体库...</div>';

            try {
                await loadLibrary();
                resetExpandState();
                filterLibrary('');
            } catch (e) {
                container.textContent = '加载媒体库失败：' + e.message;
            }
        },

        showTargetSelector: async function(callback) {
            selectorMode = 'target';
            selectionCallback = callback;
            currentSubtitleIndex = -1;
            document.getElementById(currentSubtitleSpan).innerText = '选择目标电影或剧集（剧集需指定季）';
            document.getElementById(modalId).style.display = 'block';
            document.getElementById(searchInput).value = '';

            const container = document.getElementById(containerId);
            if (container) container.innerHTML = '<div style="text-align:center; padding:20px;">📚 正在加载媒体库...</div>';

            try {
                await loadLibrary();
                resetExpandState();   // ⭐ 关键：默认展开剧集季列表
                filterLibrary('');
            } catch (e) {
                container.textContent = '加载媒体库失败：' + e.message;
            }
        },

        closeManualSelectModal: function() {
            document.getElementById(modalId).style.display = 'none';
            selectorMode = 'episode';
            selectionCallback = null;
        },

        filterMediaLibrary: function() {
            const kw = document.getElementById(searchInput).value;
            filterLibrary(kw);
        },

        toggleShowExpand: function(tmdbId) {
            expandedShows.has(tmdbId) ? expandedShows.delete(tmdbId) : expandedShows.add(tmdbId);
            renderLibrary();
        },

        toggleSeasonExpand: function(seasonKey) {
            expandedSeasons.has(seasonKey) ? expandedSeasons.delete(seasonKey) : expandedSeasons.add(seasonKey);
            renderLibrary();
        }
    };
})(window.App);
