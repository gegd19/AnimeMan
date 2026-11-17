// Real Chromium checks for the navigation shell: views, task bar, dialogs, theme
// and layout. Same harness idea as frontend_security.cjs — actual Jinja templates,
// actual CSS/JS, every request intercepted, synthetic data only.
const {test, before, after} = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const {spawnSync} = require('node:child_process');
const {chromium} = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const root = process.env.ANIMEMAN_TEST_ROOT || path.resolve(__dirname, '..');
const python = process.env.ANIMEMAN_TEST_PYTHON || 'python3';
const rendered = spawnSync(python, ['-c', `from jinja2 import Environment, FileSystemLoader
import sys
env=Environment(loader=FileSystemLoader(sys.argv[1]),autoescape=True)
print(env.get_template('index.html').render(url_for=lambda endpoint,filename:'/static/'+filename))`, path.join(root, 'templates')], {encoding: 'utf8'});
if (rendered.status !== 0) throw new Error(rendered.stderr);

let browser;
before(async () => { browser = await chromium.launch({headless: true,
    ...(process.env.CHROMIUM_PATH ? {executablePath: process.env.CHROMIUM_PATH} : {}), args: ['--no-sandbox']}); });
after(async () => { await browser?.close(); });

const secret = 'sk-synthetic-never-stored';
const movie = {cache_key: '/src/电影 "A".mkv', title: '没有海报的电影', year: '2024', tmdb_id: 9, processed_time: 1};
const episode = {cache_key: '/src/剧 S01E01.mkv', episode: 1, season: 1, title: '', target_path: '/lib/a.mkv', target_dir: '/lib', processed_time: 1};
const show = {tmdb_id: 9, title: '同 ID 的剧集', year: '2024', seasons: {1: {episodes: [episode]}}};
const logs = [{level: 'info', msg: '第一条', time: 100}, {level: 'error', msg: '第二条 <b>不是标签</b>', time: 101}];

async function setup(t, {overrides = {}, viewport = {width: 1280, height: 800}, config = {}, status, device = {}} = {}) {
    const context = await browser.newContext({viewport, ...device});
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    t.after(() => context.close());
    const requests = [], pageErrors = [];
    page.on('pageerror', error => pageErrors.push(String(error)));
    await page.addInitScript(() => { window.confirm = () => true; });
    const state = {status: status || {running: false, status: 'idle', progress: 0, total: 0, log: []}};
    await page.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url());
        if (url.origin !== 'http://animeman.test') return route.abort();
        if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: rendered.stdout});
        if (url.pathname.startsWith('/static/')) {
            const file = path.join(root, url.pathname);
            if (!file.startsWith(root + '/static/') || !fs.existsSync(file)) return route.abort();
            return route.fulfill({path: file});
        }
        if (url.pathname.startsWith('/media_poster/')) return route.fulfill({status: 404, body: ''});
        if (!url.pathname.startsWith('/api/')) return route.abort();
        requests.push({url: url.pathname + url.search, method: req.method(), body: req.postDataJSON()});
        if (overrides[url.pathname]) return overrides[url.pathname](route, req);
        if (req.method() === 'POST' && url.pathname === '/api/config') return route.fulfill({json: {status: 'success'}});
        const data = {
            '/api/config': {source_folders: ['/src'], tv_target_folder: '/tv', movie_target_folder: '/movies',
                auth: {}, ai_parser: {}, ai_plot_enhance: {}, tmdb_api: {api_key: '', api_key_configured: true}, ...config},
            '/api/status': state.status,
            '/api/offline/status': {},
            '/api/media/library': {movies: [movie], tv_shows: [show]},
            '/api/special_mappings': {mappings: []},
            '/api/drives': [{path: '/src', name: '/src'}],
        }[url.pathname] || {status: 'success'};
        return route.fulfill({json: data});
    });
    await page.goto('http://animeman.test/');
    await page.waitForFunction(() => window.App && Object.keys(App.configCache || {}).length > 0);
    await page.evaluate(() => { clearInterval(App.statusInterval); });
    return {page, requests, pageErrors, state};
}
async function openView(page, view) {
    await page.locator(`[data-view-target="${view}"]`).click();
    await page.locator(`#view-${view}`).waitFor({state: 'visible'});
}
const views = ['home', 'library', 'subtitles', 'tools', 'settings'];
// Alias and numbering forms live in Tools → 识别规则; reach them by real clicks.
const ruleTabFor = {recognitionAliasesDetails: 'aliases', numberingMapsDetails: 'numbering'};
async function openRuleTab(page, panelId) {
    await openView(page, 'tools');
    await page.locator(`[data-rule-tab="${ruleTabFor[panelId]}"]`).click();
    await page.locator('#' + panelId).waitFor({state: 'visible'});
}

test('every panel is reachable from the navigation and exactly one is shown', async t => {
    const {page, pageErrors} = await setup(t);
    assert.equal(await page.locator('.view:visible').count(), 1);
    assert.equal(await page.locator('#view-home').isVisible(), true);
    for (const view of views) {
        await openView(page, view);
        assert.deepEqual(await page.locator('.view:visible').evaluateAll(nodes => nodes.map(node => node.dataset.view)), [view]);
        assert.equal(await page.locator(`[data-view-target="${view}"]`).getAttribute('aria-current'), 'page');
        assert.equal(await page.locator('[aria-current="page"]').count(), 1);
        assert.equal(await page.locator(`#view-${view} h1`).isVisible(), true);
    }
    // Entry points that used to sit in one long page are all still operable.
    const reachable = {home: ['#pauseLogsBtn', '#logBox'], library: ['#mediaLibrarySearchInput', '#mediaLibrarySortSelect'],
        subtitles: ['#subSourceFolderInput', '#matchThresholdInput'], tools: ['#mappingRulesTable', '#offlineScanBtn', '#testTitle'],
        settings: ['#configForm', '#tmdbKeyInput', '#authPasswordInput']};
    for (const [view, selectors] of Object.entries(reachable)) {
        await openView(page, view);
        for (const selector of selectors) assert.equal(await page.locator(selector).isVisible(), true, `${selector} visible in ${view}`);
    }
    assert.deepEqual(pageErrors, []);
});

test('switching views keeps form values, selections and deep links', async t => {
    const {page} = await setup(t);
    await openView(page, 'settings');
    await page.locator('#aiModelInput').fill('edited-but-unsaved');
    await page.locator('#dryRunCheck').check();
    await openView(page, 'library');
    await page.locator('.movie-card input').check();
    assert.equal(await page.locator('#mediaSelectedCount').textContent(), '1');
    await openView(page, 'subtitles');
    await page.locator('#subSourceFolderInput').fill('/subs/带 空格');
    await openView(page, 'home');
    await openView(page, 'settings');
    assert.equal(await page.locator('#aiModelInput').inputValue(), 'edited-but-unsaved');
    assert.equal(await page.locator('#dryRunCheck').isChecked(), true);
    await openView(page, 'library');
    assert.equal(await page.locator('.movie-card input').isChecked(), true);
    assert.equal(await page.locator('#mediaBatchDeleteBtn').isDisabled(), false);
    await openView(page, 'subtitles');
    assert.equal(await page.locator('#subSourceFolderInput').inputValue(), '/subs/带 空格');
    assert.equal(new URL(page.url()).hash, '#subtitles');
    await page.goto('http://animeman.test/#tools');
    await page.locator('#view-tools').waitFor({state: 'visible'});
    assert.equal(await page.locator('#view-home').isVisible(), false);
});

test('task bar stays visible and truthful in every view while stopping', async t => {
    const stopping = {running: true, status: 'stopping', task_id: 'current', progress: 2, total: 8, message: '', log: logs};
    const {page, requests} = await setup(t, {status: stopping});
    await page.evaluate(() => App.Task.updateStatus());
    for (const view of views) {
        await openView(page, view);
        assert.equal(await page.locator('#runBtn').isVisible(), true);
        assert.equal(await page.locator('#runBtn').isDisabled(), true, 'start stays disabled while stopping');
        assert.equal(await page.locator('#stopBtn').isDisabled(), true);
        assert.match(await page.locator('#statusText').textContent(), /正在停止/);
        assert.equal(await page.locator('#taskBar').getAttribute('data-state'), 'stopping');
    }
    assert.equal(await page.locator('#progressFill').evaluate(node => node.style.width), '25%');
    assert.equal(await page.locator('#taskProgress').getAttribute('aria-valuenow'), '25');
    assert.match(await page.locator('#taskPercent').textContent(), /2 \/ 8.*25%/);
    await page.evaluate(() => App.Task.stopTask());   // repeated stop is ignored, never forced
    assert.ok(requests.every(r => !r.url.includes('force=1')));
    assert.equal(requests.filter(r => r.url.startsWith('/api/stop')).length, 0);
});

test('stop uses the current task id and the summary shows only returned numbers', async t => {
    const {page, requests, state} = await setup(t, {status: {running: true, status: 'running', task_id: 'task/7 a', progress: 1, total: 4, log: []}});
    await page.evaluate(() => App.Task.updateStatus());
    assert.equal(await page.locator('#statProgress').textContent(), '1 / 4');
    assert.equal(await page.locator('#statSuccess').textContent(), '—', 'no result yet: no invented count');
    assert.equal(await page.locator('#statFailed').textContent(), '—');
    state.status = {running: true, status: 'stopping', task_id: 'task/7 a', progress: 1, total: 4, log: []};
    await page.locator('#stopBtn').click();
    await page.waitForFunction(() => document.getElementById('taskBar').dataset.state === 'stopping');
    assert.ok(requests.some(r => r.method === 'POST' && r.url === '/api/stop?task_id=' + encodeURIComponent('task/7 a')));
    state.status = {running: false, status: 'failed', task_id: 'task/7 a', progress: 1, total: 4, message: '<i>源目录不可读</i>',
        result: {success: 1, failed: 3}, log: []};
    await page.evaluate(() => App.Task.updateStatus());
    assert.equal(await page.locator('#taskBar').getAttribute('data-state'), 'failed');
    assert.match(await page.locator('#statusText').textContent(), /失败.*成功 1，失败 3.*<i>源目录不可读<\/i>/);
    assert.equal(await page.locator('#statusText i').count(), 0);
    assert.equal(await page.locator('#statSuccess').textContent(), '1');
    assert.equal(await page.locator('#statFailed').textContent(), '3');
    assert.equal(await page.locator('#runBtn').isDisabled(), false);
});

test('dry-run is labelled as a simulation only when the saved configuration says so', async t => {
    const normal = await setup(t);
    assert.equal(await normal.page.locator('#dryRunBadge').isVisible(), false);
    assert.equal(await normal.page.locator('#statMode').textContent(), '正式');
    const preview = await setup(t, {config: {dry_run: true}});
    assert.equal(await preview.page.locator('#dryRunBadge').isVisible(), true);
    assert.equal(await preview.page.locator('#statMode').textContent(), '模拟');
});

