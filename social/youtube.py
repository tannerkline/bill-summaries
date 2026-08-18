"""Publish narrated videos to YouTube through its Data API."""

import logging
import os
from pathlib import Path
from typing import Optional


log = logging.getLogger(__name__)

YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_TOKEN_URI = "https://oauth2.googleapis.com/token"
VALID_PRIVACY_STATUSES = {"private", "public", "unlisted"}
MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5_000


def _credentials_from_environment():
    """Create OAuth credentials from the same environment-based setup as peers.

    A currently valid ``YOUTUBE_ACCESS_TOKEN`` is enough for a manual run. For
    recurring posts, set the client ID, client secret, and refresh token so a
    new access token is obtained automatically on every run.
    """
    access_token = os.environ.get("YOUTUBE_ACCESS_TOKEN", "").strip()
    refresh_token = os.environ.get("YOUTUBE_REFRESH_TOKEN", "").strip()
    client_id = os.environ.get("YOUTUBE_CLIENT_ID", "").strip()
    client_secret = os.environ.get("YOUTUBE_CLIENT_SECRET", "").strip()

    if not access_token and not refresh_token:
        log.error(
            "YouTube post skipped: set YOUTUBE_ACCESS_TOKEN or "
            "YOUTUBE_REFRESH_TOKEN"
        )
        return None
    if refresh_token and (not client_id or not client_secret):
        log.error(
            "YouTube post skipped: YOUTUBE_REFRESH_TOKEN requires "
            "YOUTUBE_CLIENT_ID and YOUTUBE_CLIENT_SECRET"
        )
        return None

    try:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
    except ImportError:
        log.exception("YouTube post skipped: Google API dependencies are unavailable")
        return None

    credentials = Credentials(
        token=access_token or None,
        refresh_token=refresh_token or None,
        token_uri=YOUTUBE_TOKEN_URI,
        client_id=client_id or None,
        client_secret=client_secret or None,
        scopes=[YOUTUBE_UPLOAD_SCOPE],
    )
    if refresh_token:
        try:
            credentials.refresh(Request())
        except RefreshError:
            log.exception("YouTube post skipped: could not refresh OAuth credentials")
            return None
    return credentials


def _upload_configuration() -> Optional[tuple[str, bool]]:
    """Read post privacy and subscriber-notification settings."""
    privacy_status = os.environ.get("YOUTUBE_PRIVACY_STATUS", "public").lower()
    if privacy_status not in VALID_PRIVACY_STATUSES:
        choices = ", ".join(sorted(VALID_PRIVACY_STATUSES))
        log.error("YouTube post skipped: YOUTUBE_PRIVACY_STATUS must be one of: %s", choices)
        return None

    notify_subscribers = os.environ.get("YOUTUBE_NOTIFY_SUBSCRIBERS", "false").lower()
    if notify_subscribers not in {"true", "false"}:
        log.error("YouTube post skipped: YOUTUBE_NOTIFY_SUBSCRIBERS must be true or false")
        return None
    return privacy_status, notify_subscribers == "true"


def _trim(value: str, maximum_length: int) -> str:
    """Trim YouTube metadata without leaving trailing whitespace."""
    return value.strip()[:maximum_length].rstrip()


def create_post(video_path: str, title: str, description: str, tags: list[str]) -> bool:
    """Upload an MP4 to the configured YouTube channel.

    YouTube determines whether the upload is a Short from the video itself. The
    application's narrated 1080x1350 MP4 is vertical and is eligible whenever
    its duration is at most three minutes.
    """
    video = Path(video_path)
    if not video.is_file():
        log.error("YouTube post skipped: video file does not exist: %s", video)
        return False
    if not title.strip():
        log.error("YouTube post skipped: title cannot be empty")
        return False

    credentials = _credentials_from_environment()
    configuration = _upload_configuration()
    if not credentials or not configuration:
        return False
    privacy_status, notify_subscribers = configuration

    try:
        from googleapiclient.discovery import build
        from googleapiclient.http import MediaFileUpload

        service = build("youtube", "v3", credentials=credentials, cache_discovery=False)
        response = service.videos().insert(
            part="snippet,status",
            body={
                "snippet": {
                    "title": _trim(title, MAX_TITLE_LENGTH),
                    "description": _trim(description, MAX_DESCRIPTION_LENGTH),
                    "tags": tags,
                    "categoryId": "25",  # News & Politics
                },
                "status": {
                    "privacyStatus": privacy_status,
                    "selfDeclaredMadeForKids": False,
                    "containsSyntheticMedia": True,
                },
            },
            media_body=MediaFileUpload(str(video), mimetype="video/mp4", resumable=True),
            notifySubscribers=notify_subscribers,
        ).execute()
    except Exception as error:
        status_code = getattr(getattr(error, "resp", None), "status", None)
        detail = f"HTTP {status_code}" if status_code else type(error).__name__
        log.error("YouTube post failed (%s)", detail)
        return False

    video_id = response.get("id") if isinstance(response, dict) else None
    if not isinstance(video_id, str) or not video_id:
        log.error("YouTube post failed: API response did not contain a video ID")
        return False
    log.info("YouTube video uploaded: https://www.youtube.com/watch?v=%s", video_id)
    return True
