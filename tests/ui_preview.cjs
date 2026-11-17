// Visual preview of the real templates/CSS/JS with every request mocked.
// Not part of `npm run test:ui`; it writes screenshots for manual review.
//   node tests/ui_preview.cjs [output directory]
// Environment: PLAYWRIGHT_MODULE, CHROMIUM_PATH, ANIMEMAN_TEST_PYTHON as in
// frontend_security.cjs. All data below is synthetic; nothing touches a real
// configuration, library, TMDB or AI endpoint.
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');

const root = process.env.ANIMEMAN_TEST_ROOT || path.resolve(__dirname, '..');
const python = process.env.ANIMEMAN_TEST_PYTHON || 'python3';
const out = path.resolve(process.argv[2] || path.join(root, 'outputs', 'ui-preview'));
const only = process.env.UI_PREVIEW_ONLY ? new RegExp(process.env.UI_PREVIEW_ONLY) : null;

const rendered = spawnSync(python, ['-c', `from jinja2 import Environment, FileSystemLoader
import sys
env=Environment(loader=FileSystemLoader(sys.argv[1]),autoescape=True)
print(env.get_template('index.html').render(url_for=lambda endpoint,filename:'/static/'+filename))`,
    path.join(root, 'templates')], {encoding: 'utf8'});
if (rendered.status !== 0) throw new Error(rendered.stderr);

// ---------- synthetic fixtures ----------
const now = 1794000000;
const hues = [212, 8, 150, 265, 32, 190, 330, 95];
function posterSvg(label, index) {
    const hue = hues[index % hues.length];
    return `<svg xmlns="http://www.w3.org/2000/svg" width="300" height="450" viewBox="0 0 300 450">
<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="hsl(${hue} 55% 62%)"/><stop offset="1" stop-color="hsl(${(hue + 40) % 360} 60% 30%)"/></linearGradient></defs>
<rect width="300" height="450" fill="url(#g)"/><circle cx="205" cy="190" r="78" fill="hsl(${hue} 80% 85%)" opacity=".55"/>
<path d="M0 340 L90 262 L160 320 L230 250 L300 312 V450 H0Z" fill="hsl(${(hue + 40) % 360} 50% 18%)" opacity=".7"/>
<text x="150" y="410" text-anchor="middle" font-family="sans-serif" font-size="26" font-weight="700" fill="#fff" opacity=".0">${label}</text></svg>`;
}
const movieTitles = ['星屑电报', '雨后的第七号车站', '纸飞机与远洋', '午夜放映员', '夏日尽头的灯塔',
    '一个名字特别特别长的剧场版标题：关于海、风与最后一封没有寄出的信'];