test('saving dry-run during a real task labels configuration without promising the active task is simulated', async t => {
    let savedDryRun = false;
    const {page, requests} = await setup(t, {
        viewport: {width: 375, height: 700},
        status: {running: true, status: 'running', task_id: 'already-writing', progress: 1, total: 4, log: []},
        overrides: {'/api/config': (route, req) => {
            if (req.method() === 'POST') {
                savedDryRun = req.postDataJSON().dry_run;
                return route.fulfill({json: {status: 'success'}});
            }
            return route.fulfill({json: {source_folders: ['/src'], tv_target_folder: '/tv', movie_target_folder: '/movies',
                auth: {}, ai_parser: {}, ai_plot_enhance: {}, tmdb_api: {api_key: '', api_key_configured: true}, dry_run: savedDryRun}});
        }}
    });
    await openView(page, 'settings');
    await page.locator('#dryRunCheck').check();
    await page.locator('#configForm .savebar button').click();
    await page.locator('#dryRunBadge').waitFor({state: 'visible'});
    assert.match(await page.locator('#dryRunBadge').textContent(), /已保存.*模拟/);
    assert.match(await page.locator('#dryRunBadge').getAttribute('title'), /启动时.*配置/);
    await openView(page, 'home');
    assert.match(await page.locator('#statMode').evaluate(node => node.parentElement.querySelector('dt').textContent), /已保存配置/);
    assert.match(await page.locator('#statusText').textContent(), /运行中/);
    assert.equal(await page.locator('#runBtn').isDisabled(), true);
    assert.equal(await page.locator('#statusText').evaluate(node => {
        const range = document.createRange();
        range.setStart(node.firstChild, 0); range.setEnd(node.firstChild, 3);
        const box = node.getBoundingClientRect();
        return [...range.getClientRects()].every(part => part.bottom <= box.bottom + 1 && part.right <= box.right + 1);
    }), true, 'the active task label remains readable beside the saved-configuration badge on a phone');
    assert.equal(requests.filter(req => req.url.startsWith('/api/run') || req.url.startsWith('/api/stop')).length, 0);
});

test('environment-managed paths are really read-only and explained', async t => {
    const {page} = await setup(t, {config: {environment_managed: ['tv_target_folder']}});
    await openView(page, 'settings');
    assert.equal(await page.locator('#tvTargetFolderInput').evaluate(node => node.readOnly), true);
    assert.equal(await page.locator('#tvBrowseButton').isDisabled(), true);
    assert.equal(await page.locator('#movieTargetFolderInput').evaluate(node => node.readOnly), false);
    assert.match(await page.locator('#environmentPathNote').textContent(), /剧集目标.*环境变量/);
    assert.equal(await page.locator('#environmentPathNote').isVisible(), true);
    await page.locator('#tvTargetFolderInput').focus();
    await page.keyboard.type('x');
    assert.equal(await page.locator('#tvTargetFolderInput').inputValue(), '/tv');
});

test('secrets stay out of the page and out of browser storage', async t => {
    const {page, requests} = await setup(t);
    await openView(page, 'settings');
    assert.equal(await page.locator('#tmdbKeyInput').inputValue(), '');
    assert.match(await page.locator('#tmdbKeyInput').getAttribute('placeholder'), /已配置/);
    await page.locator('#tmdbKeyInput').fill(secret);
    await page.locator('#authPasswordInput').fill(secret);
    await page.locator('[data-theme-choice="dark"]').click();
    await page.locator('#configForm .savebar button').click();
    await page.waitForFunction(() => document.querySelector('.app-toast-success'));
    const saved = requests.find(r => r.method === 'POST' && r.url === '/api/config').body;
    assert.equal(saved.tmdb_api.api_key, secret);
    assert.deepEqual(saved.clear_secrets, []);
    const stored = await page.evaluate(() => JSON.stringify({...localStorage}) + JSON.stringify({...sessionStorage}));
    assert.ok(!stored.includes(secret), 'no secret in storage');
    assert.deepEqual(await page.evaluate(() => Object.keys(localStorage).sort()), ['animeman.theme']);
    assert.equal(await page.locator('#tmdbKeyInput').inputValue(), '', 'reloaded form is redacted again');
    // Buttons inside the form never submit or reload it.
    assert.equal(await page.locator('#configForm button:not([type="button"])').count(), 0);
});

test('dialogs are named, trap focus, close on Escape and give focus back', async t => {
    const {page} = await setup(t);
    await openView(page, 'settings');
    await page.locator('#sourceBrowseButton').click();
    const dialog = page.locator('#browseModal');
    await page.waitForFunction(() => document.activeElement?.closest('#browseModal'));
    assert.equal(await dialog.getAttribute('role'), 'dialog');
    assert.equal(await dialog.getAttribute('aria-modal'), 'true');
    assert.equal(await page.locator('#' + await dialog.getAttribute('aria-labelledby')).textContent(), '选择文件夹');
    for (let i = 0; i < 12; i++) {
        await page.keyboard.press('Tab');
        assert.equal(await page.evaluate(() => !!document.activeElement.closest('#browseModal')), true, 'Tab stays inside the dialog');
    }
    await page.keyboard.press('Shift+Tab');
    assert.equal(await page.evaluate(() => !!document.activeElement.closest('#browseModal')), true);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => document.getElementById('browseModal').style.display === 'none');
    await page.waitForFunction(() => document.activeElement?.id === 'sourceBrowseButton');
    assert.equal(await page.evaluate(() => document.documentElement.classList.contains('modal-open')), false);
    for (const id of await page.locator('.modal').evaluateAll(nodes => nodes.map(node => node.id))) {
        const modal = page.locator('#' + id);
        assert.equal(await modal.getAttribute('role'), 'dialog', id);
        assert.ok((await page.locator('#' + await modal.getAttribute('aria-labelledby')).textContent()).trim(), id + ' has a name');
        assert.equal(await modal.locator('.modal-close[aria-label]').count(), 1, id + ' has a labelled close button');
    }
});

test('stacked dialogs close one at a time and keyboard reaches scripted rows', async t => {
    const {page} = await setup(t, {overrides: {
        '/api/failed_cache/clusters': route => route.fulfill({json: {clusters: [{folder: '/src', count: 1, files: [{path: '/src/a.mkv', name: 'a.mkv'}]}]}}),
        '/api/browse': route => route.fulfill({json: {current: '/src', parent: null, dirs: []}})}});
    await page.locator('.link-row').first().click();
    await page.locator('#failedCacheList button').filter({hasText: '查看失败文件'}).click();
    await page.locator('#failedCacheList button.warning').click();
    await page.waitForFunction(() => App.Shell.openModalCount() === 2);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => App.Shell.openModalCount() === 1);
    assert.equal(await page.locator('#correctionModal').isVisible(), false);
    assert.equal(await page.locator('#failedCacheModal').isVisible(), true);
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => App.Shell.openModalCount() === 0);
    // Folder rows are created by script; they must work from the keyboard too.
    await page.evaluate(() => App.Browse.openBrowser('source'));
    await page.locator('#dirList li').waitFor();
    await page.locator('#dirList li').focus();
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => App.currentBrowsePath === '/src');
});

test('log lines are text, pause holds the view and clear survives the next poll', async t => {
    const {page, state} = await setup(t, {status: {running: true, status: 'running', task_id: 't', progress: 1, total: 2, log: logs}});
    await page.evaluate(() => App.Task.updateStatus());
    assert.equal(await page.locator('#logBox .log-line').count(), 2);
    assert.equal(await page.locator('#logBox .log-error .log-msg').textContent(), '第二条 <b>不是标签</b>');
    assert.equal(await page.locator('#logBox b').count(), 0);
    await page.locator('#pauseLogsBtn').click();
    assert.equal(await page.locator('#pauseLogsBtn').textContent(), '恢复日志');
    state.status = {...state.status, log: [...logs, {level: 'success', msg: '第三条', time: 102}]};
    await page.evaluate(() => App.Task.updateStatus());
    assert.equal(await page.locator('#logBox .log-line').count(), 2, 'paused view does not move');
    await page.locator('#pauseLogsBtn').click();
    assert.equal(await page.locator('#logBox .log-line').count(), 3);
    await page.getByRole('button', {name: '清空日志'}).click();
    await page.evaluate(() => App.Task.updateStatus());
    assert.equal(await page.locator('#logBox .log-line').count(), 0, 'cleared lines do not come back');
    state.status = {...state.status, log: [...state.status.log, {level: 'info', msg: '第四条', time: 103}]};
    await page.evaluate(() => App.Task.updateStatus());
    assert.deepEqual(await page.locator('#logBox .log-msg').allTextContents(), ['第四条']);
});

test('errors are announced as alerts and a failed start does not look like success', async t => {
    const {page} = await setup(t, {overrides: {'/api/run': route => route.fulfill({status: 409, json: {message: '已有任务在运行'}})}});
    await page.locator('#runBtn').click();
    const toast = page.locator('.app-toast');
    await toast.waitFor();
    assert.equal(await toast.getAttribute('role'), 'alert');
    assert.match(await toast.textContent(), /冲突.*HTTP 409.*已有任务在运行/);
    await page.waitForFunction(() => !document.getElementById('runBtn').disabled);
    assert.doesNotMatch(await page.locator('#statusText').textContent(), /运行中|启动中/);
});

test('missing posters show a labelled placeholder and typed poster URLs are kept', async t => {
    const {page} = await setup(t);
    await openView(page, 'library');
    await page.locator('#movieGrid .movie-card').waitFor();
    assert.equal(await page.locator('#movieGrid img').getAttribute('src'), '/media_poster/movie/9');
    assert.equal(await page.locator('#showGrid img').getAttribute('src'), '/media_poster/tv/9');
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#movieGrid img')).display === 'none');
    assert.match(await page.locator('#movieGrid .media-card-poster').evaluate(node => getComputedStyle(node, '::after').content), /暂无海报/);
    const box = await page.locator('#movieGrid .media-card-poster').boundingBox();
    assert.ok(box.height > box.width, 'placeholder keeps the poster shape');
    // Card actions stay out of the artwork until wanted, but never depend on hover alone:
    // keyboard focus inside the card reveals them, and so does selecting the card.
    const actions = page.locator('#movieGrid .media-card-actions');
    const opacity = () => actions.evaluate(node => getComputedStyle(node).opacity);
    await page.mouse.move(0, 0);
    assert.equal(await opacity(), '0');
    await actions.locator('button').first().focus();
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#movieGrid .media-card-actions')).opacity === '1');
    await page.locator('#view-library h1').click();
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#movieGrid .media-card-actions')).opacity === '0');
    await page.locator('.movie-card input').check();
    await page.mouse.move(0, 0);
    await page.waitForFunction(() => getComputedStyle(document.querySelector('#movieGrid .media-card-actions')).opacity === '1');
});

