#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Emby Auto Processor Web 启动入口（酷炫彩色启动信息）
"""

import sys
import logging
import socket
from pathlib import Path
from core.logger import setup_logging
setup_logging()

# 确保项目根目录在 sys.path 中
sys.path.insert(0, str(Path(__file__).parent))

from web import create_app

# 配置日志文件
LOG_FILE = "auto_processor_errors.log"
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.ERROR,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

# ========== 彩色输出辅助 ==========
class Colors:
    """ANSI 颜色转义码"""
    HEADER = '\033[95m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BOLD = '\033[1m'
    UNDERLINE = '\033[4m'
    END = '\033[0m'

def print_colored(text, color=Colors.END, bold=False):
    """打印带颜色的文本"""
    prefix = Colors.BOLD if bold else ""
    print(f"{prefix}{color}{text}{Colors.END}")

def get_local_ip():
    """获取本机局域网 IP"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "无法获取"

# ========== 酷炫启动横幅 ==========
def print_banner():
    banner = r"""
    █████╗ ███╗   ██╗██╗███╗   ███╗███████╗███╗   ███╗ █████╗ ███╗   ██╗
   ██╔══██╗████╗  ██║██║████╗ ████║██╔════╝████╗ ████║██╔══██╗████╗  ██║
   ███████║██╔██╗ ██║██║██╔████╔██║█████╗  ██╔████╔██║███████║██╔██╗ ██║
   ██╔══██║██║╚██╗██║██║██║╚██╔╝██║██╔══╝  ██║╚██╔╝██║██╔══██║██║╚██╗██║
   ██║  ██║██║ ╚████║██║██║ ╚═╝ ██║███████╗██║ ╚═╝ ██║██║  ██║██║ ╚████║
   ╚═╝  ╚═╝╚═╝  ╚═══╝╚═╝╚═╝     ╚═╝╚══════╝╚═╝     ╚═╝╚═╝  ╚═╝╚═╝  ╚═══╝
    """
    print_colored(banner, Colors.CYAN, bold=True)
    print_colored("   🎌  AnimeMan · 番剧智能管家  🎌", Colors.GREEN, bold=True)
    print_colored("   " + "─" * 56, Colors.BLUE)
    print()
    print_colored("   ✨ 让每一部番，终归此匣 · 全自动整理 ✨", Colors.YELLOW)
    print()

def print_startup_info(host, port):
    """打印启动信息"""
    local_ip = get_local_ip()
    print_colored("🚀 服务启动成功！", Colors.GREEN, bold=True)
    print()
    print_colored("📍 访问地址：", Colors.YELLOW, bold=True)
    print(f"   ➜ 本地地址: {Colors.CYAN}http://127.0.0.1:{port}{Colors.END}")
    if local_ip != "无法获取":
        print(f"   ➜ 局域网地址: {Colors.CYAN}http://{local_ip}:{port}{Colors.END}")
    print()
    print_colored("📄 日志文件：", Colors.YELLOW, bold=True)
    print(f"   ➜ {Path(LOG_FILE).resolve()}")
    print()
    print_colored("⌨️  按 CTRL+C 停止服务", Colors.BLUE)
    print_colored("─" * 50, Colors.BLUE)
    print()

if __name__ == '__main__':
    # 打印启动横幅
    print_banner()

    # 创建 Flask 应用
    app = create_app()

    # 配置运行参数
    host = '0.0.0.0'
    port = 8000

    # 打印访问信息
    print_startup_info(host, port)

    # 启动 Flask 开发服务器（关闭 Flask 默认的启动横幅，使用我们自己的）
    import sys
    import logging as flask_logging
    # 关闭 Flask 的默认启动消息
    flask_logging.getLogger('werkzeug').disabled = True
    cli = sys.modules.get('flask.cli')
    if cli:
        cli.show_server_banner = lambda *args, **kwargs: None

    # 自定义请求日志（彩色）
    from flask import request
    import time

    @app.before_request
    def log_request():
        # 忽略静态资源请求的日志
        if request.path.startswith('/static'):
            return
        request.start_time = time.time()

    @app.after_request
    def log_response(response):
        if hasattr(request, 'start_time') and not request.path.startswith('/static'):
            duration = (time.time() - request.start_time) * 1000
            status_color = Colors.GREEN if 200 <= response.status_code < 300 else (Colors.YELLOW if 300 <= response.status_code < 400 else Colors.RED)
            method_color = Colors.CYAN
            print(f"{Colors.BLUE}[{time.strftime('%H:%M:%S')}]{Colors.END} "
                  f"{method_color}{request.method}{Colors.END} "
                  f"{request.path} "
                  f"{status_color}{response.status_code}{Colors.END} "
                  f"({duration:.1f}ms)")
        return response

    # 启动应用
    try:
        app.run(host=host, port=port, debug=False, threaded=True)
    except KeyboardInterrupt:
        print()
        print_colored("🛑 服务已停止", Colors.YELLOW, bold=True)
        sys.exit(0)
