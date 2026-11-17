"""Offline anime databases: status and a manual download / update."""
from flask import jsonify

from core import anime_db
from .auth import require_auth
from .task_state import request_config


def register(app):
    config_path = app.config['CONFIG_PATH']

    @app.route('/api/anime_db/status', methods=['GET'])
    @require_auth
    def anime_db_status():
        return jsonify(anime_db.status())

    @app.route('/api/anime_db/update', methods=['POST'], endpoint='update_anime_db')
    @require_auth
    def update_anime_db():
        started = anime_db.update_in_background(request_config(config_path))
        return jsonify({'status': 'started' if started else 'running', **anime_db.status()})
