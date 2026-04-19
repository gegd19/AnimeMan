#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Flask 应用工厂（含全局认证钩子）
"""

import os
from flask import Flask, render_template, request

from . import routes_config
from . import routes_task
from . import routes_browse
from . import routes_subtitle
from . import routes_ai
from . import routes_failed
from . import routes_mapping
from . import routes_offline
from . import routes_media
from . import routes_cache


def create_app():
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')
    app.secret_key = os.environ.get("SECRET_KEY", os.urandom(24).hex())

    @app.before_request
    def before_request():
        if request.path.startswith('/static/'):
            return None

        public_prefixes = ['/api/status', '/api/log', '/api/drives', '/api/browse', '/media_poster/']
        for prefix in public_prefixes:
            if request.path.startswith(prefix):
                return None

        if request.path == '/api/config' and request.method == 'GET':
            return None

        if request.path == '/':
            return None

        from .auth import check_auth, authenticate
        auth = request.authorization
        if not auth:
            return authenticate()
        if not check_auth(auth.username, auth.password):
            return authenticate()
        return None

    @app.route('/')
    def index():
        return render_template('index.html')

    routes_config.register(app)
    routes_task.register(app)
    routes_browse.register(app)
    routes_subtitle.register(app)
    routes_ai.register(app)
    routes_failed.register(app)
    routes_mapping.register(app)
    routes_offline.register(app)
    routes_media.register(app)
    routes_cache.register(app)


    return app
