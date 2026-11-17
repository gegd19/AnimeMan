/**
 * 「工具 → 识别规则」：四类规则的标签切换、自动加载、条数和启用状态。
 *
 * 只负责展示与导航：
 *   - 列表的读取和修改仍由 MappingRules / Correction / RecognitionAliases / NumberingMaps 完成；
 *   - 启用状态取自已保存的配置（App.configCache），修改开关仍在「设置」里、随配置一起保存。
 * 模块加载时不发请求；第一次进入「工具」页或切换标签时才读取对应列表。
 */
window.App = window.App || {};
App.RecognitionRules = (function(app) {
    'use strict';

    const TABS = ['mappings', 'user', 'aliases', 'numbering'];
    const CONFIG_KEY = {user: 'user_rules', aliases: 'recognition_aliases', numbering: 'numbering_maps'};
    const loaded = new Set();
    let current = 'mappings';
    let initialized = false;

    const byId = id => document.getElementById(id);

    function load(tab, force = false) {
        if (!force && loaded.has(tab)) return;
        loaded.add(tab);
        const fail = error => { loaded.delete(tab); app.showToast(error.message || '读取规则失败', 'error'); };
        if (tab === 'user' && app.Correction) app.Correction.loadRules();
        else if (tab === 'aliases' && app.RecognitionAliases) app.RecognitionAliases.refresh().catch(fail);
        else if (tab === 'numbering' && app.NumberingMaps) app.NumberingMaps.refresh().catch(fail);
        // 特辑映射在页面初始化时已由 MappingRules 读取。
    }

    function select(tab, options = {}) {
        if (!TABS.includes(tab)) tab = 'mappings';
        current = tab;
        for (const name of TABS) {
            const button = byId('ruleTab-' + name), panel = byId('rulePanel-' + name);
            if (!button || !panel) continue;
            const active = name === tab;
            button.setAttribute('aria-selected', String(active));
            button.tabIndex = active ? 0 : -1;
            panel.hidden = !active;
        }
        if (options.focus) byId('ruleTab-' + tab)?.focus();
        load(tab, !!options.reload);
    }

    // 启用状态：来自已保存的配置，而不是设置页里尚未保存的勾选。
    function syncStatus() {
        const config = app.configCache || {};
        for (const [tab, key] of Object.entries(CONFIG_KEY)) {
            const on = !!(config[key] && config[key].enabled === true);
            for (const node of document.querySelectorAll(`[data-rule-state="${tab}"], [data-rule-state-text="${tab}"]`)) {
                node.textContent = on ? '已启用' : '未启用';
                node.classList.toggle('is-on', on);
            }
            const bar = document.querySelector(`[data-rule-switch="${tab}"]`);
            if (bar) bar.dataset.on = String(on);
            const goto = bar && bar.querySelector('[data-enable-in-settings]');
            if (goto) goto.textContent = on ? '在设置中停用' : '去设置启用';
        }
    }

    function countMappings() {
        const body = byId('mappingRulesBody');
        if (!body) return;
        const rows = Array.from(body.querySelectorAll('tr')).filter(row => !row.querySelector('td[colspan]'));
        const loading = body.querySelector('td[colspan]') && /加载/.test(body.textContent);
        if (!loading) app.setRuleCount('mappings', rows.length);
    }

    // 从别处打开某一类规则：关掉弹窗，切到「工具」，选中对应标签。
    function open(tab) {
        for (const modal of document.querySelectorAll('.modal')) {
            if (modal.style.display && modal.style.display !== 'none') modal.querySelector('.modal-close')?.click();
        }
        if (app.Shell) app.Shell.show('tools');
        select(tab, {reload: true});
        const hub = document.querySelector('.rules-hub');
        if (hub && hub.scrollIntoView) hub.scrollIntoView({block: 'start'});
        byId('ruleTab-' + tab)?.focus({preventScroll: true});
    }

    // 「去设置启用」：切到设置，定位并聚焦对应开关。开关仍随「保存配置」生效。
    function gotoSetting(checkboxId) {
        if (app.Shell) app.Shell.show('settings');
        const box = byId(checkboxId);
        if (!box) return;
        box.closest('.check')?.scrollIntoView({block: 'center'});
        box.focus({preventScroll: true});
        const label = box.closest('.check');
        if (label) {
            label.classList.remove('is-flash');
            void label.offsetWidth;
            label.classList.add('is-flash');
        }
    }

    function init() {
        if (initialized) return;
        initialized = true;
        const list = document.querySelector('.rule-tabs');
        if (list) {
            list.addEventListener('click', event => {
                const tab = event.target.closest('[data-rule-tab]');
                if (tab) select(tab.dataset.ruleTab);
            });
            // 标签的键盘操作：左右方向键切换，Home / End 到首尾。
            list.addEventListener('keydown', event => {
                const index = TABS.indexOf(current);
                let next = null;
                if (event.key === 'ArrowRight') next = TABS[(index + 1) % TABS.length];
                else if (event.key === 'ArrowLeft') next = TABS[(index - 1 + TABS.length) % TABS.length];
                else if (event.key === 'Home') next = TABS[0];
                else if (event.key === 'End') next = TABS[TABS.length - 1];
                if (next) { event.preventDefault(); select(next, {focus: true}); }
            });
        }
        document.addEventListener('click', event => {
            const opener = event.target.closest('[data-open-rules]');
            if (opener) { open(opener.dataset.openRules); return; }
            const gotoButton = event.target.closest('[data-enable-in-settings]');
            if (gotoButton) gotoSetting(gotoButton.dataset.enableInSettings);
        });
        // 第一次进入「工具」页时读取各类规则的条数。
        document.addEventListener('animeman:view', event => {
            if (event.detail && event.detail.view === 'tools') {
                for (const tab of ['user', 'aliases', 'numbering']) load(tab);
            }
        });
        const body = byId('mappingRulesBody');
        if (body && typeof MutationObserver !== 'undefined') new MutationObserver(countMappings).observe(body, {childList: true});
        countMappings();
        syncStatus();
        if (app.Shell && app.Shell.currentView && app.Shell.currentView() === 'tools') {
            for (const tab of ['user', 'aliases', 'numbering']) load(tab);
        }
    }

    return {init, select, open, syncStatus, current: () => current};
})(window.App);
