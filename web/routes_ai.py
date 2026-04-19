#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AI 相关 API 路由（流式简介润色测试）
"""

import json
from flask import request, jsonify, Response, stream_with_context
from core import ai_client


def register(app):
    @app.route('/api/ai/stream_enhance', methods=['POST'])
    def stream_ai_enhance():
        data = request.json
        title = data.get('title', '')
        original_plot = data.get('original_plot', '')
        ai_config = data.get('ai_config', {})

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
            model = ai_config.get("model", "deepseek-chat")
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
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)})}\n\n"

        return Response(stream_with_context(generate()), mimetype='text/event-stream')
