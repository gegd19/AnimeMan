"""Authenticated, bounded management of explicitly saved recognition rules."""
from flask import g, jsonify
from core import user_recognition_rules as rules
from .auth import require_auth
from .task_state import request_config


def register(app):
    config_path = app.config['CONFIG_PATH']

    @app.route('/api/recognition_rules', methods=['GET'])
    @require_auth
    def get_recognition_rules():
        config = request_config(config_path)
        return jsonify({'rules': [r for r in rules.list_rules(config) if not r['deleted']]})

    @app.route('/api/recognition_rules/state', methods=['POST'])
    @require_auth
    def set_recognition_rule_state():
        try:
            rules.set_enabled(request_config(config_path), g.validated_body['id'], g.validated_body['enabled'])
        except rules.RuleValidationError as error:
            return jsonify({'status': 'error', 'message': str(error)}), 400
        return jsonify({'status': 'success'})

    @app.route('/api/recognition_rules/delete', methods=['POST'])
    @require_auth
    def delete_recognition_rule():
        try:
            rules.delete_rule(request_config(config_path), g.validated_body['id'])
        except rules.RuleValidationError as error:
            return jsonify({'status': 'error', 'message': str(error)}), 400
        return jsonify({'status': 'success'})
