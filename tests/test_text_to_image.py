from pathlib import Path
import tempfile
import unittest

from PIL import Image, ImageDraw

from util.text_to_image import (
    IMAGE_HEIGHT,
    IMAGE_WIDTH,
    _fit_text,
    _parse_story_card,
    text_to_image,
)


EXECUTIVE_ORDER_COPY = """Executive Order 14420 signed on 2026-08-10

Delivering Gold Standard Childhood Vaccine Recommendations for Americans

Published in the Federal Register on 2026-08-14

Source: official Federal Register text

Summary:

Directs the Department of Health and Human Services to review childhood vaccine recommendations and publish alternatives."""


class CivicBriefCardTests(unittest.TestCase):
    def test_extracts_visual_hierarchy_from_executive_order_copy(self) -> None:
        card = _parse_story_card(EXECUTIVE_ORDER_COPY)

        self.assertEqual(card.category, "EXECUTIVE ORDER")
        self.assertEqual(card.identifier, "Executive Order 14420")
        self.assertEqual(card.event, "signed on 2026-08-10")
        self.assertEqual(card.source, "official Federal Register text")
        self.assertTrue(card.summary.startswith("Directs the Department"))

    def test_extracts_congressional_identifier_and_event(self) -> None:
        card = _parse_story_card(
            """H.R. 42 Passed House on 2026-08-10

An Act to Improve Example Programs

118, Sponsored by Example Sponsor (I), Introduced on 2026-01-03

Source: official CRS summary

Summary:

Creates an example program."""
        )

        self.assertEqual(card.category, "CONGRESSIONAL UPDATE")
        self.assertEqual(card.identifier, "H.R. 42")
        self.assertEqual(card.event, "Passed House on 2026-08-10")

    def test_renders_a_portrait_card(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            image_path = Path(temporary_directory) / "brief.png"
            text_to_image(EXECUTIVE_ORDER_COPY, str(image_path))

            with Image.open(image_path) as image:
                self.assertEqual(image.size, (IMAGE_WIDTH, IMAGE_HEIGHT))
                self.assertEqual(image.mode, "RGB")
                self.assertNotEqual(image.getpixel((0, 0)), image.getpixel((0, IMAGE_HEIGHT - 1)))

    def test_long_latest_action_wraps_instead_of_being_cut_to_one_line(self) -> None:
        image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT))
        draw = ImageDraw.Draw(image)
        action = (
            "Referred to the House Committee on Energy and Commerce, and then "
            "ordered to be reported with an amendment"
        )

        font, lines, _, _ = _fit_text(
            draw, action, IMAGE_WIDTH - 180, 110, range(30, 19, -1), 0.16
        )

        self.assertGreater(len(lines), 1)
        self.assertTrue(
            all(draw.textlength(line, font=font) <= IMAGE_WIDTH - 180 for line in lines)
        )


if __name__ == "__main__":
    unittest.main()
