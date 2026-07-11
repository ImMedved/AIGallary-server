from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any


@dataclass
class CacheStats:
    enabled: bool
    maxBytes: int
    currentBytes: int
    items: int
    hits: int
    misses: int
    evictions: int


class ResultCache:
    def __init__(self, max_bytes: int) -> None:
        self.max_bytes = max(0, max_bytes)
        self.current_bytes = 0
        self.items: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()
        self.lock = threading.Lock()
        self.hits = 0
        self.misses = 0
        self.evictions = 0

    @property
    def enabled(self) -> bool:
        return self.max_bytes > 0

    def _estimate_size(self, value: dict[str, Any]) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except Exception:
            return 4096

    def get(self, key: str) -> dict[str, Any] | None:
        if not self.enabled:
            return None
        with self.lock:
            item = self.items.get(key)
            if item is None:
                self.misses += 1
                return None
            size, value = item
            self.items.move_to_end(key)
            self.hits += 1
            return json.loads(json.dumps(value))

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        size = self._estimate_size(value)
        if size > self.max_bytes:
            return
        with self.lock:
            previous = self.items.pop(key, None)
            if previous is not None:
                self.current_bytes -= previous[0]
            self.items[key] = (size, json.loads(json.dumps(value)))
            self.current_bytes += size
            while self.current_bytes > self.max_bytes and self.items:
                _, (old_size, _) = self.items.popitem(last=False)
                self.current_bytes -= old_size
                self.evictions += 1

    def stats(self) -> CacheStats:
        with self.lock:
            return CacheStats(
                enabled=self.enabled,
                maxBytes=self.max_bytes,
                currentBytes=self.current_bytes,
                items=len(self.items),
                hits=self.hits,
                misses=self.misses,
                evictions=self.evictions,
            )
