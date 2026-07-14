from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from analysis_service.models.registry import ModelRegistry
from analysis_service.settings import load_settings


class ModelRegistryTests(unittest.TestCase):
    def test_registry_reports_missing_models_not_ready(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings()
            model_root = Path(tmp)
            object.__setattr__(settings, "model_cache_dir", model_root)
            object.__setattr__(settings, "model_manifest_path", model_root / "manifest.lock.json")
            object.__setattr__(settings, "yolo_config_dir", model_root / "ultralytics")
            object.__setattr__(settings, "hf_home", model_root / "huggingface")
            object.__setattr__(settings, "hf_hub_cache", model_root / "huggingface" / "hub")
            object.__setattr__(settings, "torch_home", model_root / "torch")
            object.__setattr__(settings, "easyocr_module_path", model_root / "easyocr")
            object.__setattr__(settings, "paddle_home", model_root / "paddle")

            registry = ModelRegistry(settings)
            statuses = registry.collect_statuses(verify_checksum=False)
            self.assertTrue(statuses)
            self.assertTrue(any(not status.ready for status in statuses))

    def test_manifest_lock_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            settings = load_settings()
            model_root = Path(tmp)
            yolo_root = model_root / "ultralytics"
            yolo_root.mkdir(parents=True, exist_ok=True)
            (yolo_root / "weights.bin").write_bytes(b"abc123")

            object.__setattr__(settings, "enable_clip", False)
            object.__setattr__(settings, "ocr_engine", "none")
            object.__setattr__(settings, "model_cache_dir", model_root)
            object.__setattr__(settings, "model_manifest_path", model_root / "manifest.lock.json")
            object.__setattr__(settings, "yolo_config_dir", yolo_root)

            registry = ModelRegistry(settings)
            payload = registry.write_manifest_lock()
            written = json.loads(settings.model_manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(payload, written)
            self.assertEqual(written["models"][0]["name"], "yolo")


if __name__ == "__main__":
    unittest.main()
