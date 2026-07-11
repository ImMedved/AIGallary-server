from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import os
from typing import Any

from .analyzer import analyze_content_from_payload
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

            load_yolo_model(settings.yolo_model, "|".join(settings.yolo_world_classes))
            loaded.append("yolo")
        except Exception as exception:
            errors.append(f"yolo: {exception}")

    if settings.enable_clip and settings.provider != "mock":
        try:
            from .vision import load_clip_model

            load_clip_model(settings.clip_model, settings.clip_pretrained)
            loaded.append("clip")
        except Exception as exception:
            errors.append(f"clip: {exception}")

    if settings.ocr_engine != "none" and settings.provider != "mock":
        try:
            from .ocr import load_easyocr_reader, load_paddle_ocr_model, selected_ocr_engines

            for engine in selected_ocr_engines(settings, settings.mode):
                if engine == "easyocr":
                    load_easyocr_reader(",".join(settings.ocr_languages), settings.easyocr_gpu)
                elif engine == "paddle":
                    load_paddle_ocr_model(settings.paddle_ocr_lang)
                loaded.append(engine)
                if settings.mode != "best":
                    break
        except Exception as exception:
            errors.append(f"ocr: {exception}")

    return {"loaded": loaded, "errors": errors, "pid": os.getpid()}


class AnalysisExecutor:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.executor: concurrent.futures.Executor | None = None
        self.semaphore = asyncio.Semaphore(settings.max_pending_requests)
        self.started = False

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

    async def analyze(self, payload: dict[str, Any]) -> dict[str, Any]:
        await self.semaphore.acquire()
        try:
            if self.settings.executor == "inline":
                return analyze_content_from_payload(payload)
            if self.executor is None:
                self.start()
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(self.executor, analyze_content_from_payload, payload)
        finally:
            self.semaphore.release()

    async def warmup(self) -> dict[str, Any]:
        if self.settings.executor == "inline":
            return worker_warmup(0)
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
        return {"status": "ok" if not errors else "partial", "workers": self.settings.workers, "results": results, "errors": errors}