const movies = movieTitles.map((title, i) => ({
    cache_key: `/mnt/source/电影/${title} (20${18 + i})/${title}.mkv`, title, year: String(2018 + i),
    tmdb_id: 100 + i, processed_time: now - i * 3600, media_type: 'movie',
}));
function episodes(showTitle, season, count) {
    return Array.from({length: count}, (_, i) => ({
        cache_key: `/mnt/source/番剧/[字幕组] ${showTitle}/S${season}/[字幕组] ${showTitle} - ${String(i + 1).padStart(2, '0')} [1080p].mkv`,
        episode: i + 1, season, title: i % 3 === 0 ? `第 ${i + 1} 话 旅途的开始与漫长的告别` : '',
        target_path: `/library/tv/${showTitle}/Season ${season}/${showTitle} S0${season}E${String(i + 1).padStart(2, '0')}.mkv`,
        target_dir: `/library/tv/${showTitle}/Season ${season}`, processed_time: now - i * 600,
    }));
}
const showTitles = ['群青色的合唱', '机巧少女与旧书店', '月面便利店', '北方列车日记', '放课后天文部', '风平浪静的小镇'];
const shows = showTitles.map((title, i) => ({
    tmdb_id: 100 + i, title, year: String(2020 + i),   // IDs overlap movies on purpose
    seasons: i === 0 ? {0: {episodes: episodes(title, 0, 2)}, 1: {episodes: episodes(title, 1, 12)}, 2: {episodes: episodes(title, 2, 6)}}
        : {1: {episodes: episodes(title, 1, 12)}},
}));
const missingPosters = new Set(['movie/103', 'tv/104']);
const library = {movies, tv_shows: shows};
const logLines = [
    ['info', '开始扫描源文件夹 /mnt/source/番剧'], ['info', '发现 48 个视频文件，其中 31 个已在缓存中'],
    ['progress', '[1/17] [字幕组] 群青色的合唱 - 01 [1080p].mkv'], ['success', '已入库：群青色的合唱 S01E01'],
    ['progress', '[2/17] [字幕组] 群青色的合唱 - 02 [1080p].mkv'], ['success', '已入库：群青色的合唱 S01E02'],
    ['warning', 'TMDB 未返回中文标题，使用原始标题：Getsumen Konbini'],
    ['progress', '[3/17] [Raws] 月面便利店 OVA "特别篇" <BD>.mkv'], ['error', '识别失败：未找到匹配的 TMDB 条目，已记入失败缓存'],
    ['progress', '[4/17] 北方列车日记 - 第07话.mkv'], ['success', '已入库：北方列车日记 S01E07'],
    ['info', '字幕已链接：北方列车日记 S01E07.zh-CN.ass'],
].map(([level, msg], i) => ({level, msg, time: now + i * 4}));
const processedItems = Array.from({length: 9}, (_, i) => ({
    src: episodes(showTitles[i % 4], 1, 9)[i].cache_key,
    src_name: `[字幕组] ${showTitles[i % 4]} - ${String(i + 1).padStart(2, '0')} [1080p].mkv`,
    parent_dir: `[字幕组] ${showTitles[i % 4]}`, grandparent_dir: '番剧',
    target: `/library/tv/${showTitles[i % 4]}/Season 1/${showTitles[i % 4]} S01E0${i + 1}.mkv`, target_exists: i !== 4,
    title: showTitles[i % 4], tmdb_id: 100 + (i % 4), media_type: 'tv', season: i === 2 ? 0 : 1, episode: i + 1, year: '2024',
    confidence: i === 1 ? null : 96 - i * 7, confirmed_by_user: i === 3, processed_time: now - i * 900,
}));
const failedFiles = [
    {path: '/mnt/source/番剧/[Raws] 月面便利店/[Raws] 月面便利店 OVA "特别篇" <BD>.mkv', name: '[Raws] 月面便利店 OVA "特别篇" <BD>.mkv', reason: '未找到匹配的 TMDB 条目', failed_time: now},
    {path: '/mnt/source/番剧/[Raws] 月面便利店/NCOP.mkv', name: 'NCOP.mkv', reason: '文件名缺少可识别的集号', failed_time: now - 60},
];
const subtitles = [
    {path: '/mnt/subs/群青色的合唱/群青色的合唱 - 01.zh-CN.ass', name: '群青色的合唱 - 01.zh-CN.ass'},
    {path: '/mnt/subs/群青色的合唱/群青色的合唱 - 02.zh-CN.ass', name: '群青色的合唱 - 02.zh-CN.ass'},
    {path: '/mnt/subs/杂项/一个非常长的字幕文件名用来检查表格在窄屏下的换行与截断表现 [简繁内封] v2.ass', name: '一个非常长的字幕文件名用来检查表格在窄屏下的换行与截断表现 [简繁内封] v2.ass'},
    {path: '/mnt/subs/杂项/unknown_03.srt', name: 'unknown_03.srt'},
];
const matchResults = subtitles.map((subtitle, i) => ({
    subtitle: i === 1 ? {...subtitle, processed_info: {title: '群青色的合唱', media_type: 'tv', season: 1, episode: 2, target_exists: true, target: '/library/tv/x.mkv'}} : subtitle,
    best_match: i === 0 || i === 2 ? {score: i === 0 ? 96 : 71, media: {media_type: 'tv', title: i === 0 ? '群青色的合唱' : '北方列车日记', season: 1, episode: i + 1, target_path: '/library/tv/x.mkv', target_dir: '/library/tv'}} : null,
    candidates: [],
}));
const baseConfig = {
    source_folders: ['/mnt/source/番剧', '/mnt/source/电影'], tv_target_folder: '/library/tv', movie_target_folder: '/library/movies',
    environment_managed: ['tv_target_folder'], link_type: 'hard', dry_run: false, incremental: true, max_workers: 3,
    video_extensions: ['.mkv', '.mp4', '.avi', '.ts'], ignore_patterns: ['sample', 'trailer'],
    tmdb_api: {api_key: '', api_key_configured: true, language: 'zh-CN', proxy: ''},
    ai_parser: {enabled: true, api_key: '', api_key_configured: true, provider: 'deepseek', model: 'deepseek-flash', base_url: 'https://api.example.invalid'},
    ai_plot_enhance: {enabled: false, api_key: '', api_key_configured: false},
    auth: {enabled: true, username: 'admin', password: '', password_configured: true},
    subtitle: {enabled: true}, subtitle_center: {default_source_folder: '/mnt/subs', auto_match_threshold: 75},
};
const emptyConfig = {source_folders: [], tmdb_api: {}, ai_parser: {}, ai_plot_enhance: {}, auth: {}};
const statuses = {
    idle: {running: false, status: 'idle', progress: 0, total: 0, log: []},
    running: {running: true, status: 'running', task_id: 'preview', progress: 4, total: 17, message: '', log: logLines},
    stopping: {running: true, status: 'stopping', task_id: 'preview', progress: 4, total: 17, message: '', log: logLines},
    completed: {running: false, status: 'completed', progress: 17, total: 17, result: {success: 15, failed: 2}, message: '', log: logLines},
    failed: {running: false, status: 'failed', progress: 6, total: 17, result: {success: 5, failed: 1}, message: '源文件夹不可读', log: logLines},
    preview: {running: false, status: 'completed', progress: 17, total: 17, result: {success: 17, failed: 0}, message: '模拟运行完成，未修改任何文件', log: logLines},
};

