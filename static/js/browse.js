/**
 * 目录浏览模块（适配安全限制）
 */
window.App = window.App || {};
App.Browse = (function(app) {
    'use strict';

    const modalId = 'browseModal';
    const currentPathSpan = 'currentPath';
    const dirListId = 'dirList';

    function _renderDirList(items) {
        const list = document.getElementById(dirListId);
        list.innerHTML = '';
        if (!items || items.length === 0) {
            list.innerHTML = '<li class="is-empty">这里没有子文件夹，或没有访问权限</li>';
            return;
        }
        items.forEach(item => {
            const li = app.el('li', {tabIndex: 0, title: item.path, attrs: {role: 'button'}});
            li.append(app.el('span', {className: 'folder-icon', text: '📁'}), document.createTextNode(' ' + item.name));
            li.addEventListener('click', () => _browsePath(item.path).catch(error => app.showToast(error.message, 'error')));
            list.appendChild(li);
        });
    }

    async function _loadDrives() {
        const resp = await app.fetch('/api/drives');
        const drives = await resp.json();
        _renderDirList(drives);
        app.currentBrowsePath = '';
        document.getElementById(currentPathSpan).innerText = drives.length ? '请选择允许的根目录' : '/';
    }

    async function _browsePath(path) {
        let resp;
        try {
            resp = await app.fetch(`/api/browse?path=${encodeURIComponent(path)}`);
        } catch (error) {
            if (error.status === 403) return; // The shared request helper shows why.
            throw error;
        }
        const data = await resp.json();
        if (data.dirs) {
            _renderDirList(data.dirs);
            app.currentBrowsePath = data.current;
            document.getElementById(currentPathSpan).innerText = data.current;
            // 隐藏或显示“上一级”按钮（根据是否有 parent）
            const upBtn = document.querySelector('#browseModal button[onclick*="goUp"]');
            if (upBtn) {
                upBtn.disabled = !data.parent;
            }
        } else {
            app.showToast('无法浏览该目录，可能是权限不足或路径无效', 'error');
        }
    }

    async function _goUp() {
        if (!app.currentBrowsePath) {
            await _loadDrives();
            return;
        }
        let resp;
        try {
            resp = await app.fetch(`/api/browse?path=${encodeURIComponent(app.currentBrowsePath)}`);
        } catch (error) {
            if (error.status === 403) return _loadDrives();
            throw error;
        }
        const data = await resp.json();
        if (data.parent) {
            await _browsePath(data.parent);
        } else {
            await _loadDrives();
        }
    }

    function _closeModal() {
        document.getElementById(modalId).style.display = 'none';
    }

    return {
        openBrowser: function(field) {
            app.targetField = field;
            document.getElementById(modalId).style.display = 'block';
            _loadDrives();
        },
        closeModal: _closeModal,
        loadDrives: _loadDrives,
        browsePath: _browsePath,
        goUp: _goUp,
        selectCurrentPath: function() {
            if (!app.currentBrowsePath) {
                app.showToast('请先点击一个文件夹进入，或点击“根目录”选择起始路径', 'warning');
                return;
            }
            let inputId;
            switch (app.targetField) {
                case 'source': inputId = 'sourceFoldersInput'; break;
                case 'tv_target': inputId = 'tvTargetFolderInput'; break;
                case 'movie_target': inputId = 'movieTargetFolderInput'; break;
                case 'sub_source': inputId = 'subSourceFolderInput'; break;
                case 'alias_scope': inputId = 'recognitionAliasScope'; break;
                case 'numbering_scope': inputId = 'numberingScope'; break;
                default: return;
            }
            const input = document.getElementById(inputId);
            input.value = app.currentBrowsePath;
            // 让依赖输入事件的逻辑（未保存提示、预览失效）知道值变了。
            input.dispatchEvent(new Event('input', {bubbles: true}));
            _closeModal();
            const isRuleScope = app.targetField === 'alias_scope' || app.targetField === 'numbering_scope';
            app.showToast(isRuleScope ? '已填入作用域，请重新预览' : '已填入路径，保存配置后生效', 'info');
        }
    };
})(window.App);
