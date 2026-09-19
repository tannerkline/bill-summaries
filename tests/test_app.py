from datetime import date
import argparse
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

from app import (
    _document_hashtags,
    _fetch_documents,
    _narration_copy,
    _write_debug_artifacts,
    clean_summary_for_post,
    main,
    parse_date,
)
from util.congress_api import CongressBill
from util.debug_video import NARRATION_PAUSE_MARKER
from util.federal_register import ExecutiveOrder


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

    def test_narration_leads_with_the_latest_congressional_action(self) -> None:
        bill = CongressBill(
            legislation_number="H.R. 42",
            url="https://example.test/bill",
            congress="119",
            title="An Act to Improve Example Programs",
            sponsor="Example Sponsor",
            sponsor_party="I",
            date_of_introduction=date(2026, 1, 3),
            latest_action="Referred to the House Committee on the Judiciary",
            latest_action_date=date(2026, 8, 13),
            latest_summary="Official source text",
            summary_source="official CRS summary",
        )

        narration = _narration_copy(bill, "Creates an example program.")

        self.assertTrue(narration.startswith("H.R. 42. Latest action:"))
        self.assertIn("Referred to the House Committee on the Judiciary", narration)
        self.assertIn("On August 13, 2026.", narration)
        self.assertIn(NARRATION_PAUSE_MARKER, narration)

    def test_hashtags_include_document_and_matched_topics(self) -> None:
        bill = CongressBill(
            legislation_number="H.R. 42",
            url="https://example.test/bill",
            congress="119",
            title="A Vaccine and Public Health Act",
            sponsor="Example Sponsor",
            sponsor_party="I",
            date_of_introduction=date(2026, 1, 3),
            latest_action="Referred to committee",
            latest_action_date=date(2026, 8, 13),
            latest_summary="Official source text",
            summary_source="official CRS summary",
        )

        hashtags = _document_hashtags(bill, "Improves vaccine access and healthcare.")

        self.assertEqual(
            hashtags,
            [
                "#Politics",
                "#Congress",
                "#Bill",
                "#Law",
                "#Legislation",
                "#PublicPolicy",
                "#USPolitics",
                "#Vaccines",
                "#Healthcare",
            ],
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


class TopicHashtagTests(unittest.TestCase):
    def bill(self, title: str) -> CongressBill:
        return CongressBill(
            legislation_number="H.R. 42", url="https://example.test/bill",
            congress="119", title=title, sponsor="Example Sponsor", sponsor_party="I",
            date_of_introduction=date(2026, 1, 3), latest_action="Referred to committee",
            latest_action_date=date(2026, 8, 13), latest_summary="Official source text",
            summary_source="official CRS summary",
        )

    def test_covers_new_policy_areas(self) -> None:
        cases = [
            ("Credit Union Investment Authority Act", "Allows investments in corporate debt and asset-backed securities.", ["#Banking", "#FinancialMarkets"]),
            ("Veterans Benefits Act", "Improves healthcare for veterans.", ["#Veterans", "#Healthcare"]),
            ("Student Loan Relief Act", "Reduces student debt.", ["#HigherEducation", "#Education"]),
            ("Digital Privacy Act", "Protects personal data from surveillance.", ["#DataPrivacy"]),
            ("Disaster Recovery Act", "Funds FEMA hurricane recovery.", ["#DisasterRelief"]),
            ("Tribal Services Act", "Supports tribal governments.", ["#TribalAffairs"]),
            ("Postal Facility Naming Act", "Renames a post office.", ["#PostalService"]),
            ("Trade Agreement Act", "Changes tariffs on imports.", ["#TradePolicy"]),
            ("Community Support Act", "Expands child care and paid family leave.", ["#Childcare", "#PaidLeave"]),
            ("Election Administration Act", "Updates campaign finance rules.", ["#Elections"]),
        ]
        for title, summary, expected in cases:
            with self.subTest(title=title):
                self.assertEqual(_document_hashtags(self.bill(title), summary)[7:], expected)

    def test_does_not_match_parts_of_unrelated_words(self) -> None:
        tags = _document_hashtags(
            self.bill("Notice for Parents Act"),
            "An office updates its guidance on unfair treatment and taxi licenses.",
        )
        self.assertEqual(len(tags), 7)

    def test_handles_case_hyphens_and_plural_terms(self) -> None:
        tags = _document_hashtags(
            self.bill("MENTAL–HEALTH Services Act"),
            "Supports mental-health care at schools for students and teachers.",
        )
        self.assertEqual(tags[7:], ["#MentalHealth", "#Healthcare"])

    def test_specific_topics_take_priority_and_keep_two_tag_limit(self) -> None:
        tags = _document_hashtags(
            self.bill("Technology and Infrastructure Act"),
            "Funds artificial intelligence research, cybersecurity, and broadband.",
        )
        self.assertEqual(tags[7:], ["#ArtificialIntelligence", "#Cybersecurity"])
        self.assertEqual(len(tags), len(set(tags)))

    def test_executive_orders_use_expanded_topics(self) -> None:
        order = ExecutiveOrder(
            executive_order_number="Executive Order 12345", document_number="2026-12345",
            url="https://example.test/order", title="Securing Federal Networks",
            signing_date=date(2026, 8, 13), publication_date=date(2026, 8, 14),
            text="Source text", text_source="official full text",
        )
        tags = _document_hashtags(order, "Improves cybersecurity and protects personal data.")
        self.assertIn("#ExecutiveOrder", tags)
        self.assertEqual(tags[7:], ["#Cybersecurity", "#DataPrivacy"])


if __name__ == "__main__":
    unittest.main()
