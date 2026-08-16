"""Client for the authenticated Congress.gov v3 API."""

from dataclasses import dataclass
from datetime import date, timedelta
from html import unescape
from html.parser import HTMLParser
import logging
import os
from typing import Any, Optional

import requests


log = logging.getLogger(__name__)

API_ROOT = "https://api.congress.gov/v3"
DEFAULT_TIMEOUT_SECONDS = 30
MAX_PAGE_SIZE = 250
DEFAULT_BILL_TEXT_MAX_CHARACTERS = 100_000

_BILL_LABELS = {
    "HR": "H.R.",
    "S": "S.",
    "HJRES": "H.J.Res.",
    "SJRES": "S.J.Res.",
    "HCONRES": "H.Con.Res.",
    "SCONRES": "S.Con.Res.",
    "HRES": "H.Res.",
    "SRES": "S.Res.",
}

_BILL_URL_TYPES = {
    "HR": "house-bill",
    "S": "senate-bill",
    "HJRES": "house-joint-resolution",
    "SJRES": "senate-joint-resolution",
    "HCONRES": "house-concurrent-resolution",
    "SCONRES": "senate-concurrent-resolution",
    "HRES": "house-resolution",
    "SRES": "senate-resolution",
}


class _TextExtractor(HTMLParser):
    """Extract visible text from published HTML or XML bill documents."""

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    parser.close()
    return unescape(" ".join(parser.parts))


class CongressApiError(RuntimeError):
    """Raised when Congress.gov's API cannot provide bill data."""


@dataclass(frozen=True)
class CongressBill:
    """Fields used to generate one social-media summary."""

    legislation_number: str
    url: str
    congress: str
    title: str
    sponsor: str
    sponsor_party: str
    date_of_introduction: date
    latest_action: str
    latest_action_date: date
    latest_summary: str
    summary_source: str


