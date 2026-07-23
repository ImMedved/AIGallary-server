from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass
from typing import Iterable


@dataclass
class StageMetric:
    count: int = 0
    total_seconds: float = 0.0


class AnalysisMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.jobs_total = 0
        self.jobs_failed_total = 0
        self.queue_rejected_total = 0
        self.worker_restart_total = 0
        self.ocr_rejected_blocks_total = 0
        self.tags_by_source_total: dict[str, int] = defaultdict(int)
        self.stage_metrics: dict[str, StageMetric] = defaultdict(StageMetric)

    def inc_jobs_total(self) -> None:
        with self._lock:
            self.jobs_total += 1

    def inc_jobs_failed_total(self) -> None:
        with self._lock:
            self.jobs_failed_total += 1

    def inc_queue_rejected_total(self) -> None:
        with self._lock:
            self.queue_rejected_total += 1

    def inc_worker_restart_total(self) -> None:
        with self._lock:
            self.worker_restart_total += 1

    def add_ocr_rejected_blocks(self, count: int) -> None:
        with self._lock:
            self.ocr_rejected_blocks_total += max(0, count)

    def observe_stage_ms(self, stage: str, milliseconds: int | float | None) -> None:
        if milliseconds is None:
            return
        with self._lock:
            metric = self.stage_metrics[stage]
            metric.count += 1
            metric.total_seconds += max(0.0, float(milliseconds) / 1000.0)

    def observe_tag_sources(self, sources: Iterable[str]) -> None:
        with self._lock:
            for source in sources:
                self.tags_by_source_total[source.lower()] += 1

    def render_prometheus(
        self,
        *,
        queue_depth: int,
        queue_capacity: int,
        queue_rejected_total: int,
        cache_hits: int,
        cache_l2_hits: int,
        duplicate_waits: int,
        model_statuses: list[dict[str, object]],
        memory_estimate_bytes: int,
    ) -> str:
        with self._lock:
            lines = [
                "# TYPE analysis_jobs_total counter",
                f"analysis_jobs_total {self.jobs_total}",
                "# TYPE analysis_jobs_failed_total counter",
                f"analysis_jobs_failed_total {self.jobs_failed_total}",
                "# TYPE analysis_queue_depth gauge",
                f"analysis_queue_depth {queue_depth}",
                "# TYPE analysis_queue_capacity gauge",
                f"analysis_queue_capacity {queue_capacity}",
                "# TYPE analysis_queue_rejected_total counter",
                f"analysis_queue_rejected_total {self.queue_rejected_total + queue_rejected_total}",
                "# TYPE analysis_cache_hit_total counter",
                f"analysis_cache_hit_total {cache_hits}",
                "# TYPE analysis_cache_l2_hit_total counter",
                f"analysis_cache_l2_hit_total {cache_l2_hits}",
                "# TYPE analysis_duplicate_wait_total counter",
                f"analysis_duplicate_wait_total {duplicate_waits}",
                "# TYPE analysis_worker_restart_total counter",
                f"analysis_worker_restart_total {self.worker_restart_total}",
                "# TYPE analysis_ocr_rejected_blocks_total counter",
                f"analysis_ocr_rejected_blocks_total {self.ocr_rejected_blocks_total}",
                "# TYPE analysis_memory_estimate_bytes gauge",
                f"analysis_memory_estimate_bytes {memory_estimate_bytes}",
            ]
            for stage, metric in sorted(self.stage_metrics.items()):
                lines.append(f'analysis_stage_duration_seconds_count{{stage="{stage}"}} {metric.count}')
                lines.append(f'analysis_stage_duration_seconds_sum{{stage="{stage}"}} {metric.total_seconds:.6f}')
            for source, count in sorted(self.tags_by_source_total.items()):
                lines.append(f'analysis_tags_by_source_total{{source="{source}"}} {count}')
            for status in model_statuses:
                name = str(status.get("name"))
                ready = 1 if status.get("ready") else 0
                lines.append(f'analysis_model_ready{{model="{name}"}} {ready}')
            return "\n".join(lines) + "\n"
