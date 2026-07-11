from __future__ import annotations

import time


def now_ms() -> int:
    return int(time.perf_counter() * 1000)


def elapsed_ms(start_ms: int) -> int:
    return max(0, now_ms() - start_ms)


def preview_text(value: str | None, limit: int = 160) -> str | None:
    if value is None:
        return None
    value = value.replace("\n", " ").strip()
    if len(value) <= limit:
        return value
    return value[:limit] + "..."
