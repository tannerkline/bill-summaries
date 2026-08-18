"""Client for published Executive Orders in the Federal Register API."""

from dataclasses import dataclass
from datetime import date
from html import unescape
from html.parser import HTMLParser
import logging
import os
from typing import Any, Optional

import requests


log = logging.getLogger(__name__)

API_ROOT = "https://www.federalregister.gov/api/v1"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_TEXT_MAX_CHARACTERS = 100_000
MAX_RESULTS_PER_DAY = 1_000


class FederalRegisterApiError(RuntimeError):
    """Raised when the Federal Register API cannot provide Executive Order data."""


class _TextExtractor(HTMLParser):
    """Extract readable text from Federal Register HTML or XML."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


@dataclass(frozen=True)
class ExecutiveOrder:
    """Published Executive Order fields needed for a social-media summary."""

    executive_order_number: str
    document_number: str
    url: str
    title: str
    signing_date: date
    publication_date: date
    text: str
    text_source: str


def _html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return unescape(" ".join(parser.parts))


def _configuration() -> tuple[int, int]:
    try:
        timeout_seconds = int(
            os.getenv("FEDERAL_REGISTER_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
    except ValueError as error:
        raise FederalRegisterApiError(
            "FEDERAL_REGISTER_TIMEOUT_SECONDS must be a whole number of seconds"
        ) from error

    try:
        text_max_characters = int(
            os.getenv(
                "EXECUTIVE_ORDER_TEXT_MAX_CHARACTERS",
                str(DEFAULT_TEXT_MAX_CHARACTERS),
            )
        )
    except ValueError as error:
        raise FederalRegisterApiError(
            "EXECUTIVE_ORDER_TEXT_MAX_CHARACTERS must be a whole number"
        ) from error

    if timeout_seconds <= 0 or text_max_characters <= 0:
        raise FederalRegisterApiError(
            "Federal Register configuration values must be positive"
        )
    return timeout_seconds, text_max_characters


def _request_json(
    session: requests.Session,
    url: str,
    timeout_seconds: int,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    try:
        response = session.get(url, params=params, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as error:
        status_code = getattr(error.response, "status_code", None)
        detail = f"HTTP {status_code}" if status_code else type(error).__name__
        raise FederalRegisterApiError(
            f"Federal Register API request failed ({detail})"
        ) from None

    try:
        data = response.json()
    except ValueError as error:
        raise FederalRegisterApiError(
            "Federal Register API returned invalid JSON"
        ) from error
    if not isinstance(data, dict):
        raise FederalRegisterApiError(
            "Federal Register API returned an unexpected response"
        )
    return data


def _request_text(session: requests.Session, url: str, timeout_seconds: int) -> str:
    try:
        response = session.get(url, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as error:
        status_code = getattr(error.response, "status_code", None)
        detail = f"HTTP {status_code}" if status_code else type(error).__name__
        raise FederalRegisterApiError(
            f"Federal Register document text request failed ({detail})"
        ) from None
    return response.text


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise FederalRegisterApiError(
            f"Federal Register document is missing {field_name}"
        )
    try:
        return date.fromisoformat(value[:10])
    except ValueError as error:
        raise FederalRegisterApiError(
            f"Federal Register returned an invalid {field_name}: {value!r}"
        ) from error


def _document_text(
    session: requests.Session,
    document: dict[str, Any],
    timeout_seconds: int,
    maximum_characters: int,
) -> tuple[str, str]:
    """Retrieve readable official text, preferring the plain-text rendition."""
    for field_name, source_name in (
        ("raw_text_url", "official Federal Register text"),
        ("body_html_url", "official Federal Register text"),
        ("full_text_xml_url", "official Federal Register text"),
    ):
        text_url = document.get(field_name)
        if not isinstance(text_url, str) or not text_url:
            continue
        try:
            source_text = _request_text(session, text_url, timeout_seconds)
        except FederalRegisterApiError as error:
            log.warning("Could not retrieve Executive Order text from %s: %s", field_name, error)
            continue

        text = _html_to_text(source_text)
        normalized_text = " ".join(text.split())
        if not normalized_text:
            continue
        if len(normalized_text) > maximum_characters:
            log.info(
                "Truncating Executive Order text from %d to %d characters for model input",
                len(normalized_text),
                maximum_characters,
            )
            normalized_text = normalized_text[:maximum_characters]
        return normalized_text, source_name

    abstract = document.get("abstract")
    if isinstance(abstract, str) and abstract.strip():
        return " ".join(abstract.split()), "Federal Register abstract"
    return "", ""


def _executive_order_from_document(
    session: requests.Session,
    document: dict[str, Any],
    target_date: date,
    timeout_seconds: int,
    maximum_characters: int,
) -> Optional[ExecutiveOrder]:
    signing_date = _parse_date(document.get("signing_date"), "signing date")
    publication_date = _parse_date(document.get("publication_date"), "publication date")
    if publication_date != target_date:
        return None

    executive_order_number = document.get("executive_order_number")
    document_number = document.get("document_number")
    title = document.get("title")
    url = document.get("html_url")
    if executive_order_number is None or not all(
        isinstance(value, str) and value for value in (document_number, title, url)
    ):
        raise FederalRegisterApiError(
            "Federal Register Executive Order is missing required metadata"
        )

    text, text_source = _document_text(
        session,
        document,
        timeout_seconds,
        maximum_characters,
    )
    if not text:
        log.info(
            "Skipping Executive Order %s because Federal Register has no readable text",
            str(executive_order_number),
        )
        return None

    return ExecutiveOrder(
        executive_order_number=f"Executive Order {executive_order_number}",
        document_number=document_number,
        url=url,
        title=title,
        signing_date=signing_date,
        publication_date=publication_date,
        text=text,
        text_source=text_source,
    )


def fetch_executive_orders_published_on(
    target_date: date,
    session: Optional[requests.Session] = None,
) -> list[ExecutiveOrder]:
    """Fetch Executive Orders published on ``target_date`` from Federal Register.

    Publication date is used so a daily job does not miss orders whose Federal
    Register publication occurs days after the President signs them.
    """
    timeout_seconds, maximum_characters = _configuration()
    client = session or requests.Session()
    documents_url = f"{API_ROOT}/documents.json"
    params: dict[str, Any] = {
        "conditions[presidential_document_type][]": "executive_order",
        "conditions[publication_date][is]": target_date.isoformat(),
        "conditions[correction]": "0",
        "per_page": MAX_RESULTS_PER_DAY,
        "order": "newest",
        "fields[]": [
            "document_number",
            "executive_order_number",
            "title",
            "signing_date",
            "publication_date",
            "html_url",
            "raw_text_url",
            "body_html_url",
            "full_text_xml_url",
            "abstract",
        ],
    }
    data = _request_json(client, documents_url, timeout_seconds, params=params)
    documents = data.get("results", [])
    if not isinstance(documents, list):
        raise FederalRegisterApiError(
            "Federal Register API returned an invalid Executive Order list"
        )

    executive_orders = []
    for document in documents:
        if not isinstance(document, dict):
            continue
        if _parse_date(document.get("publication_date"), "publication date") != target_date:
            continue
        executive_order = _executive_order_from_document(
            client,
            document,
            target_date,
            timeout_seconds,
            maximum_characters,
        )
        if executive_order is not None:
            executive_orders.append(executive_order)

    log.info(
        "Federal Register scan for %s: %d document(s) found, %d eligible Executive Order(s)",
        target_date,
        len(documents),
        len(executive_orders),
    )
    return executive_orders
