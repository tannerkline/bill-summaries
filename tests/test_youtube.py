from datetime import date
from pathlib import Path
import os
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

from app import _youtube_metadata
from util.congress_api import CongressBill
from social.youtube import _credentials_from_environment, _upload_configuration, create_post


class YouTubeUploadTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_defaults_upload_visibility_to_public(self) -> None:
        self.assertEqual(_upload_configuration(), ("public", False))

    def test_youtube_metadata_includes_relevant_hashtags_and_tags(self) -> None:
        bill = CongressBill(
            legislation_number="H.R. 42",
            url="https://example.test/bill",
            congress="119",
            title="A Vaccine Access Act",
            sponsor="Example Sponsor",
            sponsor_party="I",
            date_of_introduction=date(2026, 1, 3),
            latest_action="Referred to committee",
            latest_action_date=date(2026, 8, 13),
            latest_summary="Official source text",
            summary_source="official CRS summary",
        )

        _, description, tags = _youtube_metadata(bill, "Improves vaccine access.")

        self.assertIn("#Shorts #Politics #Congress #Bill #Law", description)
        self.assertIn("#Vaccines", description)
        self.assertIn("Congress", tags)
        self.assertIn("Vaccines", tags)

    @patch.dict(os.environ, {}, clear=True)
    def test_skips_when_no_oauth_token_is_configured(self) -> None:
        self.assertIsNone(_credentials_from_environment())

    @patch.dict(
        os.environ,
        {
            "YOUTUBE_PRIVACY_STATUS": "private",
            "YOUTUBE_NOTIFY_SUBSCRIBERS": "false",
        },
        clear=True,
    )
    @patch("social.youtube._credentials_from_environment", return_value="credentials")
    def test_creates_video_post_with_short_metadata(self, credentials: Mock) -> None:
        request = Mock()
        request.execute.return_value = {"id": "video-id"}
        service = Mock()
        service.videos.return_value.insert.return_value = request
        build = Mock(return_value=service)
        media_upload = Mock(return_value="media-upload")
        google_api_client = types.ModuleType("googleapiclient")
        google_api_client.__path__ = []
        discovery = types.ModuleType("googleapiclient.discovery")
        discovery.build = build
        http = types.ModuleType("googleapiclient.http")
        http.MediaFileUpload = media_upload

        with tempfile.TemporaryDirectory() as temporary_directory:
            video_path = Path(temporary_directory) / "summary.mp4"
            video_path.write_bytes(b"fake-video")
            with patch.dict(
                sys.modules,
                {
                    "googleapiclient": google_api_client,
                    "googleapiclient.discovery": discovery,
                    "googleapiclient.http": http,
                },
            ):
                created = create_post(
                    str(video_path),
                    "A bill title",
                    "A narrated summary",
                    ["congress", "legislation"],
                )

        self.assertTrue(created)
        credentials.assert_called_once_with()
        build.assert_called_once_with("youtube", "v3", credentials="credentials", cache_discovery=False)
        media_upload.assert_called_once_with(
            str(video_path), mimetype="video/mp4", resumable=True
        )
        service.videos.return_value.insert.assert_called_once_with(
            part="snippet,status",
            body={
                "snippet": {
                    "title": "A bill title",
                    "description": "A narrated summary",
                    "tags": ["congress", "legislation"],
                    "categoryId": "25",
                },
                "status": {
                    "privacyStatus": "private",
                    "selfDeclaredMadeForKids": False,
                    "containsSyntheticMedia": True,
                },
            },
            media_body="media-upload",
            notifySubscribers=False,
        )


if __name__ == "__main__":
    unittest.main()
