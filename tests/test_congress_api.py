from datetime import date
import os
import unittest
from unittest.mock import Mock, patch

import requests

from util.congress_api import (
    CongressApiError,
    _action_is_advanced,
    _request_json,
    fetch_bills_with_latest_action_on,
)


def json_response(payload: dict) -> Mock:
    response = Mock()
    response.json.return_value = payload
    return response


class CongressApiTests(unittest.TestCase):
    @patch.dict("os.environ", {"CONGRESS_API_KEY": "test-api-key"}, clear=False)
    def test_fetches_bill_details_and_latest_summary(self) -> None:
        session = Mock()
        session.get.side_effect = [
            json_response(
                {
                    "bills": [
                        {
                            "latestAction": {
                                "actionDate": "2026-08-14",
                                "text": "Passed House.",
                            },
                            "url": "https://api.congress.gov/v3/bill/119/hr/42",
                        }
                    ],
                    "pagination": {},
                }
            ),
            json_response(
                {
                    "bill": {
                        "type": "HR",
                        "number": "42",
                        "congress": 119,
                        "title": "A test bill",
                        "introducedDate": "2026-01-03",
                        "sponsors": [
                            {"fullName": "Rep. Example, Pat [D-CA-1]", "party": "D"}
                        ],
                        "summaries": {
                            "url": "https://api.congress.gov/v3/bill/119/hr/42/summaries"
                        },
                    }
                }
            ),
            json_response({"actions": []}),
            json_response(
                {
                    "summaries": [
                        {"actionDate": "2026-01-03", "text": "Earlier summary"},
                        {"actionDate": "2026-08-14", "text": "Latest summary"},
                    ]
                }
            ),
        ]

        bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)

        self.assertEqual(len(bills), 1)
        bill = bills[0]
        self.assertEqual(bill.legislation_number, "H.R. 42")
        self.assertEqual(
            bill.url,
            "https://www.congress.gov/bill/119th-congress/house-bill/42",
        )
        self.assertEqual(bill.sponsor_party, "D")
        self.assertEqual(bill.latest_summary, "Latest summary")
        self.assertEqual(bill.summary_source, "official CRS summary")
        self.assertEqual(bill.latest_action, "Passed House")
        self.assertEqual(bill.progress.reached, (True, True, False, False, False))
        self.assertEqual(bill.date_of_introduction, date(2026, 1, 3))
        self.assertEqual(
            session.get.call_args_list[0].args[0],
            "https://api.congress.gov/v3/bill/119",
        )
        self.assertEqual(
            session.get.call_args_list[0].kwargs["params"],
            {
                "api_key": "test-api-key",
                "format": "json",
                "fromDateTime": "2026-08-14T00:00:00Z",
                "toDateTime": "2026-08-16T00:00:00Z",
                "limit": 250,
            },
        )

    @patch.dict(
        "os.environ",
        {"CONGRESS_API_KEY": "test-api-key", "CONGRESS_NUMBER": "120"},
        clear=False,
    )
    def test_uses_the_configured_congress_endpoint(self) -> None:
        session = Mock()
        session.get.return_value = json_response({"bills": [], "pagination": {}})

        bills = fetch_bills_with_latest_action_on(date(2027, 1, 4), session=session)

        self.assertEqual(bills, [])
        self.assertEqual(
            session.get.call_args.args[0], "https://api.congress.gov/v3/bill/120"
        )

    @patch.dict("os.environ", {"CONGRESS_API_KEY": "test-api-key"}, clear=False)
    def test_ignores_bills_with_a_different_latest_action_date(self) -> None:
        session = Mock()
        session.get.return_value = json_response(
            {
                "bills": [
                    {
                        "latestAction": {
                            "actionDate": "2026-08-13",
                            "text": "Older action",
                        },
                        "url": "https://api.congress.gov/v3/bill/119/hr/42",
                    }
                ],
                "pagination": {},
            }
        )

        bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)

        self.assertEqual(bills, [])
        session.get.assert_called_once()

    @patch.dict("os.environ", {"CONGRESS_API_KEY": "test-api-key", "CONGRESS_BILL_FILTER": "all"}, clear=False)
    def test_uses_official_bill_text_when_crs_summary_is_unavailable(self) -> None:
        session = Mock()
        text_response = Mock()
        text_response.text = "<html><body>Section 1. A test bill.</body></html>"
        session.get.side_effect = [
            json_response(
                {
                    "bills": [
                        {
                            "latestAction": {
                                "actionDate": "2026-08-14",
                                "text": "Introduced in House",
                            },
                            "url": "https://api.congress.gov/v3/bill/119/hr/42",
                        }
                    ],
                    "pagination": {},
                }
            ),
            json_response(
                {
                    "bill": {
                        "type": "HR",
                        "number": "42",
                        "congress": 119,
                        "title": "A test bill",
                        "introducedDate": "2026-01-03",
                        "sponsors": [],
                        "summaries": {},
                        "textVersions": {
                            "url": "https://api.congress.gov/v3/bill/119/hr/42/text"
                        },
                    }
                }
            ),
            json_response({"actions": []}),
            json_response(
                {
                    "textVersions": [
                        {
                            "date": "2026-08-14",
                            "formats": [
                                {
                                    "type": "Formatted Text",
                                    "url": "https://www.congress.gov/bill-text.html",
                                }
                            ],
                        }
                    ]
                }
            ),
            text_response,
        ]

        bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)

        self.assertEqual(len(bills), 1)
        self.assertEqual(bills[0].latest_summary, "Section 1. A test bill.")
        self.assertEqual(bills[0].summary_source, "official bill text")
        self.assertNotIn("api_key", session.get.call_args_list[-1].kwargs)

    @patch.dict("os.environ", {"CONGRESS_API_KEY": "test-api-key"}, clear=False)
    def test_skips_bills_without_an_official_summary_or_bill_text(self) -> None:
        session = Mock()
        session.get.side_effect = [
            json_response(
                {
                    "bills": [
                        {
                            "latestAction": {
                                "actionDate": "2026-08-14",
                                "text": "Passed House",
                            },
                            "url": "https://api.congress.gov/v3/bill/119/hr/42",
                        }
                    ],
                    "pagination": {},
                }
            ),
            json_response(
                {
                    "bill": {
                        "type": "HR",
                        "number": "42",
                        "congress": 119,
                        "title": "A test bill",
                        "introducedDate": "2026-01-03",
                        "sponsors": [],
                        "summaries": {},
                        "textVersions": {},
                    }
                }
            ),
            json_response({"actions": []}),
        ]

        bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)

        self.assertEqual(bills, [])

    @patch.dict("os.environ", {}, clear=True)
    def test_requires_an_api_key(self) -> None:
        with self.assertRaisesRegex(CongressApiError, "CONGRESS_API_KEY"):
            fetch_bills_with_latest_action_on(date(2026, 8, 14))

    def test_hides_the_underlying_request_url_when_a_request_fails(self) -> None:
        session = Mock()
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError(
            "Request URL contains a secret"
        )
        session.get.return_value = response

        with self.assertRaisesRegex(CongressApiError, "HTTP") as context:
            _request_json(
                session,
                "https://api.congress.gov/v3/bill",
                "test-api-key",
                30,
            )

        self.assertIsNone(context.exception.__cause__)


class BillProgressFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        environment = patch.dict(os.environ, {
            "CONGRESS_API_KEY": "test-api-key", "CONGRESS_BILL_FILTER": "committee_or_later",
        })
        environment.start()
        self.addCleanup(environment.stop)

    def session_for(self, latest_action: str, *responses: dict) -> Mock:
        session = Mock()
        session.get.side_effect = [
            json_response({"bills": [{
                "latestAction": {"actionDate": "2026-08-14", "text": latest_action},
                "url": "https://api.congress.gov/v3/bill/119/hr/42",
            }]}),
            json_response({"bill": {
                "type": "HR", "number": "42", "congress": 119,
                "title": "An example bill", "introducedDate": "2026-01-03",
                "actions": {"url": "https://api.congress.gov/v3/bill/119/hr/42/actions"},
                "summaries": {"url": "https://api.congress.gov/v3/bill/119/hr/42/summaries"},
            }}),
            *(json_response(response) for response in responses),
        ]
        return session

    def test_recognizes_milestones_without_matching_early_procedural_actions(self) -> None:
        accepted = [
            "Ordered to be Reported (Amended) by the Yeas and Nays: 30 - 10.",
            "Committee on Finance. Ordered to be reported without amendment favorably.",
            "Committee on Commerce. Reported by Senator Example with an amendment.",
            "Reported (Amended) by the Committee on Energy and Commerce.",
            "Committee on Finance discharged by Unanimous Consent.",
            "Passed House.", "Passed Senate without amendment by Unanimous Consent.",
            "Presented to President.", "Signed by President.", "Became Public Law No: 119-42.",
        ]
        rejected = [
            "Introduced in House", "Referred to the House Committee on Education.",
            "Read twice and referred to the Committee on Finance.",
            "Committee on Finance. Hearings held.", "Committee Consideration and Mark-up Session Held.",
            "Subcommittee on Health. Ordered to be reported favorably to the full committee.",
            "Placed on Senate Legislative Calendar under General Orders. Calendar No. 629.",
            "Motion to order the bill reported was not agreed to.",
            "A discharge petition was filed.", "", "Unknown procedural update",
        ]
        for text in accepted:
            with self.subTest(text=text):
                self.assertTrue(_action_is_advanced({"text": text}))
        for text in rejected:
            with self.subTest(text=text):
                self.assertFalse(_action_is_advanced({"text": text}))
        self.assertTrue(_action_is_advanced({"type": "Floor", "text": "Considered by the House."}))
        self.assertTrue(_action_is_advanced({"type": "BecameLaw"}))
        for action_type in ["IntroReferral", "Committee", "Calendars", "NotUsed", "Discharge"]:
            self.assertFalse(_action_is_advanced({"type": action_type}))

    def test_only_interprets_action_codes_from_their_documented_source(self) -> None:
        for source in [9, "9"]:
            self.assertTrue(_action_is_advanced({"sourceSystem": {"code": source}, "actionCode": "5000"}))
        for source in [0, 1, 2, None]:
            self.assertFalse(_action_is_advanced({"sourceSystem": {"code": source}, "actionCode": "5000"}))
        self.assertFalse(_action_is_advanced({"sourceSystem": {"code": 9}, "actionCode": "4200"}))

    def test_skips_early_bills_before_fetching_summary_or_text(self) -> None:
        session = self.session_for("Referred to the House Committee on Education.", {
            "actions": [{"actionDate": "2026-08-14", "type": "IntroReferral", "text": "Introduced in House"}],
        })
        with self.assertLogs("util.congress_api", level="INFO") as logs:
            bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)
        self.assertEqual(bills, [])
        self.assertEqual(session.get.call_count, 3)
        self.assertIn("Skipping H.R. 42", " ".join(logs.output))
        self.assertNotIn("summaries", session.get.call_args.args[0])

    def test_later_referral_keeps_previously_passed_bill_and_reads_all_pages(self) -> None:
        session = self.session_for("Received in the Senate and referred to the Committee on Finance.", {
            "actions": [{"actionDate": "2026-08-14", "type": "IntroReferral", "text": "Referred to committee"}],
            "pagination": {"next": "https://api.congress.gov/v3/bill/119/hr/42/actions?offset=250"},
        }, {
            "actions": [{"actionDate": "2026-08-13", "type": "Floor", "text": "Passed House"}],
        }, {
            "summaries": [{"actionDate": "2026-08-13", "text": "An official summary."}],
        })
        bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)
        self.assertEqual(len(bills), 1)
        self.assertIn("referred", bills[0].latest_action)
        self.assertEqual(bills[0].progress.status, "Passed House")
        self.assertEqual(session.get.call_count, 5)
        self.assertIn("offset=250", session.get.call_args_list[3].args[0])

    def test_later_milestone_does_not_make_earlier_date_eligible(self) -> None:
        session = self.session_for("Introduced in House", {
            "actions": [{"actionDate": "2026-08-15", "type": "Floor", "text": "Passed House"}],
        })
        self.assertEqual(fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session), [])

    @patch.dict(os.environ, {"CONGRESS_BILL_FILTER": "all"})
    def test_progress_excludes_future_actions_even_when_filter_is_disabled(self) -> None:
        session = self.session_for("Referred to committee", {
            "actions": [
                {"actionDate": "2026-08-15", "type": "BecameLaw", "text": "Became Public Law No: 119-42."},
                {"actionDate": "2026-08-13", "type": "Floor", "text": "Passed House"},
            ],
        }, {"summaries": [{"actionDate": "2026-08-13", "text": "Official summary."}]})
        bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)
        self.assertEqual(bills[0].progress.status, "Passed House")
        self.assertFalse(bills[0].progress.reached[-1])

    def test_committee_approval_reads_history_for_progress(self) -> None:
        session = self.session_for("Ordered to be Reported by Voice Vote.", {
            "actions": [],
        }, {
            "summaries": [{"actionDate": "2026-08-14", "text": "An official summary."}],
        })
        bills = fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)
        self.assertEqual(len(bills), 1)
        self.assertEqual(session.get.call_count, 4)

    def test_bad_action_data_does_not_bypass_filter(self) -> None:
        session = self.session_for("Referred to committee", {"actions": None})
        with self.assertRaisesRegex(CongressApiError, "invalid bill actions list"):
            fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)

    @patch.dict(os.environ, {"CONGRESS_BILL_FILTER": "typo"})
    def test_invalid_filter_configuration_fails_before_network_request(self) -> None:
        session = Mock()
        with self.assertRaisesRegex(CongressApiError, "CONGRESS_BILL_FILTER"):
            fetch_bills_with_latest_action_on(date(2026, 8, 14), session=session)
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
