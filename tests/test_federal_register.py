from datetime import date
import os
import unittest
from unittest.mock import Mock, patch

import requests

from util.federal_register import (
    FederalRegisterApiError,
    _request_json,
    fetch_executive_orders_published_on,
)


def json_response(payload):
    response = Mock()
    response.json.return_value = payload
    return response


class FederalRegisterApiTests(unittest.TestCase):
    def test_fetches_published_executive_order_and_uses_plain_text(self) -> None:
        session = Mock()
        text_response = Mock()
        text_response.text = "Section 1. Direct agencies to test this program."
        session.get.side_effect = [
            json_response(
                {
                    "results": [
                        {
                            "document_number": "2026-10001",
                            "executive_order_number": 14399,
                            "title": "Testing a Federal Program",
                            "signing_date": "2026-08-10",
                            "publication_date": "2026-08-14",
                            "html_url": "https://www.federalregister.gov/documents/test",
                            "raw_text_url": "https://www.federalregister.gov/raw/test.txt",
                        }
                    ]
                }
            ),
            text_response,
        ]

        executive_orders = fetch_executive_orders_published_on(
            date(2026, 8, 14), session=session
        )

        self.assertEqual(len(executive_orders), 1)
        executive_order = executive_orders[0]
        self.assertEqual(executive_order.executive_order_number, "Executive Order 14399")
        self.assertEqual(executive_order.document_number, "2026-10001")
        self.assertEqual(executive_order.signing_date, date(2026, 8, 10))
        self.assertEqual(executive_order.publication_date, date(2026, 8, 14))
        self.assertEqual(
            executive_order.text, "Section 1. Direct agencies to test this program."
        )
        self.assertEqual(executive_order.text_source, "official Federal Register text")
        request_params = session.get.call_args_list[0].kwargs["params"]
        self.assertEqual(
            request_params["conditions[presidential_document_type][]"], "executive_order"
        )
        self.assertEqual(request_params["conditions[publication_date][is]"], "2026-08-14")
        self.assertEqual(request_params["conditions[correction]"], "0")

    def test_falls_back_to_html_and_normalizes_its_text(self) -> None:
        session = Mock()
        text_response = Mock()
        text_response.text = "<html><body>Section 1. <strong>Act now.</strong></body></html>"
        session.get.side_effect = [
            json_response(
                {
                    "results": [
                        {
                            "document_number": "2026-10002",
                            "executive_order_number": "14400",
                            "title": "Testing HTML Text",
                            "signing_date": "2026-08-14",
                            "publication_date": "2026-08-14",
                            "html_url": "https://www.federalregister.gov/documents/test-html",
                            "body_html_url": "https://www.federalregister.gov/html/test.html",
                        }
                    ]
                }
            ),
            text_response,
        ]

        executive_orders = fetch_executive_orders_published_on(
            date(2026, 8, 14), session=session
        )

        self.assertEqual(executive_orders[0].text, "Section 1. Act now.")

    def test_ignores_documents_with_a_different_publication_date(self) -> None:
        session = Mock()
        session.get.return_value = json_response(
            {
                "results": [
                    {
                        "publication_date": "2026-08-13",
                    }
                ]
            }
        )

        executive_orders = fetch_executive_orders_published_on(
            date(2026, 8, 14), session=session
        )

        self.assertEqual(executive_orders, [])
        session.get.assert_called_once()

    def test_uses_abstract_when_no_full_text_rendition_is_available(self) -> None:
        session = Mock()
        session.get.return_value = json_response(
            {
                "results": [
                    {
                        "document_number": "2026-10003",
                        "executive_order_number": "14401",
                        "title": "Testing Abstract Fallback",
                        "signing_date": "2026-08-14",
                        "publication_date": "2026-08-14",
                        "html_url": "https://www.federalregister.gov/documents/test-abstract",
                        "abstract": "  Directs agencies to test the program.  ",
                    }
                ]
            }
        )

        executive_orders = fetch_executive_orders_published_on(
            date(2026, 8, 14), session=session
        )

        self.assertEqual(executive_orders[0].text, "Directs agencies to test the program.")
        self.assertEqual(executive_orders[0].text_source, "Federal Register abstract")

    def test_hides_the_underlying_request_url_when_a_request_fails(self) -> None:
        session = Mock()
        response = Mock()
        response.raise_for_status.side_effect = requests.HTTPError("Request URL")
        session.get.return_value = response

        with self.assertRaisesRegex(FederalRegisterApiError, "HTTP") as context:
            _request_json(session, "https://www.federalregister.gov/api/v1/documents.json", 30)

        self.assertIsNone(context.exception.__cause__)

    @patch.dict(os.environ, {"FEDERAL_REGISTER_TIMEOUT_SECONDS": "0"}, clear=False)
    def test_rejects_non_positive_timeout(self) -> None:
        with self.assertRaisesRegex(FederalRegisterApiError, "positive"):
            fetch_executive_orders_published_on(date(2026, 8, 14))


if __name__ == "__main__":
    unittest.main()