// ---------- media library: spotlight, poster wall, inline seasons, selection bar ----------
const evil = '<img src=x onerror="window.__xss=1">最新的剧';
const ep = (showTitle, season, number, time) => ({cache_key: `/src/${showTitle}/S${season}/第 ${number} 话 "a".mkv`, episode: number, season,
    title: '', target_path: '/lib/x.mkv', target_dir: '/lib', processed_time: time});
const bigLibrary = () => ({
    movies: [{cache_key: '/src/老电影.mkv', title: '老电影', year: '1999', tmdb_id: 5, processed_time: 10},
             {cache_key: '/src/新电影 & co.mkv', title: '新电影', year: '2024', tmdb_id: 6, processed_time: 900}],
    tv_shows: [
        {tmdb_id: 6, title: evil, year: '2025', seasons: {0: {episodes: [ep('e', 0, 1, 950)]}, 1: {episodes: [ep('e', 1, 1, 1000), ep('e', 1, 2, 990)]}}},
        ...Array.from({length: 70}, (_, i) => ({tmdb_id: 100 + i, title: `剧集 ${String(i).padStart(2, '0')}`, year: '2020',
            seasons: {1: {episodes: [ep(`s${i}`, 1, 1, 500 - i)]}}})),
    ],
});
const withLibrary = library => ({'/api/media/library': route => route.fulfill({json: library})});
async function waitForRequest(page, requests, url, action) {
    const before = requests.length;
    await action();
    await page.waitForFunction(() => true);
    for (let i = 0; i < 50 && !requests.slice(before).some(r => r.url === url); i++) await page.waitForTimeout(40);
    const hit = requests.slice(before).find(r => r.url === url);
    assert.ok(hit, `${url} was requested`);
    return hit.body;
}

test('library spotlight shows the newest real item as text and follows the thumbnails', async t => {
    const {page, pageErrors} = await setup(t, {overrides: withLibrary(bigLibrary())});
    await openView(page, 'library');
    const spotlight = page.locator('#librarySpotlight');
    await spotlight.waitFor();
    assert.equal(await spotlight.locator('.spotlight-title').textContent(), evil);
    assert.equal(await spotlight.locator('.spotlight-title img').count(), 0);
    assert.equal(await page.evaluate(() => window.__xss), undefined);
    assert.match(await spotlight.locator('.spotlight-meta').textContent(), /剧集.*2025.*2 季 3 集/);
    assert.equal(await spotlight.locator('.spotlight-backdrop').getAttribute('src'), '/media_poster/tv/6');
    assert.equal(await spotlight.locator('[onclick], [onerror]').count(), 0);
    // Counts come from the response: 2 movies, 71 shows, 3 + 70 episodes.
    assert.equal((await page.locator('#libraryStats').textContent()).replace(/\s+/g, ' ').trim(), '2 部电影 71 部剧集 73 集');
    assert.equal(await spotlight.locator('.spotlight-thumb').count(), 8);
    // Second most recent is the movie that shares TMDB id 6 with the show: typed poster, movie actions.
    await spotlight.locator('.spotlight-thumb').nth(1).click();
    assert.equal(await spotlight.locator('.spotlight-title').textContent(), '新电影');
    assert.equal(await spotlight.locator('.spotlight-backdrop').getAttribute('src'), '/media_poster/movie/6');
    assert.equal(await spotlight.locator('.spotlight-thumb').nth(1).getAttribute('aria-pressed'), 'true');
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('spotlight-thumb')), true);
    // Filtering puts results first: the spotlight steps aside and comes back when the filter is cleared.
    await page.locator('#mediaLibrarySearchInput').fill('没有这个标题');
    assert.equal(await spotlight.isVisible(), false);
    assert.match(await page.locator('#mediaLibraryManagerContainer').textContent(), /没有符合条件的条目.*没有这个标题/);
    await page.getByRole('button', {name: '清除过滤'}).click();
    assert.equal(await page.locator('#mediaLibrarySearchInput').inputValue(), '');
    assert.equal(await spotlight.isVisible(), true);
    assert.deepEqual(pageErrors, []);
});

test('spotlight and whole-show actions confirm first and never delete sources', async t => {
    const {page, requests} = await setup(t, {overrides: withLibrary(bigLibrary())});
    await openView(page, 'library');
    await page.locator('#librarySpotlight .spotlight-thumb').nth(1).click();
    await page.evaluate(() => { window.__confirms = []; window.confirm = message => { window.__confirms.push(message); return false; }; });
    await page.locator('#librarySpotlight').getByRole('button', {name: '删除'}).click();
    assert.equal(await page.evaluate(() => window.__confirms.length), 1);
    assert.equal(requests.filter(r => r.url === '/api/media/delete').length, 0, 'cancel sends nothing');
    await page.evaluate(() => { window.confirm = message => { window.__confirms.push(message); return true; }; });
    let body = await waitForRequest(page, requests, '/api/media/delete', () => page.locator('#librarySpotlight').getByRole('button', {name: '删除'}).click());
    assert.deepEqual(body, {src_path: '/src/新电影 & co.mkv', delete_source: false});

    await page.locator('#librarySpotlight .spotlight-thumb').first().click();
    await page.locator('#librarySpotlight').getByRole('button', {name: '查看季集'}).click();
    const panel = page.locator('.show-seasons-panel');
    await panel.waitFor();
    assert.equal(await panel.locator('.show-panel-title strong').textContent(), evil);
    body = await waitForRequest(page, requests, '/api/media/batch_delete', () => panel.getByRole('button', {name: '整部删除'}).click());
    assert.equal(body.delete_source, false);
    assert.deepEqual(body.src_paths.sort(), ['/src/e/S0/第 1 话 "a".mkv', '/src/e/S1/第 1 话 "a".mkv', '/src/e/S1/第 2 话 "a".mkv']);
    assert.match(await page.evaluate(() => window.__confirms.at(-1)), /全部 3 个.*不会删除源文件/s);
});

test('seasons open in place under the poster row and give focus back when closed', async t => {
    const {page} = await setup(t, {overrides: withLibrary(bigLibrary())});
    await openView(page, 'library');
    const card = page.locator('.tv-card').first();
    await card.locator('.season-toggle-btn').focus();
    await page.keyboard.press('Enter');
    const panel = page.locator('.show-seasons-panel');
    await panel.waitFor();
    assert.equal(await card.evaluate(node => node.nextElementSibling.classList.contains('show-seasons-panel')), true, 'panel follows its card in the DOM');
    assert.equal(await card.locator('.season-toggle-btn').getAttribute('aria-expanded'), 'true');
    const [cardBox, panelBox, gridBox] = await Promise.all([card.boundingBox(), panel.boundingBox(), page.locator('#showGrid').boundingBox()]);
    assert.ok(panelBox.y >= cardBox.y + cardBox.height - 1, 'panel sits below the row');
    assert.ok(Math.abs(panelBox.width - gridBox.width) < 2, 'panel spans the whole row');
    // Later cards back-fill the row instead of leaving a hole next to the open card.
    const second = await page.locator('.tv-card').nth(1).boundingBox();
    assert.ok(Math.abs(second.y - cardBox.y) < 2);
    // Clicking the artwork toggles too; the button keeps the accessible state.
    await page.locator('.tv-card').nth(1).locator('.media-card-poster').click({position: {x: 40, y: 60}});
    assert.equal(await page.locator('.show-seasons-panel').count(), 2);
    await panel.first().getByRole('button', {name: '收起'}).focus();
    await page.keyboard.press('Enter');
    assert.equal(await page.locator('.show-seasons-panel').count(), 1);
    assert.equal(await card.locator('.season-toggle-btn').getAttribute('aria-expanded'), 'false');
    assert.equal(await page.evaluate(() => document.activeElement.classList.contains('season-toggle-btn')), true);
});

test('infinite scroll adds each card once and the spotlight can reveal a show beyond the first page', async t => {
    const library = bigLibrary();
    library.tv_shows[0].seasons[1].episodes.forEach(episode => { episode.processed_time = 1; });   // sorts to the very end
    library.tv_shows[0].seasons[0].episodes[0].processed_time = 1;
    const {page} = await setup(t, {overrides: withLibrary(library)});
    await openView(page, 'library');
    await page.locator('.tv-card').first().waitFor();
    assert.equal(await page.locator('.tv-card').count(), 30);
    for (let i = 0; i < 12 && await page.locator('.tv-card').count() < 71; i++) {
        await page.evaluate(() => window.scrollTo(0, document.documentElement.scrollHeight));
        await page.waitForTimeout(150);
    }
    const ids = await page.locator('.tv-card').evaluateAll(cards => cards.map(card => card.dataset.showId));
    assert.equal(ids.length, 71);
    assert.equal(new Set(ids).size, 71, 'no duplicated cards');

    // Fresh page starts at the top; browser scroll restoration would load another page.
    await page.evaluate(() => { history.scrollRestoration = 'manual'; window.scrollTo(0, 0); });
    await page.reload();
    await page.waitForFunction(() => window.App && App.Shell);
    await page.locator('[data-view-target="library"]').click();
    await page.locator('.tv-card').first().waitFor();
    assert.equal(await page.locator('.tv-card').count(), 30);
    await page.evaluate(() => App.MediaManager.revealShow(6));
    await page.locator('.show-seasons-panel').waitFor();
    assert.equal(await page.locator('.show-seasons-panel').evaluate(node => node.previousElementSibling.dataset.showId), '6');
    assert.equal(new Set(await page.locator('.tv-card').evaluateAll(cards => cards.map(card => card.dataset.showId))).size, await page.locator('.tv-card').count());
});

test('selection bar appears with a selection, clears it, and keeps raw keys for batch delete', async t => {
    const {page, requests} = await setup(t, {overrides: withLibrary(bigLibrary())});
    await openView(page, 'library');
    const bar = page.locator('#mediaSelectionBar');
    assert.equal(await bar.isVisible(), false);
    assert.equal(await page.locator('#mediaBatchDeleteBtn').isDisabled(), true);
    await page.locator('.movie-card input').first().check();
    await page.locator('.movie-card input').nth(1).check();
    assert.equal(await bar.isVisible(), true);
    assert.equal(await page.locator('#mediaSelectedCount').textContent(), '2');
    await bar.getByRole('button', {name: '取消选择'}).click();
    assert.equal(await bar.isVisible(), false);
    assert.equal(await page.locator('.movie-card input:checked').count(), 0);
    assert.equal(await page.locator('#mediaBatchCorrectBtn').isDisabled(), true);
    await page.locator('.movie-card input').first().check();
    const body = await waitForRequest(page, requests, '/api/media/batch_delete', () => bar.getByRole('button', {name: '批量删除'}).click());
    assert.deepEqual(body, {src_paths: ['/src/新电影 & co.mkv'], delete_source: false});
});

