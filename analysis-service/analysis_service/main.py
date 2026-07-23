from __future__ import annotations

import hashlib
import logging
import asyncio
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile

from .cache import ResultCache
from .errors import AnalysisServiceError, AnalysisTimeoutError, QueueFullError, WorkerPoolUnavailableError
from .logging_config import configure_logging
from .metrics import AnalysisMetrics
from .models.registry import ModelRegistry
from .runtime import elapsed_ms, now_ms
from .schemas import AnalyzeResponse
from .settings import load_settings, resolve_mode, resolve_ocr_policy
from .worker_pool import AnalysisExecutor

settings = load_settings()
configure_logging(settings)
logger = logging.getLogger("smart_gallery_analysis")
job_logger = logging.getLogger("smart_gallery_analysis.jobs")
metrics = AnalysisMetrics()
model_registry = ModelRegistry(settings)

PIPELINE_VERSION = "3.7.0"

result_cache = ResultCache(settings.result_cache_mb * 1024 * 1024, settings.result_cache_dir)
analysis_executor = AnalysisExecutor(settings, metrics=metrics)
inflight_lock = asyncio.Lock()
inflight: dict[str, asyncio.Future] = {}


def response_from_dict(payload: dict[str, Any]) -> AnalyzeResponse:
    return AnalyzeResponse.model_validate(payload)


def model_versions_key() -> str:
    return "|".join(
        [
            f"provider={settings.provider}",
            f"yolo={settings.enable_yolo}:{settings.yolo_model}",
            f"clip={settings.enable_clip}:{settings.clip_model}:{settings.clip_pretrained}",
            f"ocr={settings.ocr_engine}:{','.join(settings.ocr_languages)}:{settings.paddle_ocr_lang}",
            "taxonomy=tag-merger-v1",
        ]
    )


def cache_key(checksum: str, top_tags: int, enhance: bool, mode: str, ocr_policy: str, include_debug: bool) -> str:
    # include_debug changes response shape, therefore it is part of the key.
    raw = f"{PIPELINE_VERSION}|{checksum}|{top_tags}|{enhance}|{mode}|{ocr_policy}|{include_debug}|{model_versions_key()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def cache_completed_result(key: str, future: asyncio.Future) -> None:
    try:
        payload = future.result()
    except Exception:
        return
    if isinstance(payload, dict):
        result_cache.put(key, payload)


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


app = FastAPI(title="smart-gallery-analysis", version=PIPELINE_VERSION, lifespan=lifespan)


@app.middleware("http")
async def api_request_logging_middleware(request: Request, call_next):
    path = request.url.path
    if path in {"/health", "/health/live"}:
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


@app.get("/health/live")
def health_live() -> dict[str, Any]:
    return {
        "status": "ok",
        "version": PIPELINE_VERSION,
        "provider": settings.provider,
        "mode": settings.mode,
        "executor": settings.executor,
        "workers": settings.workers,
        "intraopThreads": settings.intraop_threads,
        "ramProfile": settings.ram_profile,
        "memoryLimitGb": settings.memory_limit_gb,
        "queueConfiguredFast": settings.max_pending_fast_requests,
        "queueConfiguredEnrichment": settings.max_pending_enrichment_requests,
    }


@app.get("/health")
def health() -> dict[str, Any]:
    return health_live()


@app.get("/health/ready")
def health_ready(response: Response) -> dict[str, Any]:
    ready, details = analysis_executor.ready()
    if not ready:
        response.status_code = 503
    return {"status": "ready" if ready else "not_ready", **details}


@app.get("/ready")
def ready(response: Response) -> dict[str, Any]:
    return health_ready(response)


@app.get("/health/models")
def health_models() -> dict[str, Any]:
    statuses = [status.to_dict() for status in model_registry.collect_statuses(verify_checksum=True)]
    return {"models": statuses, "manifestPath": str(settings.model_manifest_path)}


@app.get("/metrics")
def metrics_endpoint() -> Response:
    queue = analysis_executor.queue_snapshot()["fast"]
    cache_stats = result_cache.stats()
    body = metrics.render_prometheus(
        queue_depth=queue["current"],
        queue_capacity=queue["capacity"],
        queue_rejected_total=queue["rejected"],
        cache_hits=cache_stats.hits,
        cache_l2_hits=cache_stats.l2Hits,
        duplicate_waits=cache_stats.duplicateWaits,
        model_statuses=[status.to_dict() for status in model_registry.collect_statuses(verify_checksum=False)],
        memory_estimate_bytes=settings.memory_limit_gb * 1024 * 1024 * 1024,
    )
    return Response(content=body, media_type="text/plain; version=0.0.4")


@app.post("/admin/warmup")
async def warmup() -> dict[str, Any]:
    started = now_ms()
    result = await analysis_executor.warmup()
    result["durationMs"] = elapsed_ms(started)
    return result


@app.post("/warmup")
async def warmup_compat() -> dict[str, Any]:
    return await warmup()


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

    cache_lookup = result_cache.get_with_status(key)
    if cache_lookup.value is not None:
        job_logger.info("Analysis job cache %s checksum=%s filename='%s'", cache_lookup.status, checksum[:12], filename)
        return response_from_dict(cache_lookup.value)
    job_logger.info("Analysis job cache %s checksum=%s filename='%s'", cache_lookup.status, checksum[:12], filename)

    try:
        async with inflight_lock:
            future = inflight.get(key)
            if future is None:
                future = await analysis_executor.submit(
                    {
                        "content": content,
                        "filename": filename,
                        "content_type": content_type,
                        "top_tags": max(1, min(top_tags, 30)),
                        "include_debug": include_debug,
                        "enhance": enhance,
                        "mode": resolved_mode,
                        "ocr_policy": resolved_policy,
                    }
                )
                inflight[key] = future

                def cleanup(done: asyncio.Future, cache_key_value: str = key) -> None:
                    if done.cancelled():
                        metrics.inc_jobs_failed_total()
                    elif done.exception() is not None:
                        metrics.inc_jobs_failed_total()
                    cache_completed_result(cache_key_value, done)
                    inflight.pop(cache_key_value, None)

                future.add_done_callback(cleanup)
            else:
                result_cache.record_duplicate_wait()
                job_logger.info("Analysis job joined in-flight request checksum=%s filename='%s'", checksum[:12], filename)

        response_payload = await asyncio.wait_for(asyncio.shield(future), timeout=settings.fast_timeout_seconds)
    except QueueFullError as exception:
        raise HTTPException(status_code=429, detail=exception.to_payload(), headers={"Retry-After": str(exception.retry_after_seconds)}) from exception
    except asyncio.TimeoutError as exception:
        raise HTTPException(status_code=504, detail=AnalysisTimeoutError(settings.fast_timeout_seconds).to_payload()) from exception
    except AnalysisTimeoutError as exception:
        raise HTTPException(status_code=504, detail=exception.to_payload()) from exception
    except (WorkerPoolUnavailableError, AnalysisServiceError) as exception:
        raise HTTPException(status_code=503, detail=exception.to_payload()) from exception
    except RuntimeError as exception:
        raise HTTPException(status_code=503, detail={"code": "ANALYSIS_EXECUTOR_UNAVAILABLE", "message": f"Analysis executor unavailable: {exception}", "retryable": True, "component": "execution", "details": {}}) from exception

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
    max_files = max(1, min(500, settings.max_pending_fast_requests * 4))
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
