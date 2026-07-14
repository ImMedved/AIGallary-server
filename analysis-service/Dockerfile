# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_CACHE_DIR=/root/.cache/pip \
    XDG_CACHE_HOME=/models/.cache \
    ANALYSIS_MODE=quality \
    ANALYSIS_PROVIDER=local_ml \
    ANALYSIS_EXECUTOR=process \
    ANALYSIS_RAM_PROFILE=test \
    ANALYSIS_MEMORY_LIMIT_GB=5 \
    ANALYSIS_WORKERS=1 \
    ANALYSIS_ENRICHMENT_WORKERS=1 \
    ANALYSIS_INTRAOP_THREADS=4 \
    ANALYSIS_MAX_PENDING_FAST_REQUESTS=2 \
    ANALYSIS_MAX_PENDING_ENRICHMENT_REQUESTS=1 \
    ANALYSIS_RESULT_CACHE_MB=512 \
    ANALYSIS_FAST_TIMEOUT_SECONDS=30 \
    ANALYSIS_QUEUE_RETRY_AFTER_SECONDS=15 \
    ANALYSIS_PRELOAD_ON_STARTUP=true \
    ANALYSIS_LOG_MODE=production \
    ANALYSIS_ALLOW_MODEL_DOWNLOAD=false \
    ENABLE_YOLO=true \
    YOLO_MODEL=yolov8s.pt \
    YOLO_RUN_ON_TEXT_IMAGES=false \
    ENABLE_CLIP=true \
    CLIP_RUN_ON_TEXT_IMAGES=false \
    OCR_ENGINE=easyocr \
    OCR_LANGUAGES=ru,en \
    OCR_POLICY=auto \
    HF_HUB_CACHE=/models/huggingface/hub \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch \
    TIKTOKEN_CACHE_DIR=/models/tiktoken \
    EASYOCR_MODULE_PATH=/models/easyocr \
    PADDLE_HOME=/models/paddle \
    YOLO_CONFIG_DIR=/models/ultralytics \
    TOKENIZERS_PARALLELISM=false

ARG INSTALL_ML=true

RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libglib2.0-0 \
    libgl1 \
    libgomp1 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip install --upgrade pip && \
    pip install -r requirements.txt

COPY requirements-ml.txt .
RUN --mount=type=cache,target=/root/.cache/pip \
    if [ "$INSTALL_ML" = "true" ]; then pip install -r requirements-ml.txt; fi

COPY app.py .
COPY analysis_service ./analysis_service

EXPOSE 8090

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--no-access-log"]