test('touch screens reach single-item actions by selecting, with no hover needed', async t => {
    const context = await browser.newContext({viewport: {width: 390, height: 844}, hasTouch: true, isMobile: true});
    t.after(() => context.close());
    const page = await context.newPage();
    page.setDefaultTimeout(5000);
    const requests = [];
    await page.addInitScript(() => { window.confirm = () => true; });
    await page.route('**/*', async route => {
        const req = route.request(), url = new URL(req.url());
        if (url.pathname === '/') return route.fulfill({contentType: 'text/html', body: rendered.stdout});
        if (url.pathname.startsWith('/static/')) return route.fulfill({path: path.join(root, url.pathname)});
        if (url.pathname.startsWith('/media_poster/')) return route.fulfill({status: 404, body: ''});
        if (!url.pathname.startsWith('/api/')) return route.abort();
        requests.push({url: url.pathname + url.search, method: req.method(), body: req.postDataJSON()});
        const data = {'/api/config': {source_folders: ['/src'], tv_target_folder: '/tv', movie_target_folder: '/m', auth: {}, ai_parser: {}, ai_plot_enhance: {}, tmdb_api: {}},
            '/api/status': {running: false, status: 'idle', log: []}, '/api/media/library': bigLibrary(), '/api/special_mappings': {mappings: []}}[url.pathname] || {status: 'success'};
        return route.fulfill({json: data});
    });
    await page.goto('http://animeman.test/');
    await page.waitForFunction(() => window.App && Object.keys(App.configCache || {}).length > 0);
    await page.evaluate(() => clearInterval(App.statusInterval));
    await page.locator('[data-view-target="library"]').tap();
    const card = page.locator('.movie-card').first();
    await card.waitFor();
    assert.equal(await page.evaluate(() => matchMedia('(hover: none)').matches), true);
    // The checkbox is always visible on touch and large enough to hit.
    assert.equal(await card.locator('.media-card-check').evaluate(node => getComputedStyle(node).opacity), '1');
    const target = await card.locator('.media-card-check').boundingBox();
    assert.ok(target.width >= 44 && target.height >= 44, `checkbox target is ${target.width}x${target.height}`);
    assert.equal(await card.locator('.media-card-actions').evaluate(node => getComputedStyle(node).pointerEvents), 'none', 'hidden actions do not swallow taps');
    await card.locator('.media-card-check input').tap();
    assert.equal(await page.locator('#mediaSelectionBar').isVisible(), true);
    await page.waitForFunction(() => getComputedStyle(document.querySelector('.movie-card .media-card-actions')).opacity === '1');
    const before = requests.length;
    await card.locator('.media-card-actions .danger').tap();
    for (let i = 0; i < 50 && !requests.slice(before).some(r => r.url === '/api/media/delete'); i++) await page.waitForTimeout(40);
    assert.deepEqual(requests.slice(before).find(r => r.url === '/api/media/delete').body, {src_path: '/src/新电影 & co.mkv', delete_source: false});
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    assert.ok(overflow <= 1, `library overflows by ${overflow}px on a phone`);
});

test('workbench strip mirrors the newest items, opens them in the library, and hides when empty', async t => {
    const full = await setup(t, {overrides: withLibrary(bigLibrary())});
    const strip = full.page.locator('#homeRecent');
    await strip.locator('.recent-item').first().waitFor();
    assert.equal(await strip.locator('.recent-item').count(), 8);
    assert.equal(await strip.locator('.recent-title').first().textContent(), evil);
    assert.equal(await strip.locator('.recent-title img').count(), 0);
    await strip.locator('.recent-item').nth(1).click();
    await full.page.locator('#view-library').waitFor({state: 'visible'});
    assert.equal(await full.page.locator('#librarySpotlight .spotlight-title').textContent(), '新电影');
    const empty = await setup(t, {overrides: withLibrary({movies: [], tv_shows: []})});
    assert.equal(await empty.page.locator('#homeRecent').isVisible(), false);
    await openView(empty.page, 'library');
    assert.equal(await empty.page.locator('#librarySpotlight').isVisible(), false);
    assert.match(await empty.page.locator('#mediaLibraryManagerContainer').textContent(), /媒体库还是空的/);
    assert.equal(await empty.page.locator('#libraryStats').textContent(), '', 'no invented totals');
});

test('a failed library request says so and can be retried', async t => {
    let fail = true;
    const {page} = await setup(t, {overrides: {'/api/media/library': route => fail
        ? route.fulfill({status: 500, json: {message: '缓存 <b>损坏</b>'}}) : route.fulfill({json: bigLibrary()})}});
    await openView(page, 'library');
    const container = page.locator('#mediaLibraryManagerContainer');
    await page.waitForFunction(() => /媒体库加载失败/.test(document.getElementById('mediaLibraryManagerContainer').textContent));
    assert.match(await container.textContent(), /HTTP 500.*缓存 <b>损坏<\/b>/);
    assert.equal(await container.locator('b').count(), 1, 'only the heading is bold; the message stayed text');
    assert.equal(await page.locator('#librarySpotlight').isVisible(), false);
    fail = false;
    await container.getByRole('button', {name: '重试'}).click();
    await page.locator('.tv-card').first().waitFor();
    assert.equal(await page.locator('#librarySpotlight').isVisible(), true);
});

test('theme preference applies immediately and is the only thing stored', async t => {
    const {page} = await setup(t);
    await openView(page, 'settings');
    await page.locator('[data-theme-choice="dark"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark');
    assert.equal(await page.locator('[data-theme-choice="dark"]').getAttribute('aria-pressed'), 'true');
    await page.reload();
    await page.waitForFunction(() => window.App && App.Shell);
    assert.equal(await page.evaluate(() => document.documentElement.dataset.theme), 'dark');
    await page.locator('[data-view-target="settings"]').click();
    await page.locator('[data-theme-choice="system"]').click();
    assert.deepEqual(await page.evaluate(() => Object.keys(localStorage)), []);
});

for (const [name, viewport] of [['375px phone', {width: 375, height: 700}], ['768px tablet', {width: 768, height: 1024}], ['1280px desktop', {width: 1280, height: 800}]]) {
    test(`${name}: no page-level horizontal overflow, zoom allowed, controls large enough`, async t => {
        const {page} = await setup(t, {viewport});
        assert.doesNotMatch(await page.locator('meta[name="viewport"]').getAttribute('content'), /maximum-scale|user-scalable\s*=\s*no/);
        for (const view of views) {
            await openView(page, view);
            const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
            assert.ok(overflow <= 1, `${view} overflows by ${overflow}px`);
        }
        for (const open of ['App.ProcessedCache.viewProcessedCache()', 'App.Correction.openCorrectionModal("/src/a b.mkv","a b.mkv")',
            'App.BatchCorrection.openModalWithFiles("来源",[{path:"/src/a.mkv",name:"a.mkv"}])', 'App.MediaLibrary.showTargetSelector(()=>{})']) {
            await page.evaluate(code => { (0, eval)(code); }, open);
            await page.waitForFunction(() => App.Shell.openModalCount() === 1);
            const size = await page.evaluate(() => {
                const panel = document.querySelector('.modal[style*="block"] .modal-content').getBoundingClientRect();
                return {left: panel.left, right: panel.right, bottom: panel.bottom, width: innerWidth, height: innerHeight};
            });
            assert.ok(size.left >= 0 && size.right <= size.width + 1 && size.bottom <= size.height + 1, `${open} fits the viewport`);
            await page.keyboard.press('Escape');
            await page.waitForFunction(() => App.Shell.openModalCount() === 0);
        }
        if (viewport.width < 600) {
            await openView(page, 'home');
            for (const selector of ['#runBtn', '#stopBtn', '[data-view-target="library"]']) {
                const box = await page.locator(selector).boundingBox();
                assert.ok(box.height >= 36 && box.width >= 44, `${selector} is ${box.width}x${box.height}`);
            }
        }
    });
}

test('manual rule scope is explicit, previews impact and preserves special season zero', async t => {
    const {page, requests} = await setup(t, {overrides:{
        '/api/failed_cache/correct': route => route.fulfill({json:{status:'success'}})
    }});
    await openView(page, 'settings');
    assert.equal(await page.locator('#userRulesEnabledCheck').isChecked(), false);
    await page.evaluate(() => App.Correction.openCorrectionModal('/src/Show/Show OVA.mkv','Show OVA.mkv'));
    assert.equal(await page.locator('#correctionRuleScope').inputValue(), 'none');
    await page.evaluate(() => App.Correction.selectTmdbForCorrection(42,'Show','tv'));
    await page.locator('#correctionRuleScope').selectOption('series');
    assert.match(await page.locator('#correctionRulePreview').textContent(), /系列目录.*\/src\/Show.*42/);
    await page.locator('#correctionSeason').fill('0');
    await page.locator('#correctionEpisode').fill('2');
    await page.evaluate(() => App.Correction.executeCorrection());
    await page.waitForFunction(() => document.querySelector('#correctionModal').style.display === 'none');
    const req=requests.find(r=>r.url==='/api/failed_cache/correct');
    assert.equal(req.body.season,0);
    assert.equal(req.body.episode,2);
    assert.equal(req.body.save_rule_scope,'series');
});

test('manual correction reports rule save failure without repeating media operation', async t => {
    const {page, requests} = await setup(t, {overrides:{
        '/api/failed_cache/correct': route => route.fulfill({json:{status:'success', rule_status:'failed', rule_message:'synthetic failure'}})
    }});
    await page.evaluate(() => {
        window.capturedRuleToast = '';
        App.showToast = message => { window.capturedRuleToast = message; };
        App.Correction.openCorrectionModal('/src/Show/Show S01E01.mkv','Show S01E01.mkv');
        App.Correction.selectTmdbForCorrection(42,'Show','tv');
    });
    await page.locator('#correctionRuleScope').selectOption('file');
    await page.locator('#correctionSeason').fill('1');
    await page.locator('#correctionEpisode').fill('1');
    await page.evaluate(() => App.Correction.executeCorrection());
    await page.waitForFunction(() => window.capturedRuleToast.includes('规则未保存'));
    assert.match(await page.evaluate(() => window.capturedRuleToast), /修正成功.*synthetic failure/);
    assert.equal(requests.filter(r => r.url === '/api/failed_cache/correct').length, 1);
});

