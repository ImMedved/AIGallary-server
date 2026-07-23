from __future__ import annotations

import io
import unittest

from PIL import Image

from analysis_service.analyzer import PIPELINE_COMPLETED, analyze_content
from analysis_service.settings import load_settings


class PipelineStatusTests(unittest.TestCase):
    def test_mock_analysis_returns_completed_pipeline_status(self) -> None:
        image = Image.new("RGB", (32, 32), "white")
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")

        settings = load_settings()
        object.__setattr__(settings, "provider", "mock")
        object.__setattr__(settings, "save_debug", False)
        response = analyze_content(
            content=buffer.getvalue(),
            filename="mock.png",
            content_type="image/png",
            top_tags=5,
            include_debug=True,
            enhance=False,
            mode=settings.mode,
            ocr_policy=settings.ocr_policy,
            settings=settings,
        )

        self.assertEqual(response.pipelineStatus, PIPELINE_COMPLETED)
        self.assertEqual(response.debug.pipelineStatus, PIPELINE_COMPLETED)


if __name__ == "__main__":
    unittest.main()
