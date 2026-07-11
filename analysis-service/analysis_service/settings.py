from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

AnalysisMode = Literal["fast", "quality", "best"]
OcrPolicy = Literal["auto", "always", "skip"]
ExecutorKind = Literal["process", "thread", "inline"]
LogMode = Literal["debug", "production"]
RamProfile = Literal["test", "production", "custom"]


def bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def int_env(name: str, default: int, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def float_env(name: str, default: float, minimum: float | None = None, maximum: float | None = None) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def str_list_env(name: str, default: str) -> list[str]:
    raw = os.getenv(name, default)
    return [item.strip() for item in raw.split(",") if item.strip()]


def cpu_count() -> int:
    return max(1, os.cpu_count() or 1)


def resolve_ram_profile() -> RamProfile:
    raw = os.getenv("ANALYSIS_RAM_PROFILE", "test").strip().lower()
    if raw in {"test", "production", "custom"}:
        return raw  # type: ignore[return-value]
    return "test"


def default_memory_gb(profile: RamProfile) -> int:
    if profile == "production":
        return 20
    if profile == "test":
        return 5
    return 5


def default_workers(profile: RamProfile, memory_gb: int) -> int:
    if profile == "test" or memory_gb <= 6:
        return 1
    # CPU-only OCR/YOLO is heavy and each process keeps its own model cache.
    # Keep this conservative; raise ANALYSIS_WORKERS explicitly after measuring RAM.
    return min(3, max(1, cpu_count() // 3))


def default_intraop_threads(workers: int) -> int:
    return max(1, min(4, cpu_count() // max(1, workers)))


def default_cache_mb(profile: RamProfile, memory_gb: int) -> int:
    if profile == "production":
        return min(4096, max(1024, memory_gb * 128))
    return min(768, max(256, memory_gb * 96))


@dataclass(frozen=True)
class Settings:
    provider: str
    mode: AnalysisMode
    log_mode: LogMode
    executor: ExecutorKind
    ram_profile: RamProfile
    memory_limit_gb: int
    workers: int
    intraop_threads: int
    max_pending_requests: int
    result_cache_mb: int
    save_debug: bool
    include_debug_by_default: bool
    debug_dir: Path
    preload_on_startup: bool
    warmup_timeout_seconds: float

    enable_yolo: bool
    yolo_model: str
    yolo_confidence: float
    yolo_image_size: int
    yolo_run_on_text_images: bool
    yolo_world_classes: list[str]

    ocr_engine: str
    ocr_languages: list[str]
    paddle_ocr_lang: str
    ocr_policy: OcrPolicy
    ocr_max_side: int
    ocr_block_min_confidence: float
    easyocr_gpu: bool

    enable_clip: bool
    clip_model: str
    clip_pretrained: str
    clip_min_confidence: float
    clip_top_k: int
    clip_tags: list[str]

    enable_vlm: bool
    vlm_model: str
    ollama_url: str
    vlm_timeout_seconds: float


def load_settings() -> Settings:
    profile = resolve_ram_profile()
    memory_gb = int_env("ANALYSIS_MEMORY_LIMIT_GB", default_memory_gb(profile), minimum=1, maximum=256)
    workers = int_env("ANALYSIS_WORKERS", default_workers(profile, memory_gb), minimum=1, maximum=max(1, cpu_count()))
    intraop = int_env("ANALYSIS_INTRAOP_THREADS", default_intraop_threads(workers), minimum=1, maximum=max(1, cpu_count()))

    raw_mode = os.getenv("ANALYSIS_MODE", "quality").strip().lower()
    mode: AnalysisMode = raw_mode if raw_mode in {"fast", "quality", "best"} else "quality"  # type: ignore[assignment]

    raw_log = os.getenv("ANALYSIS_LOG_MODE", "production").strip().lower()
    log_mode: LogMode = raw_log if raw_log in {"debug", "production"} else "production"  # type: ignore[assignment]

    raw_executor = os.getenv("ANALYSIS_EXECUTOR", "process").strip().lower()
    executor: ExecutorKind = raw_executor if raw_executor in {"process", "thread", "inline"} else "process"  # type: ignore[assignment]

    raw_policy = os.getenv("OCR_POLICY", "auto").strip().lower()
    ocr_policy: OcrPolicy = raw_policy if raw_policy in {"auto", "always", "skip"} else "auto"  # type: ignore[assignment]

    max_pending_default = max(2, workers * 2)

    return Settings(
        provider=os.getenv("ANALYSIS_PROVIDER", "local_ml").strip().lower(),
        mode=mode,
        log_mode=log_mode,
        executor=executor,
        ram_profile=profile,
        memory_limit_gb=memory_gb,
        workers=workers,
        intraop_threads=intraop,
        max_pending_requests=int_env("ANALYSIS_MAX_PENDING_REQUESTS", max_pending_default, minimum=1, maximum=512),
        result_cache_mb=int_env("ANALYSIS_RESULT_CACHE_MB", default_cache_mb(profile, memory_gb), minimum=0, maximum=memory_gb * 1024),
        save_debug=bool_env("ANALYSIS_SAVE_DEBUG", True),
        include_debug_by_default=bool_env("ANALYSIS_INCLUDE_DEBUG_IN_RESPONSE", False),
        debug_dir=Path(os.getenv("ANALYSIS_DEBUG_DIR", "/tmp/smart-gallery-analysis-debug")),
        preload_on_startup=bool_env("ANALYSIS_PRELOAD_ON_STARTUP", True),
        warmup_timeout_seconds=float_env("ANALYSIS_WARMUP_TIMEOUT_SECONDS", 180.0, minimum=1.0, maximum=3600.0),
        enable_yolo=bool_env("ENABLE_YOLO", True),
        yolo_model=os.getenv("YOLO_MODEL", "yolov8s.pt"),
        yolo_confidence=float_env("YOLO_CONFIDENCE", 0.22, minimum=0.05, maximum=0.95),
        yolo_image_size=int_env("YOLO_IMAGE_SIZE", 768, minimum=320, maximum=1600),
        yolo_run_on_text_images=bool_env("YOLO_RUN_ON_TEXT_IMAGES", False),
        yolo_world_classes=str_list_env("YOLO_WORLD_CLASSES", ""),
        ocr_engine=os.getenv("OCR_ENGINE", "auto").strip().lower(),
        ocr_languages=[item.lower() for item in str_list_env("OCR_LANGUAGES", "ru,en")],
        paddle_ocr_lang=os.getenv("PADDLE_OCR_LANG", "ru").strip().lower(),
        ocr_policy=ocr_policy,
        ocr_max_side=int_env("OCR_MAX_SIDE", 2200, minimum=640, maximum=4096),
        ocr_block_min_confidence=float_env("OCR_BLOCK_MIN_CONFIDENCE", 0.42, minimum=0.0, maximum=1.0),
        easyocr_gpu=bool_env("EASYOCR_GPU", False),
        enable_clip=bool_env("ENABLE_CLIP", True),
        clip_model=os.getenv("CLIP_MODEL", "ViT-B-32"),
        clip_pretrained=os.getenv("CLIP_PRETRAINED", "openai"),
        clip_min_confidence=float_env("CLIP_MIN_CONFIDENCE", 0.58, minimum=0.0, maximum=1.0),
        clip_top_k=int_env("CLIP_TOP_K", 10, minimum=1, maximum=40),
        clip_tags=str_list_env("CLIP_TAGS", ""),
        enable_vlm=bool_env("ENABLE_VLM", False),
        vlm_model=os.getenv("VLM_MODEL", "llava:7b"),
        ollama_url=os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/"),
        vlm_timeout_seconds=float_env("VLM_TIMEOUT_SECONDS", 45.0, minimum=1.0, maximum=600.0),
    )


def resolve_mode(value: str | None, settings: Settings) -> AnalysisMode:
    raw = (value or settings.mode).strip().lower()
    return raw if raw in {"fast", "quality", "best"} else settings.mode  # type: ignore[return-value]


def resolve_ocr_policy(value: str | None, settings: Settings) -> OcrPolicy:
    raw = (value or settings.ocr_policy).strip().lower()
    return raw if raw in {"auto", "always", "skip"} else settings.ocr_policy  # type: ignore[return-value]