test('confirmed identity with unknown numbering requires explicit season and episode', async t => {
    const {page, requests} = await setup(t, {overrides:{
        '/api/failed_cache/correct': route => route.fulfill({json:{status:'success'}})
    }});
    await page.evaluate(() => App.Correction.openCorrectionModal('/src/Show/Show OVA.mkv', 'Show OVA.mkv',
        {identity_status:'confirmed', numbering_status:'unknown', tmdb_id:42, media_type:'tv'}));
    assert.equal(await page.locator('#correctionSeason').inputValue(), '');
    assert.equal(await page.locator('#correctionEpisode').inputValue(), '');
    await page.evaluate(() => App.Correction.executeCorrection());
    assert.equal(requests.filter(r => r.url === '/api/failed_cache/correct').length, 0);
    await page.locator('#correctionSeason').fill('0');
    await page.locator('#correctionEpisode').fill('3');
    await page.evaluate(() => App.Correction.executeCorrection());
    const req=requests.find(r=>r.url==='/api/failed_cache/correct');
    assert.equal(req.body.tmdb_id,42);
    assert.equal(req.body.use_pending_identity,true);
    assert.equal(req.body.season,0);
    assert.equal(req.body.episode,3);
});

test('numbering maps require a reviewed preview and preserve decimal label', async t => {
    const {page, requests} = await setup(t, {overrides:{
        '/api/numbering_maps/preview': route => route.fulfill({json:{status:'success',preview:{source_label:'12.5',season:0,episode:3}}}),
        '/api/numbering_maps': route => route.fulfill({json:{status:'success',rules:[]}})
    }});
    await openView(page,'settings');
    assert.equal(await page.locator('#numberingMapsEnabledCheck').isChecked(),false);
    await openRuleTab(page,'numberingMapsDetails');
    await page.locator('#numberingScope').fill('/src/Show');
    await page.locator('#numberingSrcPath').fill('/src/Show/Show - 12.5.mkv');
    await page.locator('#numberingTmdbId').fill('42');
    await page.locator('#numberingSourceLabel').fill('12.5');
    await page.locator('#numberingTargetSeason').fill('0');
    await page.locator('#numberingTargetEpisode').fill('3');
    assert.equal(await page.locator('#numberingSave').isDisabled(),true);
    await page.locator('#numberingPreview').click();
    await page.waitForFunction(() => document.querySelector('#numberingPreviewResult').textContent.includes('12.5'));
    assert.match(await page.locator('#numberingPreviewResult').textContent(),/S00E03/);
    assert.equal(await page.locator('#numberingSave').isDisabled(),false);
    await page.locator('#numberingTargetEpisode').fill('4');
    assert.equal(await page.locator('#numberingSave').isDisabled(),true);
    await page.locator('#numberingTargetEpisode').fill('3');
    await page.locator('#numberingPreview').click();
    await page.locator('#numberingSave').click();
    const req=requests.find(r=>r.url==='/api/numbering_maps' && r.method==='POST');
    assert.equal(req.body.source_label,'12.5');
    assert.equal(req.body.season,0);
    assert.equal(req.body.episode,3);
});

test('scoped alias requires reviewed preview and keeps identifiers as text', async t => {
    const {page,requests}=await setup(t,{overrides:{
        '/api/recognition_aliases/preview': route => route.fulfill({json:{status:'success',preview:{scope:'/src/Show',name:'Sora no Tabi',media_type:'tv',tmdb_id:42,title:'空の旅',year:'2020',additional_names:['空の旅'],conflicting_ids:[]},preview_token:'a'.repeat(64)}}),
        '/api/recognition_aliases': route => route.fulfill({json:{status:'success',active:false,aliases:[]}})
    }});
    await openView(page,'settings');
    assert.equal(await page.locator('#recognitionAliasesEnabledCheck').isChecked(),false);
    await openRuleTab(page,'recognitionAliasesDetails');
    await page.locator('#recognitionAliasScope').fill('/src/Show');
    await page.locator('#recognitionAliasName').fill('Sora no Tabi');
    await page.locator('#recognitionAliasId').fill('42');
    assert.equal(await page.locator('#recognitionAliasSave').isDisabled(),true);
    await page.locator('#recognitionAliasPreview').click();
    await page.waitForFunction(() => document.querySelector('#recognitionAliasPreviewResult').textContent.includes('空の旅'));
    assert.match(await page.locator('#recognitionAliasPreviewResult').textContent(),/Sora no Tabi.*42/);
    await page.locator('#recognitionAliasName').fill('Changed');
    assert.equal(await page.locator('#recognitionAliasSave').isDisabled(),true);
    await page.locator('#recognitionAliasName').fill('Sora no Tabi');
    await page.locator('#recognitionAliasPreview').click();
    await page.locator('#recognitionAliasSave').click();
    const req=requests.find(r=>r.url==='/api/recognition_aliases' && r.method==='POST');
    assert.equal(req.body.name,'Sora no Tabi');
    assert.equal(req.body.scope,'/src/Show');
    assert.equal(req.body.tmdb_id,42);
    assert.equal(req.body.preview_token,'a'.repeat(64));
});

test('alias preview renders titles and conflicting identifiers as plain text', async t => {
    const {page}=await setup(t,{overrides:{
        '/api/recognition_aliases/preview': route => route.fulfill({json:{status:'success',preview:{scope:'/src/Show',name:'<img src=x onerror=alert(1)>',media_type:'tv',tmdb_id:42,title:'<b>not markup</b>',year:null,additional_names:[],conflicting_ids:[43]},preview_token:'b'.repeat(64)}})
    }});
    await openRuleTab(page,'recognitionAliasesDetails');
    await page.locator('#recognitionAliasScope').fill('/src/Show');
    await page.locator('#recognitionAliasName').fill('<img src=x onerror=alert(1)>');
    await page.locator('#recognitionAliasId').fill('42');
    await page.locator('#recognitionAliasPreview').click();
    await page.waitForFunction(() => document.querySelector('#recognitionAliasPreviewResult').textContent.includes('not markup'));
    assert.equal(await page.locator('#recognitionAliasPreviewResult img').count(),0);
    assert.equal(await page.locator('#recognitionAliasPreviewResult b').count(),0);
    assert.match(await page.locator('#recognitionAliasPreviewResult').textContent(),/43.*人工确认/);
});

// ---------- round three: correction cards, failed folders, subtitles, logs, settings, favicon ----------
const tmdbResults = [
    {id: 11, title: '<b>粗体</b>标题', year: '2021', media_type: 'tv', poster_url: '/media_poster/tv/11',
        seasons_detail: [{season_number: 0, episode_count: 3, name: 'SP'}, {season_number: 1, episode_count: 12, name: 'S1'}, {season_number: 2, episode_count: 13, name: 'S2'}]},
    {id: 12, title: '没有海报', year: '', media_type: 'tv', poster_url: null, seasons_detail: []},
];

test('TMDB results are poster cards: one choice at a time, facts only from the response', async t => {
    const {page, requests} = await setup(t, {overrides: {'/api/tmdb/search_proxy': route => route.fulfill({json: {results: tmdbResults}})}});
    await page.evaluate(() => App.Correction.openCorrectionModal('/src/a b "c".mkv', 'a b "c".mkv'));
    assert.match(await page.locator('#tmdbResultsBody').textContent(), /输入片名搜索/);
    await page.locator('#tmdbSearchInput').fill('x');
    await page.keyboard.press('Enter');
    const cards = page.locator('#tmdbResultsBody .tmdb-card');
    await cards.first().waitFor();
    assert.equal(await cards.count(), 2);
    assert.equal(await cards.first().locator('.tmdb-title').textContent(), '<b>粗体</b>标题');
    assert.equal(await page.locator('#tmdbResultsBody b').count(), 0);
    assert.equal(await cards.first().locator('.tmdb-meta').textContent(), '2021 · 剧集 · 2 季 25 集 · 含特别篇');
    assert.equal(await cards.nth(1).locator('.tmdb-meta').textContent(), '剧集', 'no invented seasons or year');
    assert.equal(await cards.nth(1).locator('img').evaluate(img => img.getAttribute('src')), null, 'no poster URL is made up');
    assert.equal(await cards.nth(1).locator('.poster-fallback').textContent(), '没');
    await cards.nth(1).click();
    await cards.first().click();
    assert.deepEqual(await cards.evaluateAll(nodes => nodes.map(n => n.getAttribute('aria-pressed'))), ['true', 'false']);
    assert.equal(await page.locator('#selectedTmdbId').textContent(), '11');
    await page.locator('#correctionSeason').fill('1');
    await page.locator('#correctionEpisode').fill('1');
    const before = requests.length;
    await page.locator('#correctionModal button.success.primary').click();
    for (let i = 0; i < 50 && !requests.slice(before).some(r => r.url === '/api/failed_cache/correct'); i++) await page.waitForTimeout(40);
    const body = requests.slice(before).find(r => r.url === '/api/failed_cache/correct').body;
    assert.equal(body.src_path, '/src/a b "c".mkv');
    assert.equal(body.tmdb_id, 11);
});

test('a new search clears the previous choice, and search errors show as text', async t => {
    let fail = false;
    const {page} = await setup(t, {overrides: {'/api/tmdb/search_proxy': route => fail
        ? route.fulfill({status: 500, json: {message: '<i>上游</i>超时'}}) : route.fulfill({json: {results: tmdbResults}})}});
    await page.evaluate(() => App.Correction.openCorrectionModal('/src/a.mkv', 'a.mkv'));
    await page.locator('#tmdbSearchInput').fill('x');
    await page.locator('#correctionSearchBtn').click();
    await page.locator('#tmdbResultsBody .tmdb-card').first().click();
    assert.equal(await page.locator('#selectedTmdbInfo').isVisible(), true);
    fail = true;
    await page.locator('#correctionSearchBtn').click();
    await page.locator('#tmdbResultsBody .result-message.is-error').waitFor();
    assert.equal(await page.locator('#selectedTmdbInfo').isVisible(), false, 'old choice is not silently kept');
    assert.equal(await page.evaluate(() => App.selectedTmdbId), null);
    assert.match(await page.locator('#tmdbResultsBody').textContent(), /搜索失败.*<i>上游<\/i>超时/);
    assert.equal(await page.locator('#tmdbResultsBody i').count(), 0);
});

