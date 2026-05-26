# syntax=docker/dockerfile:1

FROM node:22-alpine AS frontend-build

WORKDIR /app
COPY package.json package-lock.json vite.visualization.config.js ./
COPY frontend ./frontend
RUN npm ci && npm run build

ARG RUNTIME_IMAGE=python:3.11-slim
FROM ${RUNTIME_IMAGE} AS runtime

ARG INSTALL_SYSTEM_PYTHON=false
ARG PADDLE_VARIANT=cpu
ARG FG_DEVICE=cpu

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FG_DATA_DIR=/app/data \
    FG_DEVICE=${FG_DEVICE} \
    FG_ENABLE_PADDLE=true

WORKDIR /app

RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        fonts-dejavu-core \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        $(if [ "$INSTALL_SYSTEM_PYTHON" = "true" ]; then echo "python3 python3-pip python3-venv"; fi); \
    if ! command -v python >/dev/null 2>&1; then ln -s /usr/bin/python3 /usr/local/bin/python; fi; \
    if ! command -v pip >/dev/null 2>&1; then ln -s /usr/bin/pip3 /usr/local/bin/pip; fi; \
    rm -rf /var/lib/apt/lists/*

COPY requirements-common.txt requirements.txt requirements-gpu-cu118.txt ./
RUN set -eux; \
    python -m pip install --upgrade pip; \
    case "$PADDLE_VARIANT" in \
        cpu) python -m pip install -r requirements.txt ;; \
        cu118|cuda|gpu) python -m pip install -r requirements-gpu-cu118.txt ;; \
        *) echo "Unsupported PADDLE_VARIANT=$PADDLE_VARIANT. Use 'cpu', 'cu118', 'cuda', or 'gpu'." >&2; exit 64 ;; \
    esac

COPY backend ./backend
COPY frontend ./frontend
COPY main.py ./main.py
COPY --from=frontend-build /app/frontend/assets/visualization-react.js ./frontend/assets/visualization-react.js
COPY --from=frontend-build /app/frontend/assets/visualization-react.css ./frontend/assets/visualization-react.css

RUN mkdir -p /app/data/input /app/data/processed /app/data/results /app/data/models /app/data/sources

EXPOSE 8000
VOLUME ["/app/data"]

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=5).read()" || exit 1

CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
