# syntax=docker/dockerfile:1.7

FROM python:3.11-slim-bookworm

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_CACHE_DIR=/root/.cache/pip \
    ANALYSIS_MODE=quality \
    ANALYSIS_PROVIDER=local_ml \
    ANALYSIS_EXECUTOR=process \
    ANALYSIS_RAM_PROFILE=test \
    ANALYSIS_MEMORY_LIMIT_GB=5 \
    ANALYSIS_WORKERS=1 \
    ANALYSIS_INTRAOP_THREADS=4 \
    ANALYSIS_RESULT_CACHE_MB=512 \
    ANALYSIS_PRELOAD_ON_STARTUP=true \
    ANALYSIS_LOG_MODE=production \
    ENABLE_YOLO=true \
    YOLO_MODEL=yolov8s.pt \
    YOLO_RUN_ON_TEXT_IMAGES=false \
    ENABLE_CLIP=true \
    OCR_ENGINE=easyocr \
    OCR_LANGUAGES=ru,en \
    OCR_POLICY=auto \
    HF_HOME=/models/huggingface \
    TORCH_HOME=/models/torch \
    EASYOCR_MODULE_PATH=/models/easyocr \
    PADDLE_HOME=/models/paddle \
    TOKENIZERS_PARALLELISM=false

ARG INSTALL_ML=true

RUN apt-get update && apt-get install -y --no-install-recommends \
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