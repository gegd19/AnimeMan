#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
特辑映射规则管理 API
"""

from flask import request, jsonify
from core import config_manager
from core.special_mapping import validate_mapping_rule, normalize_mapping_rule
from .auth import require_auth

CONFIG_PATH = "auto_config.json"


def register(app):
    from flask import g
    from werkzeug.exceptions import NotFound, Conflict
    config_path = app.config.get('CONFIG_PATH', CONFIG_PATH)

    @app.route('/api/special_mappings', methods=['GET'])
    def get_mappings():
        return jsonify({'mappings': config_manager.load_config(config_path)['special_mappings']})

    @app.route('/api/special_mappings', methods=['POST'])
    @require_auth
    def add_mapping():
        normalized = normalize_mapping_rule(request.json['rule'])
        def mutate(config):
            mappings = config['special_mappings']
            if any(rule['keyword'].lower() == normalized['keyword'].lower() for rule in mappings):
                raise Conflict('该关键词已存在')
            mappings.append(normalized)
            return config
        config_manager.update_config(mutate, config_path)
        return jsonify({'status': 'success', 'rule': normalized})

    @app.route('/api/special_mappings', methods=['PUT'])
    @require_auth
    def update_mapping():
        index = request.json['index']
        normalized = normalize_mapping_rule(request.json['rule'])
        def mutate(config):
            mappings = config['special_mappings']
            if index >= len(mappings):
                raise NotFound('记录不存在')
            if any(i != index and rule['keyword'].lower() == normalized['keyword'].lower()
                   for i, rule in enumerate(mappings)):
                raise Conflict('该关键词已存在')
            mappings[index] = normalized
            return config
        config_manager.update_config(mutate, config_path)
        return jsonify({'status': 'success', 'rule': normalized})

    @app.route('/api/special_mappings', methods=['DELETE'])
    @require_auth
    def delete_mapping():
        index = g.validated_query['index']
        removed = []
        def mutate(config):
            mappings = config['special_mappings']
            if index >= len(mappings):
                raise NotFound('记录不存在')
            removed.append(mappings.pop(index))
            return config
        config_manager.update_config(mutate, config_path)
        return jsonify({'status': 'success', 'removed': removed[0]})
