#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 相关 API 路由（流式简介润色测试）
"""

import json
from flask import request, jsonify, Response, stream_with_context
from core import ai_client, config_manager
from .config_secrets import configured


def register(app):
    config_path = app.config.get("CONFIG_PATH", "auto_config.json")

    @app.route('/api/ai/stream_enhance', methods=['POST'])
    def stream_ai_enhance():
        data = request.json
        if not isinstance(data, dict):
            return jsonify({"error": "请求必须为对象"}), 400
        title = data.get('title', '')
        original_plot = data.get('original_plot', '')
        overrides = data.get('ai_config', {})
        source = data.get('ai_config_source', 'ai_parser')
        if source not in ('ai_parser', 'ai_plot_enhance') or not isinstance(overrides, dict):
            return jsonify({"error": "无效的 AI 配置来源"}), 400
        saved = config_manager.load_config(config_path).get(source, {})
        ai_config = {**saved, **overrides}
        if not overrides.get('api_key'):
            # Do not send a server-held credential to a transient custom endpoint.
            for field in ('provider', 'base_url'):
                if field in overrides and str(overrides[field]).rstrip('/') != str(saved.get(field, '')).rstrip('/'):
                    return jsonify({"error": "使用已保存密钥时，请先保存提供商和地址变更"}), 400
            ai_config['api_key'] = saved.get('api_key', '')
        if not configured(ai_config.get('api_key')):
            return jsonify({"error": "请先配置 AI API Key"}), 400

        if not isinstance(title, str) or not isinstance(original_plot, str):
            return jsonify({"error": "标题和简介必须为字符串"}), 400

        if len(title) > 200 or len(original_plot) > 5000:
            return jsonify({"error": "标题或简介过长"}), 400
        if not title or not original_plot:
            return jsonify({"error": "缺少标题或简介"}), 400

        def generate():
            prompt_template = ai_config.get(
                'prompt_template',
                "你是一个专业的影视剧文案。请将以下剧情简介改写得更加生动、吸引人，语言流畅自然，可以适当增加一些悬念和感染力。请直接输出改写后的简介，不要添加额外说明。\n\n原标题：{title}\n原简介：{original_plot}\n\n优化后简介："
            )
            prompt = prompt_template.format(title=title, original_plot=original_plot)

            provider = ai_config.get("provider", "deepseek")
            api_key = ai_config.get("api_key")
            model = ai_config.get("model", "deepseek-flash")
            base_url = ai_config.get("base_url", "https://api.deepseek.com")
            temperature = ai_config.get("temperature", 0.7)
            max_tokens = ai_config.get("max_tokens", 500)

            url_map = {
                "deepseek": f"{base_url}/v1/chat/completions",
                "openai": "https://api.openai.com/v1/chat/completions",
                "zhipu": "https://open.bigmodel.cn/api/paas/v4/chat/completions",
                "qwen": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
            }
            url = url_map.get(provider)
            if not url:
                yield f"data: {json.dumps({'error': f'不支持的 AI 提供商: {provider}'})}\n\n"
                return

            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True
            }

            resp = None
            session = None
            try:
                import requests
                from requests.adapters import HTTPAdapter
                from urllib3.util.retry import Retry
                session = requests.Session()
                retries = Retry(total=3, backoff_factor=1.0)
                session.mount('https://', HTTPAdapter(max_retries=retries))
                resp = session.post(url, headers=headers, json=payload, stream=True, timeout=(5, 60))
                resp.raise_for_status()

                for line in resp.iter_lines(decode_unicode=True):
                    if line and line.startswith("data: "):
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            break
                        try:
                            chunk = json.loads(data_str)
                            content = chunk['choices'][0]['delta'].get('content', '')
                            if content:
                                yield f"data: {json.dumps({'content': content})}\n\n"
                        except Exception:
                            continue
                yield f"data: {json.dumps({'done': True})}\n\n"
            except Exception:
                yield f"data: {json.dumps({'error': 'AI 请求失败，请检查服务端配置或稍后重试'})}\n\n"
            finally:
                if resp is not None:
                    resp.close()
                if session is not None:
                    session.close()

        return Response(stream_with_context(generate()), mimetype='text/event-stream')
