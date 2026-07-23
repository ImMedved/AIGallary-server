from __future__ import annotations

import unittest

from analysis_service.schemas import AnalysisDebugPayload
from analysis_service.vision import calibrated_clip_confidence, clip_subtype_compatibility


class ClipScoringTests(unittest.TestCase):
    def test_calibrated_confidence_is_capped_below_one(self) -> None:
        confidence = calibrated_clip_confidence(0.95, 0.10, "cat")
        self.assertLess(confidence, 1.0)

    def test_receipt_tag_requires_document_subtype_evidence(self) -> None:
        debug = AnalysisDebugPayload(
            checksum="abc",
            provider="local_ml",
            mode="quality",
            imageKind="natural_photo",
            imageSubtypes={"natural_photo": 0.72, "receipt": 0.03},
            imageWidth=100,
            imageHeight=100,
        )

        compatibility, reason = clip_subtype_compatibility("receipt", debug)

        self.assertLess(compatibility, 1.0)
        self.assertIsNotNone(reason)


if __name__ == "__main__":
    unittest.main()