async function open(browser, {viewport, status = 'running', config = baseConfig, lib = library, overrides = {}, scheme = 'light', density}) {
    const context = await browser.newContext({viewport, deviceScaleFactor: viewport.width < 600 ? 2 : 1,
        colorScheme: scheme, hasTouch: viewport.width < 600, isMobile: viewport.width < 600});
    const page = await context.newPage();
    const consoleErrors = [];
    page.on('console', message => { if (message.type() === 'error') consoleErrors.push(message.text()); });
    page.on('pageerror', error => consoleErrors.push(String(error)));
    await page.addInitScript(() => { window.alert = () => {}; window.confirm = () => true; });
    if (density) await page.addInitScript(value => localStorage.setItem('animeman.density', value), density);
    await page.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url());
        if (url.origin !== 'http://animeman.test') return route.abort();
        if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: rendered.stdout});
        if (url.pathname.startsWith('/static/')) {
            const file = path.join(root, url.pathname);
            if (!file.startsWith(root + '/static/') || !fs.existsSync(file)) return route.abort();
            return route.fulfill({path: file});
        }
        const poster = url.pathname.match(/^\/media_poster\/(movie|tv)\/(\d+)$/);
        if (poster) {
            if (missingPosters.has(`${poster[1]}/${poster[2]}`)) return route.fulfill({status: 404, body: ''});
            const index = Number(poster[2]) - 100 + (poster[1] === 'tv' ? 3 : 0);
            const label = (poster[1] === 'tv' ? showTitles : movieTitles)[Number(poster[2]) - 100].slice(0, 6);
            return route.fulfill({contentType: 'image/svg+xml', body: posterSvg(label, index)});
        }
        if (!url.pathname.startsWith('/api/')) return route.abort();
        if (overrides[url.pathname]) return overrides[url.pathname](route, req);
        const data = {
            '/api/config': config, '/api/status': statuses[status],
            '/api/offline/status': {total_folders: 12, total_files: 148, cached_folders: 9},
            '/api/media/library': lib,
            '/api/processed_cache': {items: processedItems, total_pages: 3},
            '/api/failed_cache/clusters': {clusters: [
                {folder: '/mnt/source/番剧/[Raws] 月面便利店', count: 2, files: failedFiles},
                {folder: '/mnt/source/番剧/[字幕组] 一个文件夹名非常长的合集 [BDRip 1080p HEVC-10bit FLAC] Vol.1-6', count: 3, files: [
                    {path: '/x/1.mkv', name: 'SP01.mkv', reason: '未找到匹配的 TMDB 条目'}, {path: '/x/2.mkv', name: 'SP02.mkv', reason: '未找到匹配的 TMDB 条目'},
                    {path: '/x/3.mkv', name: 'Menu.mkv', reason: '文件名缺少可识别的集号'}]},
                {folder: '/mnt/source/电影/午夜放映员 导演剪辑版', count: 1, files: [{path: '/y/1.mkv', name: 'Director.Cut.mkv', reason: 'AI 返回的年份与 TMDB 不一致'}]}]},
            '/api/failed_cache': {failed: failedFiles},
            '/api/tmdb/search_proxy': {results: shows.slice(0, 5).map((s, i) => ({id: s.tmdb_id, title: s.title, year: s.year, media_type: 'tv',
                poster_url: i === 4 ? null : `/media_poster/tv/${s.tmdb_id}`,
                seasons_detail: [...(i === 0 ? [{season_number: 0, episode_count: 2, name: '特别篇'}] : []), {season_number: 1, episode_count: 12, name: '第 1 季'},
                    ...(i < 2 ? [{season_number: 2, episode_count: 6, name: '第 2 季'}] : [])]}))},
            '/api/special_mappings': {mappings: [
                {keyword: '[OVA] 月面便利店 特别篇', tmdb_id: 102, media_type: 'tv', season: 0, episode: 1, enabled: true},
                {keyword: '午夜放映员 导演剪辑版', tmdb_id: 103, media_type: 'movie', enabled: false}]},
            '/api/recognition_rules': {rules: [
                {id: 'preview-rule', enabled: true, scope: 'series', path: '/mnt/source/番剧/群青色的合唱', media_type: 'tv', tmdb_id: 100}]},
            '/api/recognition_aliases': {aliases: [
                {name: 'Gunjou no Chorus', media_type: 'tv', tmdb_id: 100, scope: '/mnt/source/番剧/群青色的合唱'}]},
            '/api/numbering_maps': {rules: [
                {id: 'preview-numbering', enabled: true, kind: 'range', start: 13, end: 24,
                    scope: '/mnt/source/番剧/群青色的合唱', tmdb_id: 100, season: 2, episode: 1}]},
            '/api/drives': [{path: '/mnt', name: '/mnt'}, {path: '/library', name: '/library'}],
            '/api/browse': {current: '/mnt/source/番剧/一个很长很长的目录名称 用来检查路径在弹窗里的换行 [BDRip 1080p HEVC-10bit FLAC]', parent: '/mnt/source',
                dirs: ['[字幕组] 群青色的合唱', '[字幕组] 机巧少女与旧书店', '[Raws] 月面便利店', '北方列车日记 (2023)'].map(name => ({name, path: '/mnt/source/番剧/' + name}))},
            '/api/subtitle/scan': {subtitles},
        }[url.pathname] || {status: 'success'};
        return route.fulfill({json: data});
    });
    await page.goto('http://animeman.test/');
    await page.waitForFunction(() => window.App && App.configCache && Object.keys(App.configCache).length > 0);
    await page.evaluate(() => { clearInterval(App.statusInterval); });
    await page.waitForTimeout(250);
    return {page, context, consoleErrors};
}

