FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS builder
RUN apt-get update && apt-get install -y --no-install-recommends gcc \
    && rm -rf /var/lib/apt/lists/*
RUN python -m venv /opt/venv
COPY requirements.lock /tmp/requirements.lock
RUN /opt/venv/bin/pip install --no-cache-dir --require-hashes -r /tmp/requirements.lock \
    && /opt/venv/bin/pip check

FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70
ENV PATH="/opt/venv/bin:$PATH" PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai CONFIG_PATH=/app/config/auto_config.json CACHE_PATH=/app/cache \
    LOG_PATH=/app/logs ANIMEMAN_WORK_PATH=/app/work TMPDIR=/app/work \
    ANIMEMAN_HOST=0.0.0.0 ANIMEMAN_PORT=8000 ANIMEMAN_THREADS=8
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg curl tzdata libsndfile1 \
    && rm -rf /var/lib/apt/lists/*
COPY --from=builder /opt/venv /opt/venv
WORKDIR /app
COPY core/ core/
COPY web/ web/
COPY templates/ templates/
COPY static/ static/
COPY main.py web_app.py server_runtime.py ./
ARG APP_UID=1000
ARG APP_GID=1000
RUN test "$APP_UID" -gt 0 && test "$APP_GID" -gt 0 \
    && (getent group "$APP_GID" >/dev/null || groupadd --gid "$APP_GID" animeman) \
    && useradd --uid "$APP_UID" --non-unique --gid "$APP_GID" --create-home animeman \
    && mkdir -p /app/config /app/cache /app/logs /app/work \
    && chown "$APP_UID:$APP_GID" /app/config /app/cache /app/logs /app/work
USER ${APP_UID}:${APP_GID}
EXPOSE 8000
STOPSIGNAL SIGTERM
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl --fail --silent http://127.0.0.1:8000/healthz || exit 1
CMD ["python", "web_app.py"]
