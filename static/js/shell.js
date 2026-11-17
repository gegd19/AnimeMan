/**
 * 界面外壳：页面导航、主题、弹窗的键盘与焦点管理、任务条的展示同步。
 *
 * 这里只做展示层的事情：
 *   - 不发起任何 /api 请求，不改任务、配置或缓存的含义；
 *   - 业务模块仍然自己控制弹窗的 display、按钮的 disabled、进度条的 width；
 *   - localStorage 只保存主题和密度偏好（animeman.theme / animeman.density），不保存配置、路径或密钥。
 *
 * 模块加载时不产生副作用，全部在 App.Shell.init() 里完成；init 可重复调用。
 */
window.App = window.App || {};
App.Shell = (function(app) {
    'use strict';

    const VIEWS = ['home', 'library', 'subtitles', 'tools', 'settings'];
    const THEME_KEY = 'animeman.theme';
    const DENSITY_KEY = 'animeman.density';
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
        // 让按需加载的模块（如识别规则）知道页面切换了。
        document.dispatchEvent(new CustomEvent('animeman:view', {detail: {view}}));
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

    // ---------- 密度：舒适（大海报、显示说明）/ 紧凑（小海报、行距收紧、隐藏辅助说明） ----------
    function densityChoice() {
        try { return localStorage.getItem(DENSITY_KEY) === 'compact' ? 'compact' : 'comfortable'; } catch (error) { return 'comfortable'; }
    }

    function applyDensity(choice) {
        if (choice === 'compact') document.documentElement.dataset.density = 'compact';
        else delete document.documentElement.dataset.density;
        for (const button of document.querySelectorAll('[data-density-choice]')) {
            button.setAttribute('aria-pressed', String(button.dataset.densityChoice === choice));
        }
    }

    function setDensity(choice) {
        if (choice !== 'compact') choice = 'comfortable';
        try {
            if (choice === 'compact') localStorage.setItem(DENSITY_KEY, choice);
            else localStorage.removeItem(DENSITY_KEY);
        } catch (error) { /* 无法保存时本次仍然生效 */ }
        applyDensity(choice);
    }

    // ---------- 说明：分区说明默认收起，标题旁的「?」按钮展开。风险和错误提示不走这里，始终显示。 ----------
    function initHints() {
        for (const hint of document.querySelectorAll('.hint[data-hint-for]')) {
            const heading = byId(hint.dataset.hintFor);
            if (!heading || !hint.id || heading.classList.contains('has-hint')) continue;
            hint.hidden = true;
            const button = app.el('button', {type: 'button', className: 'hint-btn', text: '?',
                attrs: {'aria-expanded': 'false', 'aria-controls': hint.id, 'aria-label': '说明：' + heading.textContent.trim(), title: '显示说明'}});
            button.addEventListener('click', () => {
                const open = hint.hidden;
                hint.hidden = !open;
                button.setAttribute('aria-expanded', String(open));
                button.title = open ? '收起说明' : '显示说明';
            });
            // 按钮放在标题后面而不是里面，标题文字和以它命名的区域名称保持不变。
            heading.classList.add('has-hint');
            heading.after(button);
        }
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

    // ---------- 网站图标：任务进行中 / 结束时右下角加一个状态点 ----------
    const FAVICON_BASE = "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 34 34'><path fill='#3340B0' fill-rule='evenodd' d='M9 2h16a7 7 0 0 1 7 7v16a7 7 0 0 1-7 7H9a7 7 0 0 1-7-7V9a7 7 0 0 1 7-7zM9.2 7.4h2.6a1.7 1.7 0 0 1 0 3.4H9.2a1.7 1.7 0 0 1 0-3.4zM17 7a2.1 2.1 0 1 1 0 4.2A2.1 2.1 0 1 1 17 7zM22.2 7.4h2.6a1.7 1.7 0 0 1 0 3.4h-2.6a1.7 1.7 0 0 1 0-3.4zM13.6 15.4v11.2l9.6-5.6z'/>";
    const FAVICON_DOT = {running: '#38B6FF', stopping: '#E0A030', failed: '#D9483B'};
    let faviconState = 'idle';

    function updateFavicon(state) {
        if (state === faviconState) return;
        faviconState = state;
        const link = byId('appFavicon');
        if (!link) return;
        const dot = FAVICON_DOT[state];
        const svg = FAVICON_BASE + (dot ? `<circle cx='27' cy='27' r='6.5' fill='${dot}' stroke='#fff' stroke-width='2'/>` : '') + '</svg>';
        link.href = 'data:image/svg+xml,' + encodeURIComponent(svg);
    }

    // ---------- 任务日志：按级别筛选，计数来自当前显示的日志行 ----------
    function setLogFilter(level) {
        const box = byId('logBox');
        if (!box) return;
        box.dataset.filter = level;
        for (const button of document.querySelectorAll('[data-log-filter]')) {
            button.setAttribute('aria-pressed', String(button.dataset.logFilter === level));
        }
        updateLogCounts();
    }

    function updateLogCounts() {
        const box = byId('logBox');
        if (!box) return;
        for (const badge of document.querySelectorAll('[data-log-count]')) {
            const count = box.querySelectorAll('.log-line.log-' + badge.dataset.logCount).length;
            const text = count ? String(count) : '';
            if (badge.textContent !== text) badge.textContent = text;
        }
        const filter = box.dataset.filter || 'all';
        const empty = filter !== 'all' && box.querySelector('.log-line') && !box.querySelector('.log-line.log-' + filter);
        box.classList.toggle('is-filter-empty', !!empty);
    }

    // ---------- 设置：分区目录与未保存提示 ----------
    function scrollToSection(id) {
        const heading = byId(id);
        const section = heading && heading.closest('.form-section');
        if (!section) return;
        section.scrollIntoView({block: 'start'});
        const first = section.querySelector('input:not([type="hidden"]):not([readonly]), select, textarea, button');
        if (first) first.focus({preventScroll: true});
        markSection(id);
    }

    function markSection(id) {
        for (const button of document.querySelectorAll('[data-scroll-to]')) {
            if (button.dataset.scrollTo === id) button.setAttribute('aria-current', 'true');
            else button.removeAttribute('aria-current');
        }
    }

    function watchSections() {
        if (typeof IntersectionObserver === 'undefined') return;
        const visible = new Map();
        const observer = new IntersectionObserver(entries => {
            for (const entry of entries) visible.set(entry.target, entry.isIntersecting ? entry.boundingClientRect.top : null);
            // 取视口内最靠上的分区
            let best = null, top = Infinity;
            for (const [section, y] of visible) if (y !== null && y < top) { top = y; best = section; }
            const heading = best && best.getAttribute('aria-labelledby');
            if (heading) markSection(heading);
        }, {rootMargin: '-120px 0px -55% 0px'});
        for (const section of document.querySelectorAll('#configForm .form-section')) observer.observe(section);
    }

    function setDirty(dirty) {
        const bar = byId('configSavebar');
        if (!bar) return;
        bar.classList.toggle('is-dirty', dirty);
        const label = byId('configSaveState');
        const text = dirty ? '有未保存的修改。' : '修改后需要保存才会写入配置文件。';
        if (label && label.textContent !== text) label.textContent = text;
    }

    // ---------- 任务条与「本次运行」：只展示 /api/status 和 /api/config 返回的真实数据 ----------
    function onTaskStatus(data) {
        const bar = byId('taskBar');
        if (!bar || !data) return;
        const state = data.status || (data.running ? 'running' : 'idle');
        const previous = bar.dataset.state;
        bar.dataset.state = state;
        const home = byId('view-home');
        if (home) home.dataset.task = state;
        // 任务从进行中变为结束：通知需要刷新的模块（例如工作台的待修正数量）。外壳本身不发请求。
        if ((previous === 'running' || previous === 'stopping') && !['running', 'stopping'].includes(state)) {
            document.dispatchEvent(new CustomEvent('animeman:task-finished', {detail: {status: state}}));
        }
        updateFavicon(state);

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
        // 配置刚从服务端读取（首次加载或保存成功后），表单与已保存的一致。
        setDirty(false);
        if (app.RecognitionRules) app.RecognitionRules.syncStatus();
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
            const density = event.target.closest('[data-density-choice]');
            if (density) { setDensity(density.dataset.densityChoice); return; }
            if (event.target.closest('[data-theme-toggle]')) {
                setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark');
                return;
            }
            const logFilter = event.target.closest('[data-log-filter]');
            if (logFilter) { setLogFilter(logFilter.dataset.logFilter); return; }
            const jump = event.target.closest('[data-scroll-to]');
            if (jump) { scrollToSection(jump.dataset.scrollTo); return; }
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

        const form = byId('configForm');
        if (form) {
            // 只有用户的输入才算修改；脚本填表不会触发 input / change 事件。
            const onEdit = event => { if (!event.target.closest('[data-theme-choice], [data-density-choice], [data-independent-settings]')) setDirty(true); };
            form.addEventListener('input', onEdit);
            form.addEventListener('change', onEdit);
        }
        const logBox = byId('logBox');
        if (logBox && typeof MutationObserver !== 'undefined') {
            new MutationObserver(updateLogCounts).observe(logBox, {childList: true});
        }
        watchSections();

        app.onTaskStatus = onTaskStatus;
        app.onConfigLoaded = onConfigLoaded;

        applyTheme(themeChoice());
        applyDensity(densityChoice());
        initHints();
        show(viewFromHash(), {updateHash: false, scroll: false});
    }

    return {
        init,
        show,
        setTheme,
        setDensity,
        currentView: () => currentView,
        openModalCount: () => openModals.length,
    };
})(window.App);
