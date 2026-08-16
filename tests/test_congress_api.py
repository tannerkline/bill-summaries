from datetime import date
import os
import unittest
from unittest.mock import Mock, patch

import requests

from util.congress_api import (
    CongressApiError,
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
        self.assertEqual(bill.date_of_introduction, date(2026, 1, 3))
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

    @patch.dict("os.environ", {"CONGRESS_API_KEY": "test-api-key"}, clear=False)
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


if __name__ == "__main__":
    unittest.main()
