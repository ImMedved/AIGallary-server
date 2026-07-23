from __future__ import annotations

import unittest

from analysis_service.tags import TagCandidate, deduplicate_tag_candidates, merge_evidence_candidates


class TagMergerTests(unittest.TestCase):
    def test_rejects_clip_receipt_without_document_or_text_evidence(self) -> None:
        merged, warnings = merge_evidence_candidates(
            [TagCandidate(value="receipt", confidence=0.72, source="CLIP", reason="semantic match")],
            raw_counts={},
            recognized_text=None,
            image_kind="natural_photo",
            subtype_distribution={"natural_photo": 0.62, "receipt": 0.04},
        )

        self.assertEqual(merged, [])
        self.assertTrue(any("receipt" in item for item in warnings))

    def test_keeps_receipt_with_payment_text_evidence(self) -> None:
        merged, warnings = merge_evidence_candidates(
            [TagCandidate(value="receipt", confidence=0.72, source="CLIP", reason="semantic match")],
            raw_counts={},
            recognized_text="total 12.50 eur",
            image_kind="document",
            subtype_distribution={"document": 0.12, "receipt": 0.06},
        )

        self.assertEqual(warnings, [])
        self.assertEqual(merged[0].value, "receipt")
        self.assertTrue(merged[0].validated)

    def test_final_tags_include_evidence_metadata(self) -> None:
        tags = deduplicate_tag_candidates(
            [TagCandidate(value="person", confidence=0.88, source="YOLO", reason="object detector")],
            top_tags=3,
        )

        self.assertEqual(tags[0].value, "people")
        self.assertEqual(tags[0].category, "people")
        self.assertEqual(tags[0].modelName, "ultralytics-yolo")
        self.assertEqual(tags[0].modelVersion, "tag-merger-v1")


if __name__ == "__main__":
    unittest.main()
