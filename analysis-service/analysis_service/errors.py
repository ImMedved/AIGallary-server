from __future__ import annotations


class AnalysisServiceError(RuntimeError):
    code = "ANALYSIS_ERROR"
    component = "analysis"
    retryable = False

    def to_payload(self) -> dict[str, object]:
        return {
            "code": self.code,
            "message": str(self),
            "retryable": self.retryable,
            "component": self.component,
            "details": {},
        }


class QueueFullError(AnalysisServiceError):
    code = "ANALYSIS_QUEUE_FULL"
    component = "queue"
    retryable = True

    def __init__(self, retry_after_seconds: int) -> None:
        super().__init__(f"Fast analysis queue is full. Retry after {retry_after_seconds} seconds.")
        self.retry_after_seconds = retry_after_seconds


class AnalysisTimeoutError(AnalysisServiceError):
    code = "ANALYSIS_FAST_TIMEOUT"
    component = "execution"
    retryable = True

    def __init__(self, timeout_seconds: float) -> None:
        super().__init__(f"Fast analysis timed out after {timeout_seconds:.1f} seconds.")
        self.timeout_seconds = timeout_seconds


class ModelUnavailableError(AnalysisServiceError):
    code = "MODEL_UNAVAILABLE"
    component = "models"
    retryable = True


class WorkerPoolUnavailableError(AnalysisServiceError):
    code = "WORKER_POOL_UNAVAILABLE"
    component = "execution"
    retryable = True