// Works for both the old single-page layout and the tabbed shell.
async function go(page, view) {
    const tab = page.locator(`[data-view-target="${view}"]:visible`).first();
    if (await tab.count()) await tab.click();
    await page.waitForTimeout(200);
}

const desktop = {width: 1440, height: 900}, tablet = {width: 768, height: 1024}, phone = {width: 390, height: 844};
const scenes = [
    ['home-running', {status: 'running'}, async page => go(page, 'home')],
    ['home-stopping', {status: 'stopping'}, async page => go(page, 'home')],
    ['home-failed', {status: 'failed'}, async page => go(page, 'home')],
    ['home-preview-done', {status: 'preview'}, async page => go(page, 'home')],
    ['home-first-run', {status: 'idle', config: emptyConfig, lib: {movies: [], tv_shows: []}}, async page => {
        await page.evaluate(() => { localStorage.removeItem('onboardingDismissed'); App.Config.checkOnboarding(); });
        await go(page, 'home');
    }],
    ['home-idle', {status: 'idle'}, async page => go(page, 'home')],
    ['library', {status: 'completed'}, async page => go(page, 'library')],
    ['library-compact', {status: 'idle', density: 'compact'}, async page => go(page, 'library')],
    ['library-compact-seasons', {status: 'idle', density: 'compact'}, async page => {
        await go(page, 'library');
        const toggle = page.locator('.season-toggle-btn').first();
        if (await toggle.count()) { await toggle.click(); await page.locator('[data-action="toggleSeasonEpisodes"]').nth(1).click(); }
    }],
    ['settings-compact', {status: 'idle', density: 'compact'}, async page => go(page, 'settings')],
    ['rules-user', {status: 'idle'}, async page => { await go(page, 'tools'); await page.locator('[data-rule-tab="user"]').click(); await page.waitForTimeout(200); }],
    ['rules-aliases', {status: 'idle'}, async page => { await go(page, 'tools'); await page.locator('[data-rule-tab="aliases"]').click(); await page.waitForTimeout(200); }],
    ['library-spotlight', {status: 'idle'}, async page => {
        await go(page, 'library');
        const thumb = page.locator('.spotlight-thumb').nth(1);
        if (await thumb.count()) { await thumb.click(); await page.mouse.move(0, 0); }
    }],
    ['library-seasons', {status: 'completed'}, async page => {
        await go(page, 'library');
        const toggle = page.locator('.season-toggle-btn').first();
        if (await toggle.count()) { await toggle.click(); await page.locator('[data-action="toggleSeasonEpisodes"]').nth(1).click(); }
    }],
    ['library-selected', {status: 'idle'}, async page => {
        await go(page, 'library');
        for (const index of [0, 2]) await page.locator('.movie-card input').nth(index).check();
        const thumb = page.locator('.spotlight-thumb').nth(1);
        if (await thumb.count()) await thumb.click();
    }],
    ['library-filter-empty', {status: 'idle'}, async page => {
        await go(page, 'library');
        await page.locator('#mediaLibrarySearchInput').fill('不存在的标题');
    }],
    ['library-empty', {status: 'idle', lib: {movies: [], tv_shows: []}}, async page => go(page, 'library')],
    ['subtitles-scanned', {status: 'idle'}, async (page) => {
        await go(page, 'subtitles');
        await page.evaluate(results => { App.scannedSubtitles = results.map(r => r.subtitle);
            App.matchResults = results.map(r => ({subtitle: r.subtitle, candidates: [], best_match: null})); App.SubtitleCenter.renderMatchTable(); }, matchResults);
    }],
    ['subtitles', {status: 'idle'}, async (page) => {
        await go(page, 'subtitles');
        await page.evaluate(results => { App.scannedSubtitles = results.map(r => r.subtitle); App.matchResults = results; App.SubtitleCenter.renderMatchTable(); }, matchResults);
    }],
    ['tools', {status: 'idle'}, async page => go(page, 'tools')],
    ['home-log-errors', {status: 'completed'}, async page => {
        await go(page, 'home');
        await page.locator('[data-log-filter="error"]').click();
    }],
    ['settings-dirty', {status: 'idle'}, async page => {
        await go(page, 'settings');
        await page.locator('[data-scroll-to="cfgAiTitle"]').click();
        await page.locator('#aiModelInput').fill('deepseek-chat');
    }],
    ['settings', {status: 'idle'}, async page => go(page, 'settings')],
    ['modal-correction', {status: 'idle'}, async page => {
        await page.evaluate(file => App.Correction.openCorrectionModal(file.path, file.name), failedFiles[0]);
        await page.locator('#tmdbSearchInput').fill('月面便利店');
        await page.evaluate(() => App.Correction.searchTmdbForCorrection());
        await page.locator('#tmdbResultsBody button').first().click();
    }],
    ['modal-processed-cache', {status: 'idle'}, async page => {
        await page.evaluate(() => App.ProcessedCache.viewProcessedCache());
        await page.locator('.processed-cache-checkbox').first().check();
    }],
    ['modal-failed-cache', {status: 'idle'}, async page => {
        await page.evaluate(() => App.FailedCache.viewFailedCache());
        await page.locator('#failedCacheList button').first().waitFor();
    }],
    ['modal-failed-files', {status: 'idle'}, async page => {
        await page.evaluate(() => App.FailedCache.viewFailedCache());
        await page.locator('#failedCacheList button').filter({hasText: '查看失败文件'}).nth(1).click();
    }],
    ['modal-batch-search', {status: 'idle'}, async page => {
        await page.evaluate(files => App.BatchCorrection.openModalWithFiles('媒体库选中项', files),
            episodes('群青色的合唱', 1, 3).map(e => ({path: e.cache_key, name: e.cache_key.split('/').pop()})));
        await page.locator('#batchTmdbSearchInput').fill('群青');
        await page.evaluate(() => App.BatchCorrection.searchTmdb());
        await page.locator('#batchTmdbResults .tmdb-card').nth(1).click();
    }],
    ['modal-browse', {status: 'idle'}, async page => {
        await page.evaluate(() => App.Browse.openBrowser('source'));
        await page.locator('#dirList li').first().click();
    }],
    ['modal-batch', {status: 'idle'}, async page => {
        await page.evaluate(files => App.BatchCorrection.openModalWithFiles('媒体库选中项', files),
            episodes('群青色的合唱', 1, 5).map(e => ({path: e.cache_key, name: e.cache_key.split('/').pop()})));
    }],
    ['modal-media-select', {status: 'idle'}, async page => {
        await page.evaluate(() => App.MediaLibrary.showTargetSelector(() => {}));
        await page.locator('#mediaLibraryContainer .tv-show-card').first().waitFor();
    }],
    ['error-500', {status: 'idle', overrides: {'/api/failed_cache/correct': route => route.fulfill({status: 500, json: {message: '磁盘空间不足'}})}}, async page => {
        await page.evaluate(file => { App.Correction.openCorrectionModal(file.path, file.name); App.Correction.selectTmdbForCorrection(102, '月面便利店', 'tv'); }, failedFiles[0]);
        await page.evaluate(() => App.Correction.executeCorrection());
    }],
];

