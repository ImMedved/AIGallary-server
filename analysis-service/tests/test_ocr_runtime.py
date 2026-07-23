from __future__ import annotations

import unittest

from PIL import Image

from analysis_service.ocr_runtime import (
    OcrBlock,
    build_text_result,
    correct_mixed_script_token,
    derive_ocr_image_kind,
    score_ocr_blocks,
    selected_ocr_engines,
    should_run_ocr,
)
from analysis_service.schemas import AnalysisDebugPayload
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
        self.assertEqual(result.displayText, "first message\n\nsecond message")

    def test_text_result_normalizes_display_text_to_lowercase(self) -> None:
        result = build_text_result(
            [
                OcrBlock(rawText="Mixed OCR Text", displayText="Mixed OCR Text", searchText="mixed ocr text"),
            ],
            "document",
        )
        self.assertEqual(result.displayText, "mixed ocr text")
        self.assertEqual(result.searchText, "mixed ocr text")
        self.assertEqual(result.blocks[0].text, "mixed ocr text")

    def test_auto_policy_runs_on_natural_photo_with_text_cues(self) -> None:
        image = Image.new("RGB", (1200, 800), "white")
        for x in range(100, 1100, 20):
            for y in range(100, 300, 6):
                image.putpixel((x, y), (0, 0, 0))
        self.assertTrue(should_run_ocr("natural_photo", "auto", image))

    def test_derive_ocr_route_promotes_text_screenshot(self) -> None:
        image = Image.new("RGB", (1280, 720), "white")
        for y in range(80, 620, 40):
            for x in range(80, 1120):
                image.putpixel((x, y), (0, 0, 0))
        debug = AnalysisDebugPayload(
            checksum="abc",
            filename="screen.png",
            imageWidth=1280,
            imageHeight=720,
            provider="local_ml",
            mode="quality",
            imageKind="natural_photo",
            imageSubtypes={"web_screenshot": 0.18, "photo_with_text": 0.20},
        )

        self.assertEqual(derive_ocr_image_kind(image, debug), "screenshot")


if __name__ == "__main__":
    unittest.main()
