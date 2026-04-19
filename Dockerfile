# 使用官方 Python 3.11 轻量镜像
FROM python:3.11-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive

# 安装系统依赖：ffmpeg（用于视频信息提取和字幕同步）、curl（健康检查）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r animeman && useradd -r -g animeman animeman

# 设置工作目录
WORKDIR /app

# 复制依赖文件并安装 Python 包
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建必要的目录并设置权限
RUN mkdir -p /app/config /app/cache /app/logs && \
    chown -R animeman:animeman /app

# 切换到非 root 用户
USER animeman

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

# 启动命令
CMD ["python", "web_app.py"]