test('failed folders are cards with a reason summary, and an empty cache says so', async t => {
    const files = [{path: '/src/x/1.mkv', name: '1.mkv', reason: '原因 A'}, {path: '/src/x/2.mkv', name: '2.mkv', reason: '原因 A'},
        {path: '/src/x/3.mkv', name: '3.mkv', reason: '<b>原因 B</b>'}, {path: '/src/x/4.mkv', name: '4.mkv'}];
    let clusters = [{folder: '/src/番剧/[组] 文件夹 "x"', count: 4, files}];
    const {page} = await setup(t, {overrides: {'/api/failed_cache/clusters': route => route.fulfill({json: {clusters}})}});
    await page.evaluate(() => App.FailedCache.viewFailedCache());
    const card = page.locator('.failed-folder');
    await card.waitFor();
    assert.equal(await card.locator('h4').textContent(), '[组] 文件夹 "x"');
    assert.equal(await card.locator('.mono').textContent(), '/src/番剧/[组] 文件夹 "x"');
    assert.equal(await card.locator('.badge').textContent(), '4 个文件');
    assert.deepEqual(await card.locator('.reason-list li').allTextContents(), ['原因 A× 2', '<b>原因 B</b>× 1', '未记录原因× 1']);
    assert.equal(await card.locator('.reason-list b').count(), 0);
    assert.equal(await card.locator('button.success').count(), 1);
    await card.getByRole('button', {name: '查看失败文件'}).click();
    assert.deepEqual(await page.locator('.failed-files .failed-file-name').allTextContents(), ['1.mkv', '2.mkv', '3.mkv', '4.mkv']);
    assert.equal(await page.locator('.failed-files button.warning').count(), 4);
    clusters = [];
    await page.getByRole('button', {name: '返回文件夹视图'}).click();
    await page.locator('#failedCacheList .empty-state').waitFor();
    assert.match(await page.locator('#failedCacheList').textContent(), /没有失败记录/);
});

test('subtitle steps, summary and attention sort follow the real results and keep selections', async t => {
    const {page} = await setup(t);
    await openView(page, 'subtitles');
    assert.equal(await page.locator('#subStepScan').getAttribute('data-state'), 'current');
    assert.equal(await page.locator('#subtitleSummary').textContent(), '');
    const sub = name => ({path: '/subs/' + name, name});
    const media = (title, episode) => ({media_type: 'tv', title, season: 1, episode, target_path: '/lib/x.mkv', target_dir: '/lib'});
    await page.evaluate(results => { App.scannedSubtitles = results.map(r => r.subtitle); App.matchResults = results; App.SubtitleCenter.renderMatchTable(); }, [
        {subtitle: sub('a.ass'), best_match: {score: 96, media: media('甲', 1)}},
        {subtitle: sub('b.ass'), best_match: {score: 60, media: media('乙', 2)}},
        {subtitle: {...sub('c.ass'), processed_info: {title: '丙', media_type: 'tv', season: 1, episode: 3, target_exists: true}}, best_match: null},
        {subtitle: sub('d.ass'), best_match: null},
    ]);
    assert.deepEqual(await page.locator('#subtitleSummary .chip').allTextContents(), ['共 4', '已匹配 2', '需要确认 1', '已入库 1', '无匹配 1']);
    assert.equal(await page.locator('#subStepScan').getAttribute('data-state'), 'done');
    assert.equal(await page.locator('#subStepMatch').getAttribute('data-state'), 'done');
    assert.match(await page.locator('#subStepScanText').textContent(), /找到 4 个字幕/);
    // Meters only where there is a score; the low one is flagged.
    assert.equal(await page.locator('#subtitleMatchBody .meter').count(), 2);
    assert.equal(await page.locator('#subtitleMatchBody .meter.is-low .meter-value').textContent(), '60%');
    assert.equal(await page.locator('#subtitleMatchBody .meter-fill').first().evaluate(n => n.style.width), '96%');
    assert.doesNotMatch(await page.locator('#subtitleMatchBody').textContent(), /\b0%/);
    // Tick b.ass, then re-sort: the tick follows the subtitle, not the row position.
    await page.locator('#subtitleMatchBody tr').nth(1).locator('input').check();
    await page.locator('#subtitleSortSelect').selectOption('attention');
    const names = await page.locator('#subtitleMatchBody .sub-name').allTextContents();
    assert.deepEqual(names, ['d.ass', 'b.ass', 'a.ass', 'c.ass']);
    assert.deepEqual(await page.locator('#subtitleMatchBody input:checked').evaluateAll(nodes =>
        nodes.map(n => n.closest('tr').querySelector('.sub-name').textContent)), ['b.ass']);
    assert.match(await page.locator('#subStepExecText').textContent(), /已勾选 1 个/);
    // Raising the threshold re-flags results without touching the data.
    await page.locator('#matchThresholdInput').fill('99');
    await page.locator('#matchThresholdInput').dispatchEvent('change');
    assert.equal(await page.locator('#subtitleMatchBody .meter.is-low').count(), 2);
});

test('log filter shows one level at a time with counts and an empty notice', async t => {
    const log = [{level: 'info', msg: 'i', time: 1}, {level: 'error', msg: 'e1', time: 2}, {level: 'error', msg: 'e2', time: 3},
        {level: 'success', msg: 's', time: 4}];
    const {page} = await setup(t, {status: {running: false, status: 'completed', progress: 1, total: 1, log, result: {success: 1, failed: 2}}});
    await page.evaluate(() => App.Task.updateStatus());
    assert.equal(await page.locator('[data-log-count="error"]').textContent(), '2');
    assert.equal(await page.locator('[data-log-count="success"]').textContent(), '1');
    assert.equal(await page.locator('[data-log-count="warning"]').textContent(), '');
    await page.locator('[data-log-filter="error"]').click();
    assert.deepEqual(await page.locator('#logBox .log-line:visible .log-msg').allTextContents(), ['e1', 'e2']);
    assert.equal(await page.locator('[data-log-filter="error"]').getAttribute('aria-pressed'), 'true');
    await page.locator('[data-log-filter="warning"]').click();
    assert.equal(await page.locator('#logBox .log-line:visible').count(), 0);
    assert.equal(await page.locator('#logBox').evaluate(n => n.classList.contains('is-filter-empty')), true);
    await page.locator('[data-log-filter="all"]').click();
    assert.equal(await page.locator('#logBox .log-line:visible').count(), 4);
});

test('settings sections are reachable from the nav and unsaved edits are flagged until a save succeeds', async t => {
    let saveOk = false;
    const {page} = await setup(t, {overrides: {'/api/config': (route, req) => req.method() === 'POST'
        ? route.fulfill(saveOk ? {json: {status: 'success'}} : {status: 500, json: {message: '写入失败'}})
        : route.fulfill({json: {source_folders: ['/src'], tv_target_folder: '/tv', movie_target_folder: '/m', auth: {}, ai_parser: {}, ai_plot_enhance: {}, tmdb_api: {}}})}});
    await openView(page, 'settings');
    assert.equal(await page.locator('#configSavebar').evaluate(n => n.classList.contains('is-dirty')), false);
    await page.locator('[data-scroll-to="cfgAuthTitle"]').click();
    assert.equal(await page.evaluate(() => document.activeElement.id), 'authEnabledCheck');
    assert.equal(await page.locator('[data-scroll-to="cfgAuthTitle"]').getAttribute('aria-current'), 'true');
    assert.ok(await page.locator('#cfgAuthTitle').evaluate(n => n.getBoundingClientRect().top < innerHeight));
    assert.equal(new URL(page.url()).hash, '#settings', 'section jumps do not change the view');
    // Theme buttons are a preference, not a config edit.
    await page.locator('[data-theme-choice="dark"]').click();
    assert.equal(await page.locator('#configSavebar').evaluate(n => n.classList.contains('is-dirty')), false);
    await page.locator('#aiModelInput').fill('edited');
    assert.equal(await page.locator('#configSavebar').evaluate(n => n.classList.contains('is-dirty')), true);
    assert.match(await page.locator('#configSaveState').textContent(), /未保存/);
    await page.locator('#configSavebar button').click();
    await page.locator('.app-toast-error').waitFor();
    assert.equal(await page.locator('#configSavebar').evaluate(n => n.classList.contains('is-dirty')), true, 'failed save stays dirty');
    saveOk = true;
    await page.locator('#configSavebar button').click();
    await page.waitForFunction(() => !document.getElementById('configSavebar').classList.contains('is-dirty'));
});

