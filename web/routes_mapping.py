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
    @app.route('/api/special_mappings', methods=['GET'])
    def get_mappings():
        config = config_manager.load_config(CONFIG_PATH)
        mappings = config.get("special_mappings", [])
        return jsonify({"mappings": mappings})

    @app.route('/api/special_mappings', methods=['POST'])
    @require_auth
    def add_mapping():
        data = request.json
        rule = data.get("rule", {})

        valid, error = validate_mapping_rule(rule)
        if not valid:
            return jsonify({"status": "error", "message": error}), 400

        normalized = normalize_mapping_rule(rule)

        config = config_manager.load_config(CONFIG_PATH)
        mappings = config.get("special_mappings", [])

        for existing in mappings:
            if existing.get("keyword", "").lower() == normalized["keyword"].lower():
                return jsonify({"status": "error", "message": "该关键词已存在"}), 400

        mappings.append(normalized)
        config["special_mappings"] = mappings
        config_manager.save_config(config, CONFIG_PATH)

        return jsonify({"status": "success", "rule": normalized})

    @app.route('/api/special_mappings', methods=['PUT'])
    @require_auth
    def update_mapping():
        data = request.json
        index = data.get("index")
        rule = data.get("rule", {})

        if index is None:
            return jsonify({"status": "error", "message": "缺少索引"}), 400

        valid, error = validate_mapping_rule(rule)
        if not valid:
            return jsonify({"status": "error", "message": error}), 400

        normalized = normalize_mapping_rule(rule)

        config = config_manager.load_config(CONFIG_PATH)
        mappings = config.get("special_mappings", [])

        if index < 0 or index >= len(mappings):
            return jsonify({"status": "error", "message": "索引越界"}), 400

        for i, existing in enumerate(mappings):
            if i != index and existing.get("keyword", "").lower() == normalized["keyword"].lower():
                return jsonify({"status": "error", "message": "该关键词已存在"}), 400

        mappings[index] = normalized
        config["special_mappings"] = mappings
        config_manager.save_config(config, CONFIG_PATH)

        return jsonify({"status": "success", "rule": normalized})

    @app.route('/api/special_mappings', methods=['DELETE'])
    @require_auth
    def delete_mapping():
        index = request.args.get("index")
        if index is None:
            return jsonify({"status": "error", "message": "缺少索引"}), 400

        try:
            index = int(index)
        except ValueError:
            return jsonify({"status": "error", "message": "索引无效"}), 400

        config = config_manager.load_config(CONFIG_PATH)
        mappings = config.get("special_mappings", [])

        if index < 0 or index >= len(mappings):
            return jsonify({"status": "error", "message": "索引越界"}), 400

        removed = mappings.pop(index)
        config["special_mappings"] = mappings
        config_manager.save_config(config, CONFIG_PATH)

        return jsonify({"status": "success", "removed": removed})
