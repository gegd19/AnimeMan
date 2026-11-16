/**
 * 特辑手动映射规则管理模块
 */
window.App = window.App || {};
App.MappingRules = (function(app) {
    'use strict';

    const modalId = 'mappingModal';
    const tableBodyId = 'mappingRulesBody';
    const formMappingMediaType = document.getElementById('mappingMediaType');
    const mappingTvFields = document.getElementById('mappingTvFields');

    if (formMappingMediaType) {
        formMappingMediaType.addEventListener('change', function() {
            mappingTvFields.style.display = this.value === 'tv' ? 'block' : 'none';
        });
    }

    // ---------- 私有函数 ----------
    function _renderTable() {
        const tbody = document.getElementById(tableBodyId);
        tbody.innerHTML = '';
        if (app.mappingRules.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6">还没有规则。点击「新增规则」添加第一条。</td></tr>';
            return;
        }
        app.mappingRules.forEach((r, i) => {
            const episode = r.media_type === 'tv' ? `S${String(r.season || 0).padStart(2, '0')}E${String(r.episode || 1).padStart(2, '0')}` : '-';
            const tr = app.el('tr', {}, app.el('td', {}, app.el('code', {text: r.keyword})),
                app.el('td', {text: r.tmdb_id}), app.el('td', {text: r.media_type === 'movie' ? '电影' : '剧集'}),
                app.el('td', {text: episode}), app.el('td', {}, app.el('span', {className: r.enabled !== false ? 'badge is-green' : 'badge', text: r.enabled !== false ? '启用' : '停用'})),
                app.el('td', {}, app.button('编辑', () => App.MappingRules.editMappingRule(i)),
                    app.button('删除', () => App.MappingRules.deleteMappingRule(i), 'danger')));
            tbody.appendChild(tr);
        });
    }

    function _closeModal() {
        document.getElementById(modalId).style.display = 'none';
    }

    // ---------- 公开接口 ----------
    return {
        /**
         * 加载映射规则
         */
        loadMappingRules: async function() {
            const resp = await app.fetch('/api/special_mappings');
            const data = await resp.json();
            app.mappingRules = data.mappings || [];
            _renderTable();
        },

        /**
         * 打开新增规则模态框
         */
        openMappingModal: function() {
            document.getElementById('mappingModalTitle').innerText = '新增映射规则';
            document.getElementById('editingMappingIndex').value = '-1';
            document.getElementById('mappingKeyword').value = '';
            document.getElementById('mappingTmdbId').value = '';
            document.getElementById('mappingMediaType').value = 'tv';
            document.getElementById('mappingSeason').value = '0';
            document.getElementById('mappingEpisode').value = '1';
            document.getElementById('mappingDescription').value = '';
            document.getElementById('mappingEnabled').checked = true;
            mappingTvFields.style.display = 'block';
            document.getElementById(modalId).style.display = 'block';
        },

        /**
         * 编辑已有规则
         */
        editMappingRule: function(idx) {
            const r = app.mappingRules[idx];
            document.getElementById('mappingModalTitle').innerText = '编辑映射规则';
            document.getElementById('editingMappingIndex').value = idx;
            document.getElementById('mappingKeyword').value = r.keyword;
            document.getElementById('mappingTmdbId').value = r.tmdb_id;
            document.getElementById('mappingMediaType').value = r.media_type;
            document.getElementById('mappingSeason').value = r.season ?? 0;
            document.getElementById('mappingEpisode').value = r.episode ?? 1;
            document.getElementById('mappingDescription').value = r.description || '';
            document.getElementById('mappingEnabled').checked = r.enabled !== false;
            mappingTvFields.style.display = r.media_type === 'tv' ? 'block' : 'none';
            document.getElementById(modalId).style.display = 'block';
        },

        /**
         * 关闭模态框
         */
        closeMappingModal: _closeModal,

        /**
         * 保存规则（新增或更新）
         */
        saveMappingRule: async function() {
            const idx = parseInt(document.getElementById('editingMappingIndex').value);
            const rule = {
                keyword: document.getElementById('mappingKeyword').value.trim(),
                tmdb_id: parseInt(document.getElementById('mappingTmdbId').value) || 0,
                media_type: document.getElementById('mappingMediaType').value,
                season: parseInt(document.getElementById('mappingSeason').value) ?? 0,
                episode: parseInt(document.getElementById('mappingEpisode').value) ?? 1,
                description: document.getElementById('mappingDescription').value.trim(),
                enabled: document.getElementById('mappingEnabled').checked
            };
            if (!rule.keyword || !rule.tmdb_id) {
                app.showToast('关键词和 TMDB ID 不能为空', 'warning');
                return;
            }
            const method = idx >= 0 ? 'PUT' : 'POST';
            const body = idx >= 0 ? { index: idx, rule } : { rule };
            const resp = await app.fetch('/api/special_mappings', {
                method,
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body)
            });
            const data = await resp.json();
            if (data.status === 'success') {
                await this.loadMappingRules();
                _closeModal();
            } else {
                app.showToast('保存失败：' + (data.message || '未知错误'), 'error');
            }
        },

        /**
         * 删除规则
         */
        deleteMappingRule: async function(idx) {
            if (!confirm('确定要删除这条映射规则吗？')) return;
            const resp = await app.fetch(`/api/special_mappings?index=${idx}`, { method: 'DELETE' });
            const data = await resp.json();
            if (data.status === 'success') {
                await this.loadMappingRules();
            } else {
                app.showToast('删除失败', 'error');
            }
        }
    };
})(window.App);