test('favicon carries the task state', async t => {
    const {page, state} = await setup(t);
    const icon = () => page.locator('#appFavicon').getAttribute('href');
    const idle = await icon();
    state.status = {running: true, status: 'running', task_id: 'x', progress: 1, total: 3, log: []};
    await page.evaluate(() => App.Task.updateStatus());
    const running = decodeURIComponent(await icon());
    assert.notEqual(running, decodeURIComponent(idle));
    assert.match(running, /#38B6FF/);
    state.status = {running: false, status: 'failed', progress: 1, total: 3, log: []};
    await page.evaluate(() => App.Task.updateStatus());
    assert.match(decodeURIComponent(await icon()), /#D9483B/);
    state.status = {running: false, status: 'completed', progress: 3, total: 3, log: []};
    await page.evaluate(() => App.Task.updateStatus());
    assert.doesNotMatch(decodeURIComponent(await icon()), /<circle cx='27'/);
});

test('processed cache rows show typed posters and honest confidence', async t => {
    const row = (extra) => ({src: '/src/' + extra.src_name, parent_dir: 'p', target: '/lib/x.mkv', target_exists: true, processed_time: 1, ...extra});
    const items = [
        row({src_name: 'm.mkv', title: '电影', media_type: 'movie', tmdb_id: 7, year: '2020', confidence: 88}),
        row({src_name: 't.mkv', title: '剧', media_type: 'tv', tmdb_id: 7, season: 1, episode: 2, confidence: null, confirmed_by_user: true}),
        row({src_name: 'u.mkv', title: '未知', media_type: 'tv', tmdb_id: null, season: 1, episode: 3, confidence: null}),
        row({src_name: 'z.mkv', title: '零分', media_type: 'tv', tmdb_id: 8, season: 1, episode: 4, confidence: 0}),
        row({src_name: 'a.mkv', title: '评分', media_type: 'tv', tmdb_id: 9, confidence: 83, score_origin: 'automatic', score_evidence: ['已核验详情'], score_conflicts: ['候选存在歧义']}),
        row({src_name: 'c.mkv', title: '人工规则', media_type: 'tv', tmdb_id: 10, confidence: 100, score_origin: 'manual_mapping'}),
    ];
    const {page} = await setup(t, {overrides: {'/api/processed_cache': route => route.fulfill({json: {items, total_pages: 1}})}});
    await page.evaluate(() => App.ProcessedCache.viewProcessedCache());
    await page.locator('#processedCacheBody .media-cell').first().waitFor();
    assert.deepEqual(await page.locator('#processedCacheBody .row-poster img').evaluateAll(n => n.map(i => i.getAttribute('src'))),
        ['/media_poster/movie/7', '/media_poster/tv/7', null, '/media_poster/tv/8', '/media_poster/tv/9', '/media_poster/tv/10']);
    const cells = await page.locator('#processedCacheBody tr td:nth-child(6)').allTextContents();
    assert.deepEqual(cells, ['旧评分：88', '人工指定', '未评分', '旧评分：0', '匹配评分：83 证据：已核验详情；提示：候选存在歧义', '人工指定']);
    assert.equal(await page.locator('#processedCacheBody tr').nth(1).locator('.meter').count(), 0);
});

test('alias and numbering drafts do not mark the configuration as unsaved', async t => {
    const {page}=await setup(t);
    for (const [details,input] of [['recognitionAliasesDetails','recognitionAliasName'],['numberingMapsDetails','numberingSourceLabel']]) {
        await openRuleTab(page,details);
        await page.locator(`#${input}`).fill('draft');
        assert.equal(await page.locator('#configSavebar').evaluate(node=>node.classList.contains('is-dirty')),false);
    }
    await openView(page,'settings');
    await page.locator('#recognitionAliasesEnabledCheck').check();
    assert.equal(await page.locator('#configSavebar').evaluate(node=>node.classList.contains('is-dirty')),true);
});

// ---------- Tools → 识别规则 hub ----------
const hubLists = {
    '/api/recognition_rules': {rules: [
        {id: 'r1', enabled: true, scope: 'series', path: '/src/<b>番</b>', media_type: 'tv', tmdb_id: 5},
        {id: 'r2', enabled: false, scope: 'file', path: '/src/m "x".mkv', media_type: 'movie', tmdb_id: 6}]},
    '/api/recognition_aliases': {aliases: [
        {name: '<img src=x onerror=window.__xss=1>', media_type: 'movie', tmdb_id: 7, scope: '/src'},
        {name: 'Legacy', media_type: 'tv', tmdb_id: 8, scope: ''}]},
    '/api/numbering_maps': {rules: [
        {id: 'n1', enabled: true, kind: 'range', start: 13, end: 24, scope: '/src/S', tmdb_id: 9, season: 2, episode: 1},
        {id: 'n2', enabled: false, kind: 'exact', source_label: '12.5', scope: '/src/S', tmdb_id: 9, season: 0, episode: 3}]},
};
function hubOverrides(extra = {}) {
    const o = {};
    for (const [url, json] of Object.entries(hubLists)) o[url] = (route, req) => req.method() === 'GET' ? route.fulfill({json}) : route.fulfill({json: {status: 'success'}});
    return {...o, ...extra};
}

test('rules hub: four tabs, one panel at a time, keyboard switching, mappings first', async t => {
    const {page} = await setup(t, {overrides: hubOverrides()});
    await openView(page, 'tools');
    assert.equal(await page.locator('.rule-tabs [role="tab"]').count(), 4);
    assert.equal(await page.locator('[data-rule-tab="mappings"]').getAttribute('aria-selected'), 'true');
    assert.equal(await page.locator('#mappingRulesTable').isVisible(), true);
    assert.equal(await page.locator('.rule-panel:visible').count(), 1);
    await page.locator('[data-rule-tab="mappings"]').focus();
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.evaluate(() => document.activeElement.dataset.ruleTab), 'user');
    assert.equal(await page.locator('#rulePanel-user').isVisible(), true);
    await page.keyboard.press('End');
    assert.equal(await page.locator('#rulePanel-numbering').isVisible(), true);
    await page.keyboard.press('ArrowRight');
    assert.equal(await page.locator('#rulePanel-mappings').isVisible(), true, 'wraps around');
    assert.deepEqual(await page.locator('.rule-tabs [role="tab"]').evaluateAll(n => n.map(b => b.tabIndex)), [0, -1, -1, -1]);
});

test('rules hub loads each list once on entry, shows counts and saved enable state', async t => {
    const {page, requests} = await setup(t, {overrides: hubOverrides(), config: {user_rules: {enabled: true}, recognition_aliases: {enabled: false}}});
    const gets = () => requests.filter(r => r.method === 'GET' && Object.keys(hubLists).includes(r.url)).map(r => r.url).sort();
    assert.deepEqual(gets(), [], 'nothing is fetched before the tools page is opened');
    await openView(page, 'tools');
    await page.waitForFunction(() => document.querySelector('[data-rule-count="numbering"]').textContent === '2');
    assert.deepEqual(gets(), Object.keys(hubLists).sort());
    assert.equal(await page.locator('[data-rule-count="user"]').textContent(), '2');
    assert.equal(await page.locator('[data-rule-count="aliases"]').textContent(), '2');
    assert.equal(await page.locator('[data-rule-state="user"]').textContent(), '已启用');
    assert.equal(await page.locator('[data-rule-state="aliases"]').textContent(), '未启用');
    assert.equal(await page.locator('[data-rule-state="numbering"]').textContent(), '未启用');
    for (const tab of ['user', 'aliases', 'numbering', 'user']) await page.locator(`[data-rule-tab="${tab}"]`).click();
    await openView(page, 'home'); await openView(page, 'tools');
    assert.deepEqual(gets(), Object.keys(hubLists).sort(), 'switching tabs or views does not refetch');
    // Ticking the setting without saving does not claim the rules are active.
    await openView(page, 'settings');
    await page.locator('#recognitionAliasesEnabledCheck').check();
    assert.equal(await page.locator('[data-rule-state="aliases"]').textContent(), '未启用');
});

test('saved rules render as text with readable types, switches and confirmed deletes', async t => {
    const {page, requests} = await setup(t, {overrides: hubOverrides()});
    await openView(page, 'tools');
    await page.locator('[data-rule-tab="user"]').click();
    const rows = page.locator('#recognitionRulesList .rule-row');
    await rows.first().waitFor();
    assert.deepEqual(await rows.locator('.rule-title').allTextContents(), ['剧集 · TMDB 5', '电影 · TMDB 6']);
    assert.equal(await rows.first().locator('.rule-path .mono').textContent(), '/src/<b>番</b>');
    assert.equal(await page.locator('#recognitionRulesList b').count(), 0);
    assert.deepEqual(await rows.locator('[role="switch"]').evaluateAll(n => n.map(s => s.getAttribute('aria-checked'))), ['true', 'false']);
    await rows.nth(1).locator('[role="switch"]').click();
    await page.waitForFunction(() => true);
    for (let i = 0; i < 50 && !requests.some(r => r.url === '/api/recognition_rules/state'); i++) await page.waitForTimeout(40);
    assert.deepEqual(requests.find(r => r.url === '/api/recognition_rules/state').body, {id: 'r2', enabled: true});
    await page.evaluate(() => { window.__asked = []; window.confirm = m => { window.__asked.push(m); return false; }; });
    await rows.first().getByRole('button', {name: '删除规则'}).click();
    assert.equal(requests.filter(r => r.url === '/api/recognition_rules/delete').length, 0, 'cancel sends nothing');
    assert.match(await page.evaluate(() => window.__asked[0]), /<b>番<\/b>/);

    await page.locator('[data-rule-tab="aliases"]').click();
    const aliases = page.locator('#recognitionAliasList .rule-row');
    await aliases.first().waitFor();
    assert.equal(await aliases.first().locator('.rule-title').textContent(), '<img src=x onerror=window.__xss=1>');
    assert.equal(await page.evaluate(() => window.__xss), undefined);
    assert.match(await aliases.first().textContent(), /电影 · TMDB 7/);
    assert.equal(await aliases.nth(1).getByRole('button', {name: '删除人工别名'}).count(), 0, 'unscoped legacy alias cannot be deleted here');
    assert.match(await aliases.nth(1).textContent(), /历史记录：未限定范围/);

    await page.locator('[data-rule-tab="numbering"]').click();
    const maps = page.locator('#numberingList .rule-row');
    await maps.first().waitFor();
    assert.deepEqual(await maps.locator('.rule-title').allTextContents(), ['第 13–24 集 → S02E01 起', '第 12.5 集 → S00E03']);
    await maps.first().locator('[role="switch"]').click();
    for (let i = 0; i < 50 && !requests.some(r => r.url === '/api/numbering_maps/state'); i++) await page.waitForTimeout(40);
    assert.deepEqual(requests.find(r => r.url === '/api/numbering_maps/state').body, {id: 'n1', enabled: false});
    // Deleting a numbering map asks first; cancel sends nothing, confirm sends only the id.
    await page.evaluate(() => { window.__asked = []; window.confirm = m => { window.__asked.push(m); return false; }; });
    await maps.nth(1).getByRole('button', {name: '删除映射'}).click();
    assert.equal(requests.filter(r => r.url === '/api/numbering_maps/delete').length, 0);
    assert.match(await page.evaluate(() => window.__asked.at(-1)), /第 12\.5 集 → S00E03[\s\S]*\/src\/S[\s\S]*不会改动已入库的文件/);
    await page.evaluate(() => { window.confirm = () => true; });
    await maps.nth(1).getByRole('button', {name: '删除映射'}).click();
    for (let i = 0; i < 50 && !requests.some(r => r.url === '/api/numbering_maps/delete'); i++) await page.waitForTimeout(40);
    assert.deepEqual(requests.find(r => r.url === '/api/numbering_maps/delete').body, {id: 'n2'});
});

test('numbering form shows only the fields for the chosen kind and sends only those', async t => {
    const {page, requests} = await setup(t, {overrides: hubOverrides({
        '/api/numbering_maps/preview': route => route.fulfill({json: {status: 'success', preview: {source_label: '13–24', season: 2, episode: 1, tmdb_id: 9, scope: '/src/S'}}})})});
    await openRuleTab(page, 'numberingMapsDetails');
    assert.equal(await page.locator('#numberingSourceLabel').isVisible(), true);
    assert.equal(await page.locator('#numberingStart').isVisible(), false);
    await page.locator('#numberingKind').selectOption('range');
    assert.equal(await page.locator('#numberingSourceLabel').isVisible(), false);
    assert.equal(await page.locator('#numberingStart').isVisible(), true);
    assert.equal(await page.locator('#numberingPreviewResult').getAttribute('data-state'), 'stale');
    for (const [id, value] of [['numberingScope', '/src/S'], ['numberingSrcPath', '/src/S/x 13.mkv'], ['numberingTmdbId', '9'],
        ['numberingStart', '13'], ['numberingEnd', '24'], ['numberingTargetSeason', '2'], ['numberingTargetEpisode', '1']]) await page.locator('#' + id).fill(value);
    await page.locator('#numberingPreview').click();
    await page.waitForFunction(() => document.getElementById('numberingPreviewResult').dataset.state === 'ok');
    await page.locator('#numberingSave').click();
    for (let i = 0; i < 50 && !requests.some(r => r.url === '/api/numbering_maps' && r.method === 'POST'); i++) await page.waitForTimeout(40);
    const body = requests.find(r => r.url === '/api/numbering_maps' && r.method === 'POST').body;
    assert.deepEqual(body, {scope: '/src/S', src_path: '/src/S/x 13.mkv', tmdb_id: 9, kind: 'range', season: 2, episode: 1, start: 13, end: 24});
});

test('choosing a scope with the folder browser fills it and requires a new preview', async t => {
    const {page} = await setup(t, {overrides: hubOverrides({
        '/api/browse': route => route.fulfill({json: {current: '/src/带 空格', parent: '/src', dirs: []}}),
        '/api/recognition_aliases/preview': route => route.fulfill({json: {status: 'success', preview_token: 'c'.repeat(64),
            preview: {scope: '/src', name: 'A', media_type: 'tv', tmdb_id: 1, title: 'A', conflicting_ids: []}}})})});
    await openRuleTab(page, 'recognitionAliasesDetails');
    await page.locator('#recognitionAliasScope').fill('/src');
    await page.locator('#recognitionAliasName').fill('A');
    await page.locator('#recognitionAliasId').fill('1');
    await page.locator('#recognitionAliasPreview').click();
    await page.waitForFunction(() => !document.getElementById('recognitionAliasSave').disabled);
    await page.locator('#rulePanel-aliases .browse').click();
    await page.evaluate(() => App.Browse.browsePath('/src/带 空格'));
    await page.waitForFunction(() => App.currentBrowsePath === '/src/带 空格');
    await page.getByRole('button', {name: '选择此文件夹'}).click();
    assert.equal(await page.locator('#recognitionAliasScope').inputValue(), '/src/带 空格');
    assert.equal(await page.locator('#recognitionAliasSave').isDisabled(), true, 'old preview no longer counts');
    assert.equal(await page.locator('#recognitionAliasPreviewResult').getAttribute('data-state'), 'stale');
    assert.equal(await page.locator('#configSavebar').evaluate(n => n.classList.contains('is-dirty')), false);
});

test('rules are reachable from settings and the correction dialog, and back to the setting', async t => {
    const {page} = await setup(t, {overrides: hubOverrides()});
    await page.evaluate(() => App.Correction.openCorrectionModal('/src/a.mkv', 'a.mkv'));
    await page.locator('#correctionModal [data-open-rules="user"]').click();
    await page.waitForFunction(() => App.Shell.openModalCount() === 0);
    await page.locator('#rulePanel-user').waitFor({state: 'visible'});
    assert.equal(new URL(page.url()).hash, '#tools');
    await page.locator('#recognitionRulesList .rule-row').first().waitFor();
    await page.locator('#rulePanel-user [data-enable-in-settings]').click();
    await page.locator('#view-settings').waitFor({state: 'visible'});
    assert.equal(await page.evaluate(() => document.activeElement.id), 'userRulesEnabledCheck');
    await page.locator('#configForm [data-open-rules]').click();
    await page.locator('#rulePanel-user').waitFor({state: 'visible'});
    // The correction rule preview names the media type in words.
    await page.evaluate(() => { App.Correction.openCorrectionModal('/src/Show/a.mkv', 'a.mkv'); App.Correction.selectTmdbForCorrection(42, 'Show', 'tv'); });
    await page.locator('#correctionRuleScope').selectOption('series');
    assert.match(await page.locator('#correctionRulePreview').textContent(), /剧集 · TMDB 42/);
});

// ---------- Restraint, density and the workbench ----------

test('density switch: compact is a browser preference only, mirrored in library and settings, never dirties the form', async t => {
    const {page} = await setup(t);
    await openView(page, 'library');
    assert.equal(await page.evaluate(() => document.documentElement.dataset.density), undefined);
    const before = await page.locator('.media-card-poster').first().evaluate(n => n.getBoundingClientRect().width);
    await page.locator('.library-bar [data-density-choice="compact"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.density), 'compact');
    const after = await page.locator('.media-card-poster').first().evaluate(n => n.getBoundingClientRect().width);
    assert.ok(after < before, `compact posters are smaller (${after} < ${before})`);
    assert.equal(await page.locator('#librarySpotlight').isVisible(), false, 'compact folds the spotlight away');
    assert.equal(await page.evaluate(() => localStorage.getItem('animeman.density')), 'compact');
    assert.deepEqual(await page.evaluate(() => Object.keys(localStorage).sort()), ['animeman.density'], 'nothing but the preference is stored');
    await openView(page, 'settings');
    assert.equal(await page.locator('#configForm [data-density-choice="compact"]').getAttribute('aria-pressed'), 'true');
    assert.equal(await page.locator('.check:not(.is-danger) small').first().isVisible(), false, 'helper text is hidden');
    assert.equal(await page.locator('#clearAuthPasswordCheck').locator('xpath=..').locator('small').isVisible(), true, 'risk text stays');
    await page.locator('#configForm [data-density-choice="comfortable"]').click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.density), undefined);
    assert.equal(await page.evaluate(() => localStorage.getItem('animeman.density')), null);
    assert.equal(await page.locator('#configSavebar').evaluate(n => n.classList.contains('is-dirty')), false);
    // The preference is applied before the page paints on the next load.
    await page.evaluate(() => localStorage.setItem('animeman.density', 'compact'));
    await page.reload();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.density), 'compact');
});

