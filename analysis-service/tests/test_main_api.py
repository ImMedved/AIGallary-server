from __future__ import annotations

import importlib
import os
import unittest

from fastapi.testclient import TestClient


class MainApiTests(unittest.TestCase):
    def test_health_and_metrics_endpoints(self) -> None:
        previous = os.environ.copy()
        try:
            os.environ["ENABLE_YOLO"] = "false"
            os.environ["ENABLE_CLIP"] = "false"
            os.environ["OCR_ENGINE"] = "none"
            os.environ["ANALYSIS_PRELOAD_ON_STARTUP"] = "false"
            os.environ["ANALYSIS_EXECUTOR"] = "inline"
            os.environ["ANALYSIS_MAX_PENDING_FAST_REQUESTS"] = "1"

            module = importlib.import_module("analysis_service.main")
            module = importlib.reload(module)
            with TestClient(module.app) as client:
                live = client.get("/health/live")
                ready = client.get("/health/ready")
                metrics = client.get("/metrics")
                models = client.get("/health/models")

                self.assertEqual(live.status_code, 200)
                self.assertEqual(ready.status_code, 200)
                self.assertEqual(models.status_code, 200)
                self.assertEqual(metrics.status_code, 200)
                self.assertIn("analysis_jobs_total", metrics.text)
        finally:
            os.environ.clear()
            os.environ.update(previous)


if __name__ == "__main__":
    unittest.main()
