FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive

# 安装系统依赖（包括编译工具和音频库）
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        curl \
        tzdata \
        gcc \
        python3-dev \
        libsndfile1 \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# 创建非 root 用户
RUN groupadd -r animeman && useradd -r -g animeman animeman

WORKDIR /app

# 复制依赖文件并安装
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制项目代码
COPY . .

# 创建必要目录并设置权限
RUN mkdir -p /app/config /app/cache /app/logs && \
    chown -R animeman:animeman /app

USER animeman

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

CMD ["python", "web_app.py"]