test('compact keeps touch targets at 44px on coarse pointers', async t => {
    const {page} = await setup(t, {viewport: {width: 390, height: 844}, device: {hasTouch: true, isMobile: true}});
    assert.equal(await page.evaluate(() => matchMedia('(pointer: coarse)').matches), true, 'touch context reports a coarse pointer');
    await page.evaluate(() => App.Shell.setDensity('compact'));
    for (const selector of ['#runBtn', '#stopBtn']) {
        const height = await page.locator(selector).evaluate(n => n.getBoundingClientRect().height);
        assert.ok(height >= 44, `${selector} is ${height}px tall in compact on touch`);
    }
    await openView(page, 'library');
    await page.locator('.media-card-check').first().waitFor();
    const check = await page.locator('.media-card-check').first().evaluate(n => n.getBoundingClientRect().width);
    assert.ok(check >= 44, `selection checkbox hit area ${check}px`);
});

test('section explanations are folded behind a ? button without renaming the section', async t => {
    const {page} = await setup(t);
    await openView(page, 'tools');
    const hint = page.locator('#rulesHubHint');
    const button = page.locator('#rulesHubTitle + .hint-btn');
    assert.equal(await hint.isVisible(), false);
    assert.equal(await button.getAttribute('aria-expanded'), 'false');
    assert.equal(await button.getAttribute('aria-controls'), 'rulesHubHint');
    await button.click();
    assert.equal(await hint.isVisible(), true);
    assert.equal(await button.getAttribute('aria-expanded'), 'true');
    assert.equal(await page.locator('#rulesHubTitle').textContent(), '识别规则', 'heading text unchanged');
    await button.click();
    assert.equal(await hint.isVisible(), false);
    // Subtitle steps are numbered once (the step bar), not again on every sheet.
    assert.equal(await page.locator('#view-subtitles .step-tag').count(), 0);
});

test('library counts appear once: section titles, not the view tabs', async t => {
    const {page} = await setup(t);
    await openView(page, 'library');
    await page.locator('#libraryViewTabs .view-btn').first().waitFor();
    assert.deepEqual(await page.locator('#libraryViewTabs .view-btn').allTextContents(), ['全部', '电影', '剧集']);
    assert.match(await page.locator('.media-section-title').first().textContent(), /\d/);
});

test('rules status bar only appears when a rule type is switched off', async t => {
    const {page} = await setup(t, {config: {user_rules: {enabled: true}}});
    await openView(page, 'tools');
    await page.locator('[data-rule-tab="user"]').click();
    assert.equal(await page.locator('#rulePanel-user [data-rule-switch]').isVisible(), false, 'enabled: the tab already says so');
    await page.locator('[data-rule-tab="aliases"]').click();
    assert.equal(await page.locator('#rulePanel-aliases [data-rule-switch]').isVisible(), true);
});

test('processed cache marks only missing targets', async t => {
    const row = (name, exists) => ({src: '/src/' + name, src_name: name, parent_dir: 'p', target: '/lib/' + name, target_exists: exists,
        processed_time: 1, title: name, media_type: 'movie', tmdb_id: 1, confidence: null});
    const {page} = await setup(t, {overrides: {'/api/processed_cache': route => route.fulfill({json: {items: [row('a.mkv', true), row('b.mkv', false)], total_pages: 1}})}});
    await page.evaluate(() => App.ProcessedCache.viewProcessedCache());
    await page.locator('#processedCacheBody .media-cell').first().waitFor();
    const cells = await page.locator('#processedCacheBody tr td:nth-child(4)').allTextContents();
    assert.deepEqual(cells.map(c => c.trim()), ['a.mkv', '缺失 b.mkv']);
});

test('workbench: idle shows the next step from real counts; running gives the log the room', async t => {
    const clusters = [{folder: '/src/a', count: 2, files: []}, {folder: '/src/b', count: 1, files: []}];
    const {page, state} = await setup(t, {overrides: {'/api/failed_cache/clusters': route => route.fulfill({json: {clusters}})}});
    await page.waitForFunction(() => document.getElementById('homeFailedHint').textContent.includes('3'));
    assert.equal(await page.locator('#homeFailedHint').textContent(), '3 个文件待修正');
    assert.equal(await page.locator('#homeFailedRow').getAttribute('data-attention'), 'true');
    assert.equal(await page.locator('.run-summary').isVisible(), false, 'idle: no row of dashes');
    state.status = {running: true, status: 'running', task_id: 'x', progress: 1, total: 4, log: []};
    await page.evaluate(() => App.Task.updateStatus());
    assert.equal(await page.locator('.run-summary').isVisible(), true);
    assert.equal(await page.locator('#homeRecent').isVisible(), false, 'running: recent strip steps aside');
    clusters.length = 0;
    state.status = {running: false, status: 'completed', task_id: 'x', progress: 4, total: 4, result: {success: 4, failed: 0}, log: []};
    await page.evaluate(() => App.Task.updateStatus());
    await page.waitForFunction(() => document.getElementById('homeFailedHint').textContent === '没有待修正的文件');
    assert.equal(await page.locator('#homeFailedRow').getAttribute('data-attention'), 'false');
    assert.equal(await page.locator('#homeRecent').isVisible(), true);
});

test('workbench keeps the generic text when the failed count cannot be read', async t => {
    const {page} = await setup(t, {overrides: {'/api/failed_cache/clusters': route => route.fulfill({status: 500, json: {error: 'x'}})}});
    await page.locator('.app-toast').waitFor();
    assert.equal(await page.locator('#homeFailedHint').textContent(), '没能自动识别的文件，在这里手动修正');
    assert.equal(await page.locator('#homeFailedRow').getAttribute('data-attention'), null);
});
