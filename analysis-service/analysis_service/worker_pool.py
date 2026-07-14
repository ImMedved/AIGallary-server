from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
import threading
from typing import Any

from .analyzer import analyze_content_from_payload
from .errors import AnalysisTimeoutError, QueueFullError, WorkerPoolUnavailableError
from .metrics import AnalysisMetrics
from .models.registry import ModelRegistry
from .ocr_runtime import load_easyocr_reader, load_paddle_ocr_model, selected_ocr_engines
from .settings import Settings, load_settings

logger = logging.getLogger("smart_gallery_analysis.pool")


def configure_worker_process(intraop_threads: int) -> None:
    # Must be set before native libraries create their own thread pools.
    os.environ.setdefault("OMP_NUM_THREADS", str(intraop_threads))
    os.environ.setdefault("OPENBLAS_NUM_THREADS", str(intraop_threads))
    os.environ.setdefault("MKL_NUM_THREADS", str(intraop_threads))
    os.environ.setdefault("NUMEXPR_NUM_THREADS", str(intraop_threads))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    try:
        import torch

        torch.set_num_threads(intraop_threads)
        torch.set_num_interop_threads(max(1, min(2, intraop_threads)))
    except Exception:
        pass


def worker_initializer(intraop_threads: int) -> None:
    configure_worker_process(intraop_threads)


def worker_warmup(_: int) -> dict[str, Any]:
    settings = load_settings()
    configure_worker_process(settings.intraop_threads)
    loaded: list[str] = []
    errors: list[str] = []

    if settings.enable_yolo and settings.provider != "mock":
        try:
            from .vision import load_yolo_model

            load_yolo_model(settings)
            loaded.append("yolo")
        except Exception as exception:
            errors.append(f"yolo: {exception}")

    if settings.enable_clip and settings.provider != "mock":
        try:
            from .vision import load_clip_model

            load_clip_model(settings)
            loaded.append("clip")
        except Exception as exception:
            errors.append(f"clip: {exception}")

    if settings.ocr_engine != "none" and settings.provider != "mock":
        try:
            for engine in selected_ocr_engines(settings, settings.mode):
                if engine == "easyocr":
                    load_easyocr_reader(settings)
                elif engine == "paddle":
                    load_paddle_ocr_model(settings)
                loaded.append(engine)
                if settings.mode != "best":
                    break
        except Exception as exception:
            errors.append(f"ocr: {exception}")

    return {"loaded": loaded, "errors": errors, "pid": os.getpid()}


class PendingRequestLimiter:
    def __init__(self, capacity: int) -> None:
        self.capacity = max(1, capacity)
        self.current = 0
        self.rejected = 0
        self.peak = 0
        self._lock = threading.Lock()

    def try_acquire(self) -> bool:
        with self._lock:
            if self.current >= self.capacity:
                self.rejected += 1
                return False
            self.current += 1
            self.peak = max(self.peak, self.current)
            return True

    def release(self) -> None:
        with self._lock:
            self.current = max(0, self.current - 1)

    def snapshot(self) -> dict[str, int]:
        with self._lock:
            return {
                "capacity": self.capacity,
                "current": self.current,
                "rejected": self.rejected,
                "peak": self.peak,
            }


