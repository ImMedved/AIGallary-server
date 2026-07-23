from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from analysis_service.cache import ResultCache


class ResultCacheTests(unittest.TestCase):
    def test_persistent_cache_survives_new_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cache_dir = Path(tmp)
            first = ResultCache(1024 * 1024, cache_dir)
            first.put("abc", {"value": "cached"})

            second = ResultCache(1024 * 1024, cache_dir)
            self.assertEqual(second.get("abc"), {"value": "cached"})
            self.assertEqual(second.stats().l2Hits, 1)
            self.assertEqual(second.get_with_status("abc").status, "L1_HIT")

    def test_cache_lookup_reports_miss(self) -> None:
        cache = ResultCache(1024)
        lookup = cache.get_with_status("missing")
        self.assertEqual(lookup.status, "MISS")
        self.assertIsNone(lookup.value)

    def test_duplicate_wait_counter_is_recorded(self) -> None:
        cache = ResultCache(1024)
        cache.record_duplicate_wait()
        self.assertEqual(cache.stats().duplicateWaits, 1)


if __name__ == "__main__":
    unittest.main()
