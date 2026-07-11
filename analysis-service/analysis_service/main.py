from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile

from .cache import ResultCache
from .logging_config import configure_logging
from .runtime import elapsed_ms, now_ms
from .schemas import AnalyzeResponse
from .settings import load_settings, resolve_mode, resolve_ocr_policy
from .worker_pool import AnalysisExecutor

settings = load_settings()
configure_logging(settings)
logger = logging.getLogger("smart_gallery_analysis")
job_logger = logging.getLogger("smart_gallery_analysis.jobs")

result_cache = ResultCache(settings.result_cache_mb * 1024 * 1024)
analysis_executor = AnalysisExecutor(settings)


def response_from_dict(payload: dict[str, Any]) -> AnalyzeResponse:
    return AnalyzeResponse.model_validate(payload)


def cache_key(checksum: str, top_tags: int, enhance: bool, mode: str, ocr_policy: str, include_debug: bool) -> str:
    # include_debug changes response shape, therefore it is part of the key.
    raw = f"v3|{checksum}|{top_tags}|{enhance}|{mode}|{ocr_policy}|{include_debug}|{settings.provider}|{settings.enable_yolo}|{settings.enable_clip}|{settings.ocr_engine}|{settings.ocr_languages}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


@asynccontextmanager
async def lifespan(_: FastAPI):
    analysis_executor.start()
    if settings.preload_on_startup:
        try:
            warmup_result = await analysis_executor.warmup()
            job_logger.info("Analysis warmup completed result=%s", warmup_result)
        except Exception as exception:
            job_logger.exception("Analysis warmup failed: %s", exception)
    yield
    await analysis_executor.stop()


app = FastAPI(title="smart-gallery-analysis", version="3.0.0", lifespan=lifespan)


@app.middleware("http")
async def api_request_logging_middleware(request: Request, call_next):
    path = request.url.path
    if path == "/health":
        return await call_next(request)

    started_at = now_ms()
    if settings.log_mode == "debug":
        logger.debug("API request started method=%s path=%s", request.method, path)
    try:
        response = await call_next(request)
        if settings.log_mode == "debug":
            logger.debug("API request completed method=%s path=%s status=%s durationMs=%s", request.method, path, response.status_code, elapsed_ms(started_at))
        return response
    except Exception as exception:
        logger.exception("API request failed method=%s path=%s durationMs=%s error=%s", request.method, path, elapsed_ms(started_at), exception)
        raise


@app.get("/health")
def health() -> dict[str, Any]:
    # This endpoint intentionally does not touch ML models and must stay responsive even when analysis workers are busy.
    return {
        "status": "ok",
        "version": "3.0.0",
        "provider": settings.provider,
        "mode": settings.mode,
        "executor": settings.executor,
        "workers": settings.workers,
        "intraopThreads": settings.intraop_threads,
        "ramProfile": settings.ram_profile,
        "memoryLimitGb": settings.memory_limit_gb,
        "resultCache": result_cache.stats().__dict__,
        "yoloEnabled": settings.enable_yolo,
        "yoloModel": settings.yolo_model if settings.enable_yolo else None,
        "ocrEngine": settings.ocr_engine,
        "ocrLanguages": settings.ocr_languages,
        "clipEnabled": settings.enable_clip,
        "clipModel": settings.clip_model if settings.enable_clip else None,
        "vlmEnabled": settings.enable_vlm,
        "debugSaveEnabled": settings.save_debug,
        "debugDir": str(settings.debug_dir),
    }


@app.get("/ready")
def ready() -> dict[str, Any]:
    return {"status": "ready", "executorStarted": analysis_executor.started}


@app.post("/warmup")
async def warmup() -> dict[str, Any]:
    started = now_ms()
    result = await analysis_executor.warmup()
    result["durationMs"] = elapsed_ms(started)
    return result


async def analyze_bytes(
    content: bytes,
    filename: str | None,
    content_type: str | None,
    top_tags: int,
    include_debug: bool,
    enhance: bool,
    mode: str | None,
    ocr_policy: str | None,
) -> AnalyzeResponse:
    resolved_mode = resolve_mode(mode, settings)
    resolved_policy = resolve_ocr_policy(ocr_policy, settings)
    checksum = hashlib.sha256(content).hexdigest()
    key = cache_key(checksum, top_tags, enhance, resolved_mode, resolved_policy, include_debug or settings.include_debug_by_default)

    cached = result_cache.get(key)
    if cached is not None:
        job_logger.info("Analysis job cache hit checksum=%s filename='%s'", checksum[:12], filename)
        return response_from_dict(cached)

    payload = {
        "content": content,
        "filename": filename,
        "content_type": content_type,
        "top_tags": max(1, min(top_tags, 30)),
        "include_debug": include_debug,
        "enhance": enhance,
        "mode": resolved_mode,
        "ocr_policy": resolved_policy,
    }

    try:
        response_payload = await analysis_executor.analyze(payload)
    except RuntimeError as exception:
        raise HTTPException(status_code=503, detail=f"Analysis executor unavailable: {exception}") from exception

    result_cache.put(key, response_payload)
    return response_from_dict(response_payload)


@app.post("/analyze", response_model=AnalyzeResponse, response_model_exclude_none=True)
async def analyze(
    file: UploadFile = File(...),
    topTags: int = Form(10),
    includeDebug: bool = Form(False),
    enhance: bool = Form(False),
    mode: str | None = Form(None),
    ocrPolicy: str | None = Form(None),
) -> AnalyzeResponse:
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file")
    return await analyze_bytes(content, file.filename, file.content_type, topTags, includeDebug, enhance, mode, ocrPolicy)


@app.post("/analyze-batch", response_model=list[AnalyzeResponse], response_model_exclude_none=True)
async def analyze_batch(
    files: list[UploadFile] = File(...),
    topTags: int = Form(10),
    includeDebug: bool = Form(False),
    enhance: bool = Form(False),
    mode: str | None = Form(None),
    ocrPolicy: str | None = Form(None),
) -> list[AnalyzeResponse]:
    max_files = max(1, min(500, settings.max_pending_requests * 4))
    if len(files) > max_files:
        raise HTTPException(status_code=413, detail=f"Too many files in one batch. Max: {max_files}")

    # Keep response order identical to upload order. The server queue is already sequential now,
    # but this endpoint is ready for future batch requests.
    responses: list[AnalyzeResponse] = []
    for file in files:
        content = await file.read()
        if not content:
            continue
        responses.append(await analyze_bytes(content, file.filename, file.content_type, topTags, includeDebug, enhance, mode, ocrPolicy))
    return responses
