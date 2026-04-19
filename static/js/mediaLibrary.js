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

        let html = '';

        // 电影部分
        if (filteredMovies.length > 0 && (selectorMode === 'episode' || selectorMode === 'target')) {
            html += '<div class="media-section"><h4>🎬 电影</h4><div class="movie-list">';
            filteredMovies.forEach(movie => {
                const displayTitle = cleanTitle(movie.title);
                const year = movie.year || '';
                const posterUrl = `/media_poster/${movie.tmdb_id}`;
                html += `<div class="movie-item" style="display:flex; align-items:center; gap:12px;">`;
                html += `<img src="${posterUrl}" style="width:45px; height:68px; object-fit:cover; border-radius:6px;" onerror="this.style.display='none'">`;
                html += `<span class="movie-title" style="flex:1;">${app.escapeHtml(displayTitle)} ${year ? '(' + year + ')' : ''}</span>`;
                if (selectorMode === 'target') {
                    html += `<button class="select-movie-btn success" data-movie='${JSON.stringify(movie).replace(/'/g, "&apos;")}'>选择此电影</button>`;
                } else if (selectorMode === 'episode') {
                    html += `<button class="select-media-btn success" data-media='${JSON.stringify(movie).replace(/'/g, "&apos;")}'>选择</button>`;
                }
                html += `</div>`;
            });
            html += '</div></div>';
        }

        // 剧集部分
        if (filteredShows.length > 0) {
            html += '<div class="media-section"><h4>📺 剧集</h4><div class="tv-show-list">';
            filteredShows.forEach(show => {
                const seasons = show.seasons || {};
                const seasonNumbers = Object.keys(seasons).sort((a,b) => parseInt(a)-parseInt(b));
                const posterUrl = show.poster_url || `/media_poster/${show.tmdb_id}`;
                const displayTitle = cleanTitle(show.title);
                const year = show.year || '';
                const isShowExpanded = expandedShows.has(show.tmdb_id);
                const seasonSummary = getSeasonSummary(show);

                html += `<div class="tv-show-card">`;
                // 剧集标题行（点击展开/折叠季列表）
                html += `<div class="tv-show-header" onclick="App.MediaLibrary.toggleShowExpand('${show.tmdb_id}')">`;
                html += `<img class="show-poster" src="${posterUrl}" onerror="this.style.display='none'">`;
                html += `<div class="show-info">`;
                html += `<span class="show-title">${app.escapeHtml(displayTitle)} ${year ? '(' + year + ')' : ''}</span>`;
                html += `<span class="show-seasons-count" title="${app.escapeHtml(seasonSummary)}">${seasonNumbers.length} 季 · ${seasonSummary}</span>`;
                html += `</div>`;
                if (selectorMode === 'show') {
                    html += `<button class="select-show-btn success" style="margin-left:auto;" data-show='${JSON.stringify(show).replace(/'/g, "&apos;")}'>选择此剧集</button>`;
                }
                html += `<span class="expand-icon">${isShowExpanded ? '▼' : '▶'}</span>`;
                html += `</div>`;

                // 季列表（默认随剧集展开而可见）
                html += `<div class="tv-show-seasons" id="seasons-${show.tmdb_id}" style="display: ${isShowExpanded ? 'block' : 'none'};">`;
                seasonNumbers.forEach(seasonNum => {
                    const seasonData = seasons[seasonNum];
                    const episodes = seasonData.episodes || [];
                    const seasonKey = `${show.tmdb_id}-${seasonNum}`;
                    const isSeasonExpanded = expandedSeasons.has(seasonKey);

                    html += `<div class="season-item">`;
                    // 季标题行（点击展开/折叠集数）
                    html += `<div class="season-header" onclick="App.MediaLibrary.toggleSeasonExpand('${seasonKey}')">`;
                    html += `<span class="season-title">第 ${seasonNum} 季 (${episodes.length} 集)</span>`;
                    if (selectorMode === 'season' || selectorMode === 'target') {
                        html += `<button class="select-season-btn success" style="margin-left:10px;" data-show='${JSON.stringify(show).replace(/'/g, "&apos;")}' data-season="${seasonNum}">选择此季</button>`;
                    }
                    html += `<span class="expand-icon">${isSeasonExpanded ? '▼' : '▶'}</span>`;
                    html += `</div>`;

                    // 集数列表（默认折叠）
                    html += `<div class="season-episodes" id="episodes-${seasonKey}" style="display: ${isSeasonExpanded ? 'block' : 'none'};">`;
                    episodes.forEach(ep => {
                        const epMedia = {
                            media_type: 'tv', title: show.title, year: show.year,
                            season: seasonNum, episode: ep.episode,
                            target_path: ep.target_path, target_dir: ep.target_dir,
                            cache_key: ep.cache_key, tmdb_id: show.tmdb_id,
                        };
                        const epTitle = ep.title ? ` - ${ep.title}` : '';
                        html += `<div class="episode-item"><span>第 ${ep.episode} 集${epTitle}</span>`;
                        if (selectorMode === 'episode') {
                            html += `<button class="select-media-btn success" data-media='${JSON.stringify(epMedia).replace(/'/g, "&apos;")}'>选择</button>`;
                        }
                        html += `</div>`;
                    });
                    html += `</div></div>`;
                });
                html += `</div></div>`;
            });
            html += '</div></div>';
        }

        if (filteredMovies.length === 0 && filteredShows.length === 0) {
            html = '<div style="text-align:center; padding:20px;">没有匹配的媒体</div>';
        }

        container.innerHTML = html;
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
            const resp = await fetch('/api/media/library');
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
                container.innerHTML = '<div style="text-align:center; padding:20px; color:#dc3545;">加载媒体库失败</div>';
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
                container.innerHTML = '<div style="text-align:center; padding:20px; color:#dc3545;">加载媒体库失败</div>';
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
                container.innerHTML = '<div style="text-align:center; padding:20px; color:#dc3545;">加载媒体库失败</div>';
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
                container.innerHTML = '<div style="text-align:center; padding:20px; color:#dc3545;">加载媒体库失败</div>';
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
                container.innerHTML = '<div style="text-align:center; padding:20px; color:#dc3545;">加载媒体库失败</div>';
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
