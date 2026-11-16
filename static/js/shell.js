/**
 * 界面外壳：页面导航、主题、弹窗的键盘与焦点管理、任务条的展示同步。
 *
 * 这里只做展示层的事情：
 *   - 不发起任何 /api 请求，不改任务、配置或缓存的含义；
 *   - 业务模块仍然自己控制弹窗的 display、按钮的 disabled、进度条的 width；
 *   - localStorage 只保存主题偏好（animeman.theme），不保存配置、路径或密钥。
 *
 * 模块加载时不产生副作用，全部在 App.Shell.init() 里完成；init 可重复调用。
 */
window.App = window.App || {};
App.Shell = (function(app) {
    'use strict';

    const VIEWS = ['home', 'library', 'subtitles', 'tools', 'settings'];
    const THEME_KEY = 'animeman.theme';
    const BASE_TITLE = 'AnimeMan · 番剧智能管家';
    const FOCUSABLE = 'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), ' +
        'select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

    let initialized = false;
    let currentView = 'home';
    const openModals = [];      // 按打开顺序排列，最后一个在最上层

    const byId = id => document.getElementById(id);

    // ---------- 页面导航 ----------
    function show(view, options = {}) {
        if (!VIEWS.includes(view)) view = 'home';
        currentView = view;
        for (const section of document.querySelectorAll('.view[data-view]')) {
            section.hidden = section.dataset.view !== view;
        }
        for (const tab of document.querySelectorAll('[data-view-target]')) {
            if (tab.dataset.viewTarget === view) tab.setAttribute('aria-current', 'page');
            else tab.removeAttribute('aria-current');
        }
        if (options.updateHash !== false) {
            const hash = view === 'home' ? '' : '#' + view;
            if (window.location.hash !== hash) {
                try { history.replaceState(null, '', hash || window.location.pathname + window.location.search); }
                catch (error) { /* file:// 等环境下忽略 */ }
            }
        }
        if (options.scroll !== false) window.scrollTo(0, 0);
        if (options.focus) byId('view-' + view)?.focus({preventScroll: true});
        return view;
    }

    function viewFromHash() {
        const name = window.location.hash.replace(/^#/, '');
        return VIEWS.includes(name) ? name : 'home';
    }

    // ---------- 主题 ----------
    function themeChoice() {
        try { return localStorage.getItem(THEME_KEY) || 'system'; } catch (error) { return 'system'; }
    }

    function applyTheme(choice) {
        const systemDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const dark = choice === 'dark' || (choice !== 'light' && systemDark);
        document.documentElement.dataset.theme = dark ? 'dark' : 'light';
        for (const button of document.querySelectorAll('[data-theme-choice]')) {
            button.setAttribute('aria-pressed', String(button.dataset.themeChoice === choice));
        }
        for (const toggle of document.querySelectorAll('[data-theme-toggle] .icon')) {
            toggle.classList.toggle('i-sun', dark);
            toggle.classList.toggle('i-moon', !dark);
        }
    }

    function setTheme(choice) {
        if (!['system', 'light', 'dark'].includes(choice)) choice = 'system';
        try {
            if (choice === 'system') localStorage.removeItem(THEME_KEY);
            else localStorage.setItem(THEME_KEY, choice);
        } catch (error) { /* 无法保存时本次仍然生效 */ }
        applyTheme(choice);
    }

    // ---------- 弹窗：名称、初始焦点、Tab 循环、Escape、关闭后还原焦点 ----------
    function isOpen(modal) {
        return modal.style.display !== '' && modal.style.display !== 'none';
    }

    function syncModal(modal) {
        const index = openModals.indexOf(modal);
        if (isOpen(modal) && index < 0) {
            modal.__returnFocus = document.activeElement;
            openModals.push(modal);
            document.documentElement.classList.add('modal-open');
            (modal.querySelector('.modal-content') || modal).focus({preventScroll: true});
        } else if (!isOpen(modal) && index >= 0) {
            openModals.splice(index, 1);
            if (!openModals.length) document.documentElement.classList.remove('modal-open');
            const target = modal.__returnFocus;
            modal.__returnFocus = null;
            const lost = !document.activeElement || document.activeElement === document.body || modal.contains(document.activeElement);
            if (lost && target && document.contains(target) && target.getClientRects().length) target.focus({preventScroll: true});
        }
    }

    function closeTopModal() {
        const modal = openModals[openModals.length - 1];
        if (!modal) return false;
        const close = modal.querySelector('.modal-close');
        if (close) close.click();           // 走各模块自己的关闭函数，保持其内部状态一致
        else modal.style.display = 'none';
        return true;
    }

    function trapTab(event) {
        const modal = openModals[openModals.length - 1];
        if (!modal) return;
        const panel = modal.querySelector('.modal-content') || modal;
        const items = Array.from(panel.querySelectorAll(FOCUSABLE)).filter(node => node.getClientRects().length);
        if (!items.length) { event.preventDefault(); panel.focus(); return; }
        const first = items[0], last = items[items.length - 1], active = document.activeElement;
        if (!panel.contains(active) || active === panel) {
            event.preventDefault();
            (event.shiftKey ? last : first).focus();
        } else if (event.shiftKey && active === first) {
            event.preventDefault(); last.focus();
        } else if (!event.shiftKey && active === last) {
            event.preventDefault(); first.focus();
        }
    }

    function onKeydown(event) {
        if (event.key === 'Escape') {
            const popup = byId('episodeDetailPopup');
            if (popup && popup.style.display !== 'none' && popup.style.display !== '') { popup.style.display = 'none'; return; }
            if (closeTopModal()) event.preventDefault();
        } else if (event.key === 'Tab') {
            trapTab(event);
        } else if ((event.key === 'Enter' || event.key === ' ') && event.target.matches?.('[role="button"][tabindex]')) {
            // 由脚本生成的可点击行（目录、剧集、季标题）支持键盘操作
            event.preventDefault();
            event.target.click();
        } else if (event.key === 'Enter' && event.target.id === 'tmdbSearchInput') {
            event.preventDefault(); byId('correctionSearchBtn')?.click();
        } else if (event.key === 'Enter' && event.target.id === 'batchTmdbSearchInput') {
            event.preventDefault(); app.BatchCorrection?.searchTmdb();
        }
    }

    // ---------- 任务条与「本次运行」：只展示 /api/status 和 /api/config 返回的真实数据 ----------
    function onTaskStatus(data) {
        const bar = byId('taskBar');
        if (!bar || !data) return;
        const state = data.status || (data.running ? 'running' : 'idle');
        bar.dataset.state = state;

        const hasTotal = Number(data.total) > 0;
        const percent = hasTotal ? Math.round((Number(data.progress) || 0) / Number(data.total) * 100) : 0;
        const percentText = percent + '%';
        const labelText = hasTotal ? `${data.progress} / ${data.total} · ${percentText}` : '尚未开始';
        const label = byId('taskPercent');
        if (label && label.textContent !== labelText) label.textContent = labelText;
        const progress = byId('taskProgress');
        if (progress) {
            progress.setAttribute('aria-valuenow', String(percent));
            progress.setAttribute('aria-valuetext', hasTotal ? `${data.progress} / ${data.total}` : '尚未开始');
        }

        const result = data.result || {};
        const setText = (id, text) => { const node = byId(id); if (node && node.textContent !== text) node.textContent = text; };
        setText('statProgress', hasTotal ? `${data.progress} / ${data.total}` : '—');
        setText('statSuccess', typeof result.success === 'number' ? String(result.success) : '—');
        setText('statFailed', typeof result.failed === 'number' ? String(result.failed) : '—');

        const busy = state === 'running' || state === 'stopping';
        const title = busy && hasTotal ? `${percentText} · ${BASE_TITLE}` : BASE_TITLE;
        if (document.title !== title) document.title = title;
    }

    function onConfigLoaded(config) {
        const dryRun = !!(config && config.dry_run);
        const badge = byId('dryRunBadge');
        if (badge) badge.hidden = !dryRun;
        const mode = byId('statMode');
        if (mode) mode.textContent = dryRun ? '模拟' : '正式';
    }

    // ---------- 初始化 ----------
    function init() {
        if (initialized) return;
        initialized = true;

        document.addEventListener('click', event => {
            const tab = event.target.closest('[data-view-target]');
            if (tab) { show(tab.dataset.viewTarget, {focus: false}); return; }
            const choice = event.target.closest('[data-theme-choice]');
            if (choice) { setTheme(choice.dataset.themeChoice); return; }
            if (event.target.closest('[data-theme-toggle]')) {
                setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
                return;
            }
            const dismiss = event.target.closest('[data-modal-dismiss]');
            if (dismiss) { const modal = dismiss.closest('.modal'); if (modal) modal.style.display = 'none'; }
        });
        document.addEventListener('keydown', onKeydown);
        window.addEventListener('hashchange', () => show(viewFromHash(), {updateHash: false}));

        if (window.matchMedia) {
            const query = window.matchMedia('(prefers-color-scheme: dark)');
            const onSystemChange = () => { if (themeChoice() === 'system') applyTheme('system'); };
            if (query.addEventListener) query.addEventListener('change', onSystemChange);
        }

        if (typeof MutationObserver !== 'undefined') {
            const observer = new MutationObserver(records => {
                for (const record of records) syncModal(record.target);
            });
            for (const modal of document.querySelectorAll('.modal')) {
                observer.observe(modal, {attributes: true, attributeFilter: ['style']});
            }
        }

        app.onTaskStatus = onTaskStatus;
        app.onConfigLoaded = onConfigLoaded;

        applyTheme(themeChoice());
        show(viewFromHash(), {updateHash: false, scroll: false});
    }

    return {
        init,
        show,
        setTheme,
        currentView: () => currentView,
        openModalCount: () => openModals.length,
    };
})(window.App);
