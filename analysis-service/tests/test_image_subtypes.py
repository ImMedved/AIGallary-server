from __future__ import annotations

import unittest

from PIL import Image, ImageDraw

from analysis_service.image_utils import classify_image_route, image_subtype_distribution


class ImageSubtypeTests(unittest.TestCase):
    def test_subtype_distribution_sums_to_one(self) -> None:
        image = Image.new("RGB", (900, 1600), "white")
        draw = ImageDraw.Draw(image)
        for y in range(80, 1200, 70):
            draw.rectangle((60, y, 820, y + 18), fill="black")

        distribution = image_subtype_distribution(image)

        self.assertAlmostEqual(sum(distribution.values()), 1.0, places=2)
        self.assertIn(next(iter(distribution)), distribution)
        self.assertIn(classify_image_route(distribution), {"specialized", "hybrid", "generic"})


if __name__ == "__main__":
    unittest.main()
