/**
 * 配置管理模块
 * 负责加载、填充表单、保存配置、AI 校验、首次引导教程
 */
window.App = window.App || {};
App.Config = (function(app) {
    'use strict';

    // 记录原始密码，用于判断是否被修改
    let originalPassword = '';

    // ---------- 表单填充 ----------
    function populateForm(cfg) {
        document.getElementById('sourceFoldersInput').value = (cfg.source_folders || []).join(', ');
        document.getElementById('tvTargetFolderInput').value = cfg.tv_target_folder || '';
        document.getElementById('movieTargetFolderInput').value = cfg.movie_target_folder || '';
        document.getElementById('linkTypeSelect').value = cfg.link_type || 'hard';
        document.getElementById('dryRunCheck').checked = !!cfg.dry_run;
        document.getElementById('incrementalCheck').checked = cfg.incremental !== false;
        document.getElementById('downloadImagesCheck').checked = cfg.download_images !== false;
        document.getElementById('addYearCheck').checked = cfg.add_year_to_folder !== false;
        document.getElementById('forceChineseCheck').checked = cfg.force_chinese_name !== false;
        document.getElementById('maxWorkersInput').value = cfg.max_workers || 3;
        document.getElementById('minFileSizeInput').value = cfg.min_file_size_mb || 0;
        document.getElementById('videoExtInput').value = (cfg.video_extensions || ['.mkv','.mp4']).join(', ');
        document.getElementById('ignorePatternsInput').value = (cfg.ignore_patterns || []).join(', ');
        document.getElementById('tmdbKeyInput').value = cfg.tmdb_api?.api_key || '';
        document.getElementById('tmdbLanguageInput').value = cfg.tmdb_api?.language || 'zh-CN';
        // 代理字段填充（注意：显示原始值，不自动添加协议，但用户保存时会自动补全）
        document.getElementById('tmdbProxyInput').value = cfg.tmdb_api?.proxy || '';

        const aiParser = cfg.ai_parser || {};
        const aiEnabledCheck = document.getElementById('aiParserEnabledCheck');
        if (aiEnabledCheck) {
            aiEnabledCheck.checked = !!aiParser.enabled;
            // 绑定 change 事件（避免重复绑定）
            aiEnabledCheck.removeEventListener('change', handleAiEnabledChange);
            aiEnabledCheck.addEventListener('change', handleAiEnabledChange);
        }
        document.getElementById('aiBatchFolderCheck').checked = aiParser.batch_folder_enabled !== false;
        document.getElementById('aiProviderSelect').value = aiParser.provider || 'deepseek';
        document.getElementById('aiModelInput').value = aiParser.model || 'deepseek-chat';
        document.getElementById('aiBaseUrlInput').value = aiParser.base_url || 'https://api.deepseek.com';
        document.getElementById('aiKeyInput').value = aiParser.api_key || '';

        const aiPlot = cfg.ai_plot_enhance || {};
        document.getElementById('aiPlotEnhanceCheck').checked = !!aiPlot.enabled;
        document.getElementById('plotTempInput').value = aiPlot.temperature || 0.7;
        document.getElementById('plotTokensInput').value = aiPlot.max_tokens || 500;

        const sub = cfg.subtitle || {};
        document.getElementById('subtitleEnabledCheck').checked = sub.enabled !== false;
        document.getElementById('subtitleAutoSyncCheck').checked = !!sub.auto_sync;
        document.getElementById('subtitleLinkCheck').checked = sub.link_subtitles !== false;
        document.getElementById('subtitleSyncTimeoutInput').value = sub.sync_timeout || 60;

        const animeParser = cfg.anime_parser || {};
        document.getElementById('animeParserEnabledCheck').checked = animeParser.enabled !== false;
        document.getElementById('animeParserFallbackCheck').checked = animeParser.fallback_to_regex !== false;

        const subCenter = cfg.subtitle_center || {};
        document.getElementById('subSourceFolderInput').value = subCenter.default_source_folder || '';
        document.getElementById('matchThresholdInput').value = subCenter.auto_match_threshold || 75;
        document.getElementById('thresholdValue').innerText = subCenter.auto_match_threshold || 75;
        document.getElementById('subtitleCenterAutoSyncCheck').checked = !!subCenter.auto_sync_enabled;
        document.getElementById('overwriteCheck').checked = !!subCenter.overwrite_existing;

        // 认证配置
        const auth = cfg.auth || {};
        document.getElementById('authEnabledCheck').checked = !!auth.enabled;
        document.getElementById('authUsernameInput').value = auth.username || 'admin';
        const pwdInput = document.getElementById('authPasswordInput');
        if (pwdInput) {
            const pwd = auth.password || '';
            if (pwd === '******') {
                pwdInput.value = '';
                originalPassword = '';
            } else {
                pwdInput.value = pwd;
                originalPassword = pwd;
            }
        }
    }

    // AI 启用复选框变更处理
    function handleAiEnabledChange(e) {
        const checkbox = e.target;
        if (checkbox.checked) {
            const aiKey = document.getElementById('aiKeyInput').value.trim();
            if (!aiKey) {
                const msg = '🤖 AI 解析需调用大模型 API，可能产生少量费用（新用户通常有免费额度）。\n\n请先填写有效的 API Key 再启用。';
                app.showToast(msg, 'info', 6000);
                checkbox.checked = false;
                return;
            }
            app.showToast('✅ AI 解析已启用，请确保账户余额充足', 'success', 3000);
        }
    }

    // ---------- 表单收集 ----------
    function collectConfigFromForm() {
        const cfg = JSON.parse(JSON.stringify(app.configCache));
        cfg.source_folders = document.getElementById('sourceFoldersInput').value.split(',').map(s => s.trim()).filter(s => s);
        cfg.tv_target_folder = document.getElementById('tvTargetFolderInput').value.trim();
        cfg.movie_target_folder = document.getElementById('movieTargetFolderInput').value.trim();
        cfg.link_type = document.getElementById('linkTypeSelect').value;
        cfg.dry_run = document.getElementById('dryRunCheck').checked;
        cfg.incremental = document.getElementById('incrementalCheck').checked;
        cfg.download_images = document.getElementById('downloadImagesCheck').checked;
        cfg.add_year_to_folder = document.getElementById('addYearCheck').checked;
        cfg.force_chinese_name = document.getElementById('forceChineseCheck').checked;
        cfg.max_workers = parseInt(document.getElementById('maxWorkersInput').value) || 3;
        cfg.min_file_size_mb = parseInt(document.getElementById('minFileSizeInput').value) || 0;
        cfg.video_extensions = document.getElementById('videoExtInput').value.split(',').map(s => s.trim()).filter(s => s);
        cfg.ignore_patterns = document.getElementById('ignorePatternsInput').value.split(',').map(s => s.trim()).filter(s => s);

        cfg.tmdb_api = cfg.tmdb_api || {};
        cfg.tmdb_api.api_key = document.getElementById('tmdbKeyInput').value.trim();
        cfg.tmdb_api.language = document.getElementById('tmdbLanguageInput').value.trim();

        // ========== 代理自动补全协议 ==========
        let proxy = document.getElementById('tmdbProxyInput').value.trim();
        if (proxy) {
            // 如果用户只输入了 IP:端口（不含协议），自动添加 http://
            if (!proxy.startsWith('http://') && !proxy.startsWith('https://') && !proxy.startsWith('socks5://')) {
                proxy = 'http://' + proxy;
            }
        }
        cfg.tmdb_api.proxy = proxy;
        // ========== 代理自动补全结束 ==========

        const aiKey = document.getElementById('aiKeyInput').value.trim();
        cfg.ai_parser = cfg.ai_parser || {};
        cfg.ai_parser.enabled = document.getElementById('aiParserEnabledCheck').checked;
        // 如果启用了 AI 但没有 Key，强制禁用
        if (cfg.ai_parser.enabled && !aiKey) {
            cfg.ai_parser.enabled = false;
            app.showToast('⚠️ AI 解析已自动禁用：未填写 API Key', 'warning', 3000);
        }
        cfg.ai_parser.batch_folder_enabled = document.getElementById('aiBatchFolderCheck').checked;
        cfg.ai_parser.provider = document.getElementById('aiProviderSelect').value;
        cfg.ai_parser.model = document.getElementById('aiModelInput').value;
        cfg.ai_parser.base_url = document.getElementById('aiBaseUrlInput').value;
        cfg.ai_parser.api_key = aiKey;

        cfg.ai_plot_enhance = cfg.ai_plot_enhance || {};
        cfg.ai_plot_enhance.enabled = document.getElementById('aiPlotEnhanceCheck').checked;
        cfg.ai_plot_enhance.temperature = parseFloat(document.getElementById('plotTempInput').value) || 0.7;
        cfg.ai_plot_enhance.max_tokens = parseInt(document.getElementById('plotTokensInput').value) || 500;
        cfg.ai_plot_enhance.api_key = aiKey;

        cfg.subtitle = cfg.subtitle || {};
        cfg.subtitle.enabled = document.getElementById('subtitleEnabledCheck').checked;
        cfg.subtitle.auto_sync = document.getElementById('subtitleAutoSyncCheck').checked;
        cfg.subtitle.link_subtitles = document.getElementById('subtitleLinkCheck').checked;
        cfg.subtitle.sync_timeout = parseInt(document.getElementById('subtitleSyncTimeoutInput').value) || 60;

        cfg.anime_parser = cfg.anime_parser || {};
        cfg.anime_parser.enabled = document.getElementById('animeParserEnabledCheck').checked;
        cfg.anime_parser.fallback_to_regex = document.getElementById('animeParserFallbackCheck').checked;

        cfg.subtitle_center = cfg.subtitle_center || {};
        cfg.subtitle_center.default_source_folder = document.getElementById('subSourceFolderInput').value.trim();
        cfg.subtitle_center.auto_match_threshold = parseInt(document.getElementById('matchThresholdInput').value) || 75;
        cfg.subtitle_center.auto_sync_enabled = document.getElementById('subtitleCenterAutoSyncCheck').checked;
        cfg.subtitle_center.overwrite_existing = document.getElementById('overwriteCheck').checked;

        cfg.auth = cfg.auth || {};
        cfg.auth.enabled = document.getElementById('authEnabledCheck').checked;
        cfg.auth.username = document.getElementById('authUsernameInput').value.trim();
        const pwdInput = document.getElementById('authPasswordInput');
        const newPassword = pwdInput.value;
        if (newPassword === '') {
            if (originalPassword === '******' || !originalPassword) {
                cfg.auth.password = '';
            }
        } else {
            cfg.auth.password = newPassword;
        }

        return cfg;
    }

    // ---------- 引导教程相关 ----------
    function toggleTutorial() {
        const panel = document.getElementById('tutorialPanel');
        if (panel) {
            panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
        }
    }

    function scrollToConfig() {
        const panel = document.querySelector('h2 + form') || document.getElementById('configForm');
        if (panel) {
            panel.scrollIntoView({ behavior: 'smooth' });
        }
    }

    function dismissOnboarding() {
        const banner = document.getElementById('onboardingBanner');
        if (banner) banner.style.display = 'none';
        localStorage.setItem('onboardingDismissed', 'true');
    }

    function checkOnboarding() {
        if (localStorage.getItem('onboardingDismissed') === 'true') return;

        const cfg = app.configCache;
        const missing = [];
        if (!cfg.tmdb_api?.api_key) missing.push('TMDB API Key');
        if ((cfg.source_folders || []).length === 0) missing.push('源文件夹');
        if (!cfg.tv_target_folder) missing.push('剧集目标文件夹');
        if (!cfg.movie_target_folder) missing.push('电影目标文件夹');

        const banner = document.getElementById('onboardingBanner');
        if (!banner) return;

        if (missing.length > 0) {
            const msg = banner.querySelector('#onboardingMessage');
            if (msg) {
                msg.innerHTML = `检测到尚未配置：<strong>${missing.join('、')}</strong>。`;
            }
            banner.style.display = 'block';
        } else {
            banner.style.display = 'none';
        }
    }

    // ---------- 公开接口 ----------
    return {
        loadConfig: async function() {
            try {
                const resp = await fetch('/api/config');
                app.configCache = await resp.json();
                app.configCache.auth = app.configCache.auth || { enabled: false, username: 'admin', password: '' };
                populateForm(app.configCache);
                if (typeof App.MappingRules !== 'undefined') await App.MappingRules.loadMappingRules();
                if (typeof App.MediaManager !== 'undefined') App.MediaManager.refreshLibrary();
                checkOnboarding();
            } catch (e) {
                alert('加载配置失败');
            }
        },

        saveConfig: async function() {
            try {
                const cfg = collectConfigFromForm();
                const resp = await fetch('/api/config', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(cfg)
                });
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast('✅ 配置已保存到 auto_config.json', 'success');
                    await this.loadConfig();
                } else {
                    app.showToast('保存失败: ' + data.message, 'error');
                }
            } catch (e) {
                app.showToast('保存出错: ' + e.message, 'error');
            }
        },

        setDefaultSubtitleFolder: async function() {
            const folder = document.getElementById('subSourceFolderInput').value.trim();
            if (!folder) { app.showToast('请先输入或选择一个文件夹', 'warning'); return; }
            await this.saveConfig();
            app.showToast(`⭐ 已将 "${folder}" 设为默认字幕文件夹`, 'success');
        },

        testTmdbConnection: async function() {
            const btn = document.getElementById('testTmdbBtn');
            const originalText = btn.textContent;
            btn.disabled = true;
            btn.textContent = '⏳ 测试中...';

            try {
                const resp = await fetch('/api/tmdb/test');
                const data = await resp.json();
                if (data.status === 'success') {
                    app.showToast(`✅ TMDB 连接正常！图片服务器: ${data.images_base_url || '默认'}`, 'success', 5000);
                } else {
                    app.showToast(`❌ TMDB 连接失败: ${data.message}`, 'error', 5000);
                }
            } catch (e) {
                app.showToast(`❌ 请求失败: ${e.message}`, 'error');
            } finally {
                btn.disabled = false;
                btn.textContent = originalText;
            }
        },

        // 引导教程方法
        toggleTutorial: toggleTutorial,
        scrollToConfig: scrollToConfig,
        dismissOnboarding: dismissOnboarding,
        checkOnboarding: checkOnboarding,

        // AI 校验方法
        onAiEnabledChange: handleAiEnabledChange,
        validateAiKey: function() {
            const aiKey = document.getElementById('aiKeyInput').value.trim();
            if (!aiKey) {
                app.showToast('❌ 请先填写 AI API Key，或关闭 AI 解析功能', 'warning', 4000);
                return false;
            }
            return true;
        }
    };
})(window.App);
