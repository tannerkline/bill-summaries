"""Publish bill summaries to a LinkedIn Organization Page."""

import logging
import os

import requests


log = logging.getLogger(__name__)

POSTS_URL = "https://api.linkedin.com/rest/posts"
DEFAULT_TIMEOUT_SECONDS = 30


def create_post(text: str) -> bool:
    """Create a public, text-only post on the configured LinkedIn organization.

    The application must have LinkedIn Community Management API access, and the
    account that authorized ``LINKEDIN_ACCESS_TOKEN`` must be a Page admin (or
    hold another eligible Page role). ``LINKEDIN_API_VERSION`` is deliberately
    required so deployments can choose a currently supported LinkedIn version.
    """
    access_token = os.environ.get("LINKEDIN_ACCESS_TOKEN")
    organization_urn = os.environ.get("LINKEDIN_ORGANIZATION_URN")
    api_version = os.environ.get("LINKEDIN_API_VERSION")
    if not all((access_token, organization_urn, api_version)):
        log.error(
            "LinkedIn post skipped: set LINKEDIN_ACCESS_TOKEN, "
            "LINKEDIN_ORGANIZATION_URN, and LINKEDIN_API_VERSION"
        )
        return False

    payload = {
        "author": organization_urn,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }
    try:
        response = requests.post(
            POSTS_URL,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Content-Type": "application/json",
                "Linkedin-Version": api_version,
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json=payload,
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        log.exception("LinkedIn post request failed")
        return False

    if not 200 <= response.status_code < 300:
        log.error("LinkedIn post failed with status code %d", response.status_code)
        return False

    log.info("LinkedIn post created")
    return True