def _configuration() -> tuple[str, int, int]:
    api_key = os.getenv("CONGRESS_API_KEY", "").strip()
    if not api_key:
        raise CongressApiError("CONGRESS_API_KEY is not configured")

    try:
        timeout_seconds = int(
            os.getenv("CONGRESS_API_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))
        )
    except ValueError as error:
        raise CongressApiError(
            "CONGRESS_API_TIMEOUT_SECONDS must be a whole number of seconds"
        ) from error

    if timeout_seconds <= 0:
        raise CongressApiError("CONGRESS_API_TIMEOUT_SECONDS must be positive")

    try:
        bill_text_max_characters = int(
            os.getenv(
                "CONGRESS_BILL_TEXT_MAX_CHARACTERS",
                str(DEFAULT_BILL_TEXT_MAX_CHARACTERS),
            )
        )
    except ValueError as error:
        raise CongressApiError(
            "CONGRESS_BILL_TEXT_MAX_CHARACTERS must be a whole number"
        ) from error

    if bill_text_max_characters <= 0:
        raise CongressApiError("CONGRESS_BILL_TEXT_MAX_CHARACTERS must be positive")

    return api_key, timeout_seconds, bill_text_max_characters


def _request_json(
    session: requests.Session,
    url: str,
    api_key: str,
    timeout_seconds: int,
    params: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    request_params = {"api_key": api_key, "format": "json"}
    if params:
        request_params.update(params)

    try:
        response = session.get(url, params=request_params, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as error:
        status_code = getattr(error.response, "status_code", None)
        detail = f"HTTP {status_code}" if status_code else type(error).__name__
        # The API key is passed as a query parameter, so do not preserve the
        # lower-level exception: Requests may include its full URL in a trace.
        raise CongressApiError(f"Congress.gov API request failed ({detail})") from None

    try:
        data = response.json()
    except ValueError as error:
        raise CongressApiError("Congress.gov API returned invalid JSON") from error

    if not isinstance(data, dict):
        raise CongressApiError("Congress.gov API returned an unexpected response")
    return data


def _parse_date(value: Any, field_name: str) -> date:
    if not isinstance(value, str):
        raise CongressApiError(f"Congress.gov API response is missing {field_name}")
    try:
        return date.fromisoformat(value[:10])
    except ValueError as error:
        raise CongressApiError(
            f"Congress.gov API returned an invalid {field_name}: {value!r}"
        ) from error


def _congress_url(congress: Any, bill_type: Any, bill_number: Any) -> str:
    url_type = _BILL_URL_TYPES.get(str(bill_type).upper(), "bill")
    return (
        f"https://www.congress.gov/bill/{congress}th-congress/"
        f"{url_type}/{bill_number}"
    )


def _latest_summary(
    session: requests.Session,
    summaries_url: str,
    api_key: str,
    timeout_seconds: int,
) -> str:
    data = _request_json(session, summaries_url, api_key, timeout_seconds)
    summaries = data.get("summaries", [])
    if not isinstance(summaries, list) or not summaries:
        return ""

    latest = max(
        (summary for summary in summaries if isinstance(summary, dict)),
        key=lambda summary: (
            str(summary.get("actionDate", "")),
            str(summary.get("updateDate", "")),
        ),
        default=None,
    )
    if latest is None:
        return ""
    text = latest.get("text", "")
    return text if isinstance(text, str) else ""


def _request_bill_text(
    session: requests.Session, text_url: str, timeout_seconds: int
) -> str:
    """Fetch a published bill-text document without sending the API key onward."""
    try:
        response = session.get(text_url, timeout=timeout_seconds)
        response.raise_for_status()
    except requests.RequestException as error:
        status_code = getattr(error.response, "status_code", None)
        detail = f"HTTP {status_code}" if status_code else type(error).__name__
        raise CongressApiError(f"Published bill text request failed ({detail})") from None
    return response.text


def _latest_bill_text(
    session: requests.Session,
    text_versions_url: str,
    api_key: str,
    timeout_seconds: int,
    max_characters: int,
) -> str:
    """Retrieve the newest readable official bill text, bounded for model input."""
    data = _request_json(session, text_versions_url, api_key, timeout_seconds)
    text_versions = data.get("textVersions", [])
    if not isinstance(text_versions, list):
        return ""

    ordered_versions = sorted(
        (version for version in text_versions if isinstance(version, dict)),
        key=lambda version: str(version.get("date", "")),
        reverse=True,
    )
    text_url: Optional[str] = None
    for version in ordered_versions:
        formats = version.get("formats", [])
        if not isinstance(formats, list):
            continue
        for preferred_format in ("Formatted Text", "Formatted XML"):
            match = next(
                (
                    item
                    for item in formats
                    if isinstance(item, dict)
                    and item.get("type") == preferred_format
                    and isinstance(item.get("url"), str)
                ),
                None,
            )
            if match is not None:
                text_url = match["url"]
                break
        if text_url:
            break

    if text_url is None:
        return ""

    try:
        bill_text = _html_to_text(
            _request_bill_text(session, text_url, timeout_seconds)
        )
    except CongressApiError as error:
        log.warning("Could not retrieve published bill text: %s", error)
        return ""

    normalized_text = " ".join(bill_text.split())
    if len(normalized_text) > max_characters:
        log.info(
            "Truncating official bill text from %d to %d characters for model input",
            len(normalized_text),
            max_characters,
        )
        return normalized_text[:max_characters]
    return normalized_text


def _bill_from_reference(
    session: requests.Session,
    reference: dict[str, Any],
    target_date: date,
    api_key: str,
    timeout_seconds: int,
    bill_text_max_characters: int,
) -> Optional[CongressBill]:
    latest_action = reference.get("latestAction")
    if not isinstance(latest_action, dict):
        return None
    if _parse_date(latest_action.get("actionDate"), "latest action date") != target_date:
        return None
    detail_url = reference.get("url")
    if not isinstance(detail_url, str):
        raise CongressApiError("Congress.gov API response is missing a bill URL")
    detail = _request_json(session, detail_url, api_key, timeout_seconds)
    bill = detail.get("bill")
    if not isinstance(bill, dict):
        raise CongressApiError("Congress.gov API returned an invalid bill record")

    bill_type = str(bill.get("type", "")).upper()
    bill_number = bill.get("number")
    congress = bill.get("congress")
    if not bill_type or bill_number is None or congress is None:
        raise CongressApiError("Congress.gov API bill record is missing its identifier")

    sponsors = bill.get("sponsors", [])
    sponsor = sponsors[0] if isinstance(sponsors, list) and sponsors else {}
    if not isinstance(sponsor, dict):
        sponsor = {}

    summaries = bill.get("summaries", {})
    summary_url = summaries.get("url") if isinstance(summaries, dict) else None
    latest_summary = (
        _latest_summary(session, summary_url, api_key, timeout_seconds)
        if isinstance(summary_url, str)
        else ""
    )
    summary_source = "official CRS summary"
    if not latest_summary:
        text_versions = bill.get("textVersions", {})
        text_versions_url = (
            text_versions.get("url") if isinstance(text_versions, dict) else None
        )
        latest_summary = (
            _latest_bill_text(
                session,
                text_versions_url,
                api_key,
                timeout_seconds,
                bill_text_max_characters,
            )
            if isinstance(text_versions_url, str)
            else ""
        )
        summary_source = "official bill text"
    if not latest_summary:
        log.info(
            "Skipping %s %s because Congress.gov has neither a CRS summary nor readable bill text",
            _BILL_LABELS.get(bill_type, bill_type),
            bill_number,
        )
        return None

    return CongressBill(
        legislation_number=f"{_BILL_LABELS.get(bill_type, bill_type)} {bill_number}",
        url=_congress_url(congress, bill_type, bill_number),
        congress=str(congress),
        title=str(bill.get("title", "Untitled legislation")),
        sponsor=str(sponsor.get("fullName", "Unknown sponsor")),
        sponsor_party=str(sponsor.get("party", "Unknown")),
        date_of_introduction=_parse_date(bill.get("introducedDate"), "introduced date"),
        latest_action=str(latest_action.get("text", "No action text available")).rstrip("."),
        latest_action_date=target_date,
        latest_summary=latest_summary,
        summary_source=summary_source,
    )


def fetch_bills_with_latest_action_on(
    target_date: date,
    session: Optional[requests.Session] = None,
) -> list[CongressBill]:
    """Fetch bills updated around ``target_date`` whose latest action is that day.

    The API's date filters apply to its update timestamp, not its legislative
    action date. We therefore request the target date and the following day,
    then filter records using their actual ``latestAction.actionDate``.
    """
    api_key, timeout_seconds, bill_text_max_characters = _configuration()
    client = session or requests.Session()
    start = f"{target_date.isoformat()}T00:00:00Z"
    end = f"{(target_date + timedelta(days=2)).isoformat()}T00:00:00Z"
    page_url = f"{API_ROOT}/bill"
    page_params: Optional[dict[str, Any]] = {
        "fromDateTime": start,
        "toDateTime": end,
        "limit": MAX_PAGE_SIZE,
    }
    bills: list[CongressBill] = []
    records_seen = 0
    action_date_matches = 0
    sources_unavailable = 0

    while page_url:
        data = _request_json(
            client, page_url, api_key, timeout_seconds, params=page_params
        )
        page_params = None
        references = data.get("bills", [])
        if not isinstance(references, list):
            raise CongressApiError("Congress.gov API returned an invalid bill list")

        for reference in references:
            if not isinstance(reference, dict):
                continue
            records_seen += 1
            latest_action = reference.get("latestAction")
            if not isinstance(latest_action, dict):
                continue
            if _parse_date(
                latest_action.get("actionDate"), "latest action date"
            ) != target_date:
                continue
            action_date_matches += 1

            bill = _bill_from_reference(
                client,
                reference,
                target_date,
                api_key,
                timeout_seconds,
                bill_text_max_characters,
            )
            if bill is not None:
                bills.append(bill)
            else:
                sources_unavailable += 1

        pagination = data.get("pagination", {})
        page_url = pagination.get("next") if isinstance(pagination, dict) else None
        if page_url is not None and not isinstance(page_url, str):
            raise CongressApiError("Congress.gov API returned an invalid next-page URL")

    log.info(
        "Congress.gov API scan for %s: %d record(s) seen, %d latest-action "
        "match(es), %d bill(s) without a usable CRS summary or bill text, "
        "%d eligible bill(s)",
        target_date,
        records_seen,
        action_date_matches,
        sources_unavailable,
        len(bills),
    )
    return bills
