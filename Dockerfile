FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    DEBIAN_FRONTEND=noninteractive

# 1. 替换 Debian 官方源为阿里云镜像（加速 apt-get）
RUN sed -i 's|deb.debian.org|mirrors.aliyun.com|g' /etc/apt/sources.list.d/debian.sources

# 2. 安装系统依赖（包含编译工具）
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

# 3. 创建非 root 用户
RUN groupadd -r animeman && useradd -r -g animeman animeman

WORKDIR /app

# 4. 配置 pip 国内镜像源（加速 Python 包下载）
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# 5. 复制依赖文件并安装（增加超时和重试）
COPY requirements.txt .
RUN pip install --no-cache-dir \
    --timeout 120 \
    --retries 5 \
    -r requirements.txt

# 6. 复制项目代码
COPY . .

# 7. 创建必要目录并设置权限
RUN mkdir -p /app/config /app/cache /app/logs && \
    chown -R animeman:animeman /app

USER animeman

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/status || exit 1

CMD ["python", "web_app.py"]
