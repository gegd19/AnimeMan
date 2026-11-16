// No browser or network: execute the real modules with controlled DOM/fetch.
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

function setup(environmentManaged = []) {
    const elements = new Map();
    function element(id) {
        if (!elements.has(id)) {
            let value = '';
            elements.set(id, {
                get value() { return value; }, set value(v) { value = String(v); },
                checked: false, placeholder: '', textContent: '', innerHTML: '',
                addEventListener() {}, removeEventListener() {},
            });
        }
        return elements.get(id);
    }
    const requests = [];
    const cfg = {
        environment_managed: environmentManaged,
        auth: {enabled: true, username: 'admin', password: '', password_configured: true},
        tmdb_api: {api_key: '', api_key_configured: true},
        ai_parser: {enabled: true, api_key: '', api_key_configured: true,
                    provider: 'deepseek', model: 'example', base_url: 'https://example.invalid'},
        ai_plot_enhance: {enabled: true, api_key: '', api_key_configured: true},
    };
    const toasts = [];
    const app = {configCache: {}, showToast: (...args) => toasts.push(args)};
    const context = vm.createContext({
        App: app, window: {App: app},
        document: {getElementById: element, querySelector: () => null},
        localStorage: {getItem: () => 'true'}, alert: () => assert.fail('unexpected alert'),
        TextDecoder, confirm: () => true,
        fetch: async (url, options) => {
            requests.push({url, options});
            return {ok: true, json: async () => options ? {status: 'success', dry_run: url === '/api/processed/retry'} : structuredClone(cfg),
                    body: {getReader: () => ({read: async () => ({done: true})})}};
        },
    });
    for (const file of ['app.js', 'config.js', 'aiStream.js', 'history.js']) {
        vm.runInContext(fs.readFileSync(path.join(__dirname, '../static/js', file), 'utf8'), context);
    }
    app.showToast = (...args) => toasts.push(args);
    return {app, element, requests, toasts};
}

test('redacted form keeps saved-AI availability, submits blank secrets and explicit clear flags', async () => {
    const {app, element, requests} = setup();
    await app.Config.loadConfig();
    assert.equal(element('tmdbKeyInput').value, '');
    assert.equal(element('aiKeyInput').value, '');
    assert.equal(element('authPasswordInput').value, '');
    assert.match(element('aiKeyInput').placeholder, /已配置/);
    assert.equal(app.Config.validateAiKey(), true);
    const toggle = {checked: true};
    app.Config.onAiEnabledChange({target: toggle});
    assert.equal(toggle.checked, true);
    await app.Config.saveConfig();
    const saved = JSON.parse(requests.find(r => r.options?.method === 'POST').options.body);
    assert.equal(saved.ai_parser.enabled, true);
    assert.equal(saved.ai_parser.api_key, '');
    assert.equal(saved.ai_plot_enhance.api_key, '');
    assert.deepEqual(saved.clear_secrets, []);
    requests.length = 0;
    element('clearTmdbKeyCheck').checked = true;
    await app.Config.saveConfig();
    const cleared = JSON.parse(requests.find(r => r.options?.method === 'POST').options.body);
    assert.deepEqual(cleared.clear_secrets, ['tmdb_api.api_key']);
});

test('stream requests a saved server key without putting it into the page', async () => {
    const {app, element, requests} = setup();
    await app.Config.loadConfig();
    element('testTitle').value = 'example';
    element('testPlot').value = 'plot';
    await app.AIStream.startStreamEnhance();
    const payload = JSON.parse(requests.find(r => r.url === '/api/ai/stream_enhance').options.body);
    assert.equal(payload.ai_config_source, 'ai_parser');
    assert.equal(payload.ai_config.api_key, '');
});

test('environment-managed media inputs and browse buttons are read-only', async () => {
    const {app, element} = setup(['source_folders', 'tv_target_folder']);
    await app.Config.loadConfig();
    assert.equal(element('sourceFoldersInput').readOnly, true);
    assert.equal(element('sourceBrowseButton').disabled, true);
    assert.equal(element('tvTargetFolderInput').readOnly, true);
    assert.equal(element('movieTargetFolderInput').readOnly, false);
    assert.match(element('environmentPathNote').textContent, /环境变量/);
});

test('preview retry reports a plan rather than a completed file change', async () => {
    const {app, toasts} = setup();
    app.configCache.dry_run = true;
    app.History.loadProcessedHistory = async () => {};
    await app.History.retryProcessed('/source/temporary.mkv');
    assert.match(toasts.at(-1)[0], /模拟完成/);
    assert.doesNotMatch(toasts.at(-1)[0], /重处理成功/);
});
