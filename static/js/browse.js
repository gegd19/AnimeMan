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
            list.innerHTML = '<li style="padding:12px;color:#6c757d;justify-content:center;">📭 空目录或无权限访问</li>';
            return;
        }
        items.forEach(item => {
            const li = document.createElement('li');
            li.innerHTML = `<span class="folder-icon">📁</span> ${app.escapeHtml(item.name)}`;
            li.onclick = () => _browsePath(item.path);
            list.appendChild(li);
        });
    }

    async function _loadDrives() {
        const resp = await fetch('/api/drives');
        const drives = await resp.json();
        _renderDirList(drives);
        app.currentBrowsePath = '';
        document.getElementById(currentPathSpan).innerText = drives.length ? '请选择允许的根目录' : '/';
    }

    async function _browsePath(path) {
        const resp = await fetch(`/api/browse?path=${encodeURIComponent(path)}`);
        if (resp.status === 403) {
            alert('禁止访问此目录');
            return;
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
            alert('无法浏览该目录，可能是权限不足或路径无效');
        }
    }

    async function _goUp() {
        if (!app.currentBrowsePath) {
            await _loadDrives();
            return;
        }
        const resp = await fetch(`/api/browse?path=${encodeURIComponent(app.currentBrowsePath)}`);
        if (resp.status === 403) {
            await _loadDrives();
            return;
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
                alert('请先点击一个文件夹进入，或点击“根目录”选择起始路径');
                return;
            }
            let inputId;
            switch (app.targetField) {
                case 'source': inputId = 'sourceFoldersInput'; break;
                case 'tv_target': inputId = 'tvTargetFolderInput'; break;
                case 'movie_target': inputId = 'movieTargetFolderInput'; break;
                case 'sub_source': inputId = 'subSourceFolderInput'; break;
                default: return;
            }
            document.getElementById(inputId).value = app.currentBrowsePath;
            alert('✅ 已设置路径');
            _closeModal();
        }
    };
})(window.App);