class AnalysisExecutor:
    def __init__(self, settings: Settings, metrics: AnalysisMetrics | None = None) -> None:
        self.settings = settings
        self.executor: concurrent.futures.Executor | None = None
        self.metrics = metrics
        self.fast_limiter = PendingRequestLimiter(settings.max_pending_fast_requests)
        self.enrichment_limiter = PendingRequestLimiter(settings.max_pending_enrichment_requests)
        self.started = False
        self.last_warmup: dict[str, Any] | None = None
        self.worker_restarts = 0
        self.registry = ModelRegistry(settings)

    def start(self) -> None:
        if self.started:
            return
        self.started = True
        if self.settings.executor == "inline":
            self.executor = None
            return
        if self.settings.executor == "thread":
            self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=self.settings.workers, thread_name_prefix="analysis")
            return
        self.executor = concurrent.futures.ProcessPoolExecutor(
            max_workers=self.settings.workers,
            initializer=worker_initializer,
            initargs=(self.settings.intraop_threads,),
        )
        logger.warning(
            "Analysis process pool started workers=%s intraopThreads=%s memoryLimitGb=%s profile=%s",
            self.settings.workers,
            self.settings.intraop_threads,
            self.settings.memory_limit_gb,
            self.settings.ram_profile,
        )

    async def stop(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.executor = None
        self.started = False

    def queue_snapshot(self) -> dict[str, Any]:
        return {
            "fast": self.fast_limiter.snapshot(),
            "enrichment": self.enrichment_limiter.snapshot(),
        }

    def ready(self) -> tuple[bool, dict[str, Any]]:
        model_statuses = [status.to_dict() for status in self.registry.collect_statuses(verify_checksum=False)]
        queue = self.queue_snapshot()["fast"]
        ready = self.started and self.registry.fast_models_ready() and queue["current"] < queue["capacity"]
        return ready, {
            "executorStarted": self.started,
            "queue": queue,
            "workerRestarts": self.worker_restarts,
            "models": model_statuses,
            "lastWarmup": self.last_warmup,
        }

    def _recreate_pool(self) -> None:
        if self.executor is not None:
            self.executor.shutdown(wait=False, cancel_futures=True)
        self.executor = None
        self.started = False
        self.worker_restarts += 1
        if self.metrics is not None:
            self.metrics.inc_worker_restart_total()
        self.start()

    async def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.fast_limiter.try_acquire():
            if self.metrics is not None:
                self.metrics.inc_queue_rejected_total()
            raise QueueFullError(self.settings.queue_retry_after_seconds)
        try:
            if self.settings.executor == "inline":
                try:
                    return analyze_content_from_payload(payload)
                finally:
                    self.fast_limiter.release()
            if self.executor is None:
                self.start()
            loop = asyncio.get_running_loop()
            future = loop.run_in_executor(self.executor, analyze_content_from_payload, payload)
            future.add_done_callback(lambda _: self.fast_limiter.release())
            try:
                return await asyncio.wait_for(asyncio.shield(future), timeout=self.settings.fast_timeout_seconds)
            except asyncio.TimeoutError as exception:
                raise AnalysisTimeoutError(self.settings.fast_timeout_seconds) from exception
            except concurrent.futures.process.BrokenProcessPool as exception:
                self._recreate_pool()
                raise WorkerPoolUnavailableError("Fast worker process crashed and was restarted.") from exception
        except QueueFullError:
            raise
        except AnalysisTimeoutError:
            raise
        except WorkerPoolUnavailableError:
            raise
        except RuntimeError as exception:
            self.fast_limiter.release()
            raise WorkerPoolUnavailableError(str(exception)) from exception
        except Exception:
            self.fast_limiter.release()
            raise

    async def warmup(self) -> dict[str, Any]:
        if self.settings.executor == "inline":
            self.last_warmup = worker_warmup(0)
            return self.last_warmup
        if self.executor is None:
            self.start()
        loop = asyncio.get_running_loop()
        tasks = [loop.run_in_executor(self.executor, worker_warmup, index) for index in range(self.settings.workers)]
        done, pending = await asyncio.wait(tasks, timeout=self.settings.warmup_timeout_seconds)
        for task in pending:
            task.cancel()
        results = []
        errors = []
        for task in done:
            try:
                results.append(task.result())
            except Exception as exception:
                errors.append(str(exception))
        self.last_warmup = {
            "status": "ok" if not errors else "partial",
            "workers": self.settings.workers,
            "results": results,
            "errors": errors,
        }
        if not errors:
            try:
                self.registry.write_manifest_lock()
            except Exception:
                logger.exception("Failed to write model manifest lock after warmup")
        return self.last_warmup
