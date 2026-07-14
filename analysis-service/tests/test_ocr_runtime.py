from __future__ import annotations

import unittest

from PIL import Image

from analysis_service.ocr_runtime import (
    OcrBlock,
    build_text_result,
    correct_mixed_script_token,
    score_ocr_blocks,
    selected_ocr_engines,
    should_run_ocr,
)
from analysis_service.settings import load_settings


class OcrRuntimeTests(unittest.TestCase):
    def test_selected_ocr_engines_supports_both(self) -> None:
        settings = load_settings()
        object.__setattr__(settings, "ocr_engine", "both")
        self.assertEqual(selected_ocr_engines(settings, "fast"), ["easyocr", "paddle"])

    def test_mixed_script_correction_skips_code_like_token(self) -> None:
        corrected, trace = correct_mixed_script_token("main.cpp")
        self.assertEqual(corrected, "main.cpp")
        self.assertIsNone(trace)

    def test_scoring_does_not_accept_length_only_garbage(self) -> None:
        score, reason, *_ = score_ocr_blocks(
            [
                OcrBlock(rawText="AAAAAААААAAAA", displayText="AAAAAААААAAAA", searchText="aaaaaааааaaaaa"),
                OcrBlock(rawText="OOOOOОООООOOOO", displayText="OOOOOОООООOOOO", searchText="oooooоооооoooo"),
            ]
        )
        self.assertEqual(score, 0.0)
        self.assertIsNotNone(reason)

    def test_chat_result_preserves_block_boundaries(self) -> None:
        result = build_text_result(
            [
                OcrBlock(rawText="FIRST MESSAGE", displayText="FIRST MESSAGE", searchText="first message", bbox=[0, 0, 100, 20]),
                OcrBlock(rawText="SECOND MESSAGE", displayText="SECOND MESSAGE", searchText="second message", bbox=[0, 40, 100, 60]),
            ],
            "chat_screenshot",
        )
        self.assertEqual(result.displayText, "FIRST MESSAGE\n\nSECOND MESSAGE")

    def test_auto_policy_runs_on_natural_photo_with_text_cues(self) -> None:
        image = Image.new("RGB", (1200, 800), "white")
        for x in range(100, 1100, 20):
            for y in range(100, 300, 6):
                image.putpixel((x, y), (0, 0, 0))
        self.assertTrue(should_run_ocr("natural_photo", "auto", image))


if __name__ == "__main__":
    unittest.main()