(async () => {
    fs.mkdirSync(out, {recursive: true});
    const browser = await chromium.launch({headless: true,
        ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {}), args: ['--no-sandbox']});
    const problems = [];
    const targets = [['desktop', desktop, 'light'], ['phone', phone, 'light'], ['tablet', tablet, 'light'], ['desktop-dark', desktop, 'dark'], ['phone-dark', phone, 'dark']];
    for (const [device, viewport, scheme] of targets) {
        for (const [name, options, act] of scenes) {
            const id = `${device}-${name}`;
            if (only && !only.test(id)) continue;
            if (!only && device === 'tablet' && !/^(home-running|library|library-compact|settings)$/.test(name)) continue;
            if (!only && /dark/.test(device) && !/^(home-running|home-idle|library|library-compact|library-spotlight|library-seasons|settings|modal-correction|modal-failed-cache|subtitles|rules-user)$/.test(name)) continue;
            const {page, context, consoleErrors} = await open(browser, {viewport, scheme, ...options});
            try {
                await act(page);
                await page.waitForTimeout(350);
                if (!name.startsWith('modal') && !name.startsWith('error')) {
                    // Grow the viewport to the page height so sticky bars sit where they belong.
                    await page.evaluate(() => window.scrollTo(0, 0));
                    const height = await page.evaluate(() => document.documentElement.scrollHeight);
                    if (height > viewport.height) await page.setViewportSize({width: viewport.width, height: Math.min(height, 6000)});
                    await page.waitForTimeout(150);
                }
                await page.screenshot({path: path.join(out, id + '.png')});
                const toast = await page.locator('.app-toast-error').allTextContents();
                if (!name.startsWith('error') && toast.length) problems.push(`${id}: unexpected error toast ${toast.join(' | ')}`);
                const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
                if (overflow > 1) problems.push(`${id}: page overflows horizontally by ${overflow}px`);
            } catch (error) {
                problems.push(`${id}: ${error.message.split('\n')[0]}`);
            }
            // Mocked 404/500 responses are expected to be logged by the browser.
            const unexpected = consoleErrors.filter(text => !/Failed to load resource/.test(text));
            if (unexpected.length) problems.push(`${id}: console ${unexpected.join(' | ')}`);
            await context.close();
        }
    }
    await browser.close();
    console.log(`screenshots: ${out}`);
    if (problems.length) { console.log(problems.join('\n')); process.exitCode = 1; }
    else console.log('no horizontal overflow, no unexpected console errors');
})();
