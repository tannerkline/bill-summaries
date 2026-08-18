from datetime import date
import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import _fetch_documents, _write_debug_artifacts, clean_summary_for_post, main, parse_date


class CommandLineTests(unittest.TestCase):
    def test_parses_iso_date(self) -> None:
        self.assertEqual(parse_date("2026-08-14"), date(2026, 8, 14))

    def test_rejects_non_iso_date(self) -> None:
        with self.assertRaises(argparse.ArgumentTypeError):
            parse_date("08/14/2026")

    def test_summary_is_plain_text_and_removes_canned_intro(self) -> None:
        summary = clean_summary_for_post(
            "Here is a simple summary:\n\n### **Main Goal**\n"
            "* **Requires ICE** to notify families."
        )

        self.assertEqual(summary, "Main Goal Requires ICE to notify families.")

    def test_summary_has_a_hard_word_limit(self) -> None:
        summary = clean_summary_for_post(" ".join(["word"] * 120))

        self.assertEqual(len(summary.rstrip("…").split()), 90)

    def test_debug_artifacts_include_a_narrated_video(self) -> None:
        with self.subTest("writes image and video using matching document stem"):
            with tempfile.TemporaryDirectory() as temporary_directory:
                output_directory = Path(temporary_directory)
                text_to_image = Mock()
                create_narrated_video = Mock()

                _write_debug_artifacts(
                    output_directory,
                    "H.R. 42",
                    "Requires an example action.",
                    "Post title",
                    "Image text to narrate.",
                    text_to_image,
                    create_narrated_video,
                )

        image_path = output_directory / "h-r-42.png"
        video_path = output_directory / "h-r-42.mp4"
        text_to_image.assert_called_once_with("Image text to narrate.", str(image_path))
        create_narrated_video.assert_called_once_with(
            image_path, "Image text to narrate.", video_path
        )

    @patch("app.summarize_date", return_value=0)
    def test_main_passes_the_date_to_one_shot_job(self, summarize_date) -> None:
        with patch.object(sys, "argv", ["app.py", "--date", "2026-08-14"]):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        summarize_date.assert_called_once_with(date(2026, 8, 14), debug=False, source="both")

    @patch("app.summarize_date", return_value=0)
    def test_main_enables_dry_run_with_debug_flag(self, summarize_date) -> None:
        with patch.object(sys, "argv", ["app.py", "--date", "2026-08-14", "--debug"]):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        summarize_date.assert_called_once_with(date(2026, 8, 14), debug=True, source="both")

    @patch("app.summarize_date", return_value=0)
    def test_main_can_select_executive_orders_only(self, summarize_date) -> None:
        with patch.object(
            sys,
            "argv",
            ["app.py", "--date", "2026-08-14", "--source", "executive-orders"],
        ):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        summarize_date.assert_called_once_with(
            date(2026, 8, 14),
            debug=False,
            source="executive-orders",
        )

    @patch("app.fetch_executive_orders_published_on", return_value=[])
    @patch("app.fetch_bills_with_latest_action_on", return_value=[])
    def test_both_source_fetches_bills_and_executive_orders(
        self, fetch_bills, fetch_executive_orders
    ) -> None:
        documents, failures = _fetch_documents(date(2026, 8, 14), "both")

        self.assertEqual(documents, [])
        self.assertEqual(failures, [])
        fetch_bills.assert_called_once_with(date(2026, 8, 14))
        fetch_executive_orders.assert_called_once_with(date(2026, 8, 14))


if __name__ == "__main__":
    unittest.main()
