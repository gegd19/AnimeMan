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

async function setup(t, {overrides = {}, viewport = {width: 1280, height: 800}, config = {}, status} = {}) {
    const context = await browser.newContext({viewport});
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
    // Card actions are plain visible buttons, not hover-only controls.
    assert.equal(await page.locator('#movieGrid .media-card-actions button').first().isVisible(), true);
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
