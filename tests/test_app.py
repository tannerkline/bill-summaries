from datetime import date
import argparse
import sys
import unittest
from unittest.mock import patch

from app import clean_summary_for_post, main, parse_date


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

    @patch("app.summarize_date", return_value=0)
    def test_main_passes_the_date_to_one_shot_job(self, summarize_date) -> None:
        with patch.object(sys, "argv", ["app.py", "--date", "2026-08-14"]):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        summarize_date.assert_called_once_with(date(2026, 8, 14), debug=False)

    @patch("app.summarize_date", return_value=0)
    def test_main_enables_dry_run_with_debug_flag(self, summarize_date) -> None:
        with patch.object(sys, "argv", ["app.py", "--date", "2026-08-14", "--debug"]):
            exit_code = main()

        self.assertEqual(exit_code, 0)
        summarize_date.assert_called_once_with(date(2026, 8, 14), debug=True)


if __name__ == "__main__":
    unittest.main()
