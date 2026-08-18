"""Publish bill summaries to a Facebook Page."""

import logging
import os

import requests


log = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30


def create_post(text: str) -> bool:
    """Create a text-only post on the configured Facebook Page.

    ``FACEBOOK_PAGE_ACCESS_TOKEN`` must be a Page token with the permissions
    required by Meta to publish Page posts. Facebook does not provide an API for
    publishing this content to a personal profile.
    """
    page_id = os.environ.get("FACEBOOK_PAGE_ID")
    access_token = os.environ.get("FACEBOOK_PAGE_ACCESS_TOKEN")
    api_version = os.environ.get("FACEBOOK_GRAPH_API_VERSION")
    if not all((page_id, access_token, api_version)):
        log.error(
            "Facebook post skipped: set FACEBOOK_PAGE_ID, "
            "FACEBOOK_PAGE_ACCESS_TOKEN, and FACEBOOK_GRAPH_API_VERSION"
        )
        return False

    try:
        response = requests.post(
            f"https://graph.facebook.com/{api_version}/{page_id}/feed",
            data={"message": text, "access_token": access_token},
            timeout=DEFAULT_TIMEOUT_SECONDS,
        )
    except requests.RequestException:
        log.exception("Facebook post request failed")
        return False

    if not 200 <= response.status_code < 300:
        log.error("Facebook post failed with status code %d", response.status_code)
        return False

    log.info("Facebook post created")
    return True
