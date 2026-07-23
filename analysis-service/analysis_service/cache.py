from __future__ import annotations

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class CacheStats:
    enabled: bool
    maxBytes: int
    currentBytes: int
    items: int
    hits: int
    l2Hits: int
    misses: int
    evictions: int
    duplicateWaits: int


@dataclass
class CacheLookup:
    status: str
    value: dict[str, Any] | None = None


class ResultCache:
    def __init__(self, max_bytes: int, persistent_dir: Path | None = None) -> None:
        self.max_bytes = max(0, max_bytes)
        self.persistent_dir = persistent_dir
        self.current_bytes = 0
        self.items: OrderedDict[str, tuple[int, dict[str, Any]]] = OrderedDict()
        self.lock = threading.Lock()
        self.hits = 0
        self.l2_hits = 0
        self.misses = 0
        self.evictions = 0
        self.duplicate_waits = 0

    @property
    def enabled(self) -> bool:
        return self.max_bytes > 0

    def _estimate_size(self, value: dict[str, Any]) -> int:
        try:
            return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except Exception:
            return 4096

    def _persistent_path(self, key: str) -> Path | None:
        if self.persistent_dir is None or not self.enabled:
            return None
        return self.persistent_dir / f"{key}.json"

    def _remember_l1(self, key: str, value: dict[str, Any]) -> None:
        size = self._estimate_size(value)
        if size > self.max_bytes:
            return
        previous = self.items.pop(key, None)
        if previous is not None:
            self.current_bytes -= previous[0]
        self.items[key] = (size, json.loads(json.dumps(value)))
        self.current_bytes += size
        while self.current_bytes > self.max_bytes and self.items:
            _, (old_size, _) = self.items.popitem(last=False)
            self.current_bytes -= old_size
            self.evictions += 1

    def get_with_status(self, key: str) -> CacheLookup:
        if not self.enabled:
            return CacheLookup("DISABLED")
        with self.lock:
            item = self.items.get(key)
            if item is not None:
                _, value = item
                self.items.move_to_end(key)
                self.hits += 1
                return CacheLookup("L1_HIT", json.loads(json.dumps(value)))

        path = self._persistent_path(key)
        if path is not None and path.exists():
            try:
                value = json.loads(path.read_text(encoding="utf-8"))
            except Exception:
                value = None
            if isinstance(value, dict):
                with self.lock:
                    self.l2_hits += 1
                    self._remember_l1(key, value)
                return CacheLookup("L2_HIT", json.loads(json.dumps(value)))

        with self.lock:
            self.misses += 1
        return CacheLookup("MISS")

    def get(self, key: str) -> dict[str, Any] | None:
        return self.get_with_status(key).value

    def put(self, key: str, value: dict[str, Any]) -> None:
        if not self.enabled:
            return
        size = self._estimate_size(value)
        if size > self.max_bytes:
            return
        with self.lock:
            self._remember_l1(key, value)

        path = self._persistent_path(key)
        if path is None:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(".tmp")
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(path)
        except Exception:
            pass

    def record_duplicate_wait(self) -> None:
        with self.lock:
            self.duplicate_waits += 1

    def stats(self) -> CacheStats:
        with self.lock:
            return CacheStats(
                enabled=self.enabled,
                maxBytes=self.max_bytes,
                currentBytes=self.current_bytes,
                items=len(self.items),
                hits=self.hits,
                l2Hits=self.l2_hits,
                misses=self.misses,
                evictions=self.evictions,
                duplicateWaits=self.duplicate_waits,
            )
