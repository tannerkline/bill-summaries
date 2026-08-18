import os
import importlib
import sys
import types
import unittest
from unittest.mock import Mock, patch

from social.facebook import create_post as create_facebook_post
from social.linkedin import create_post as create_linkedin_post


class LinkedInPostTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "LINKEDIN_ACCESS_TOKEN": "token",
            "LINKEDIN_ORGANIZATION_URN": "urn:li:organization:123",
            "LINKEDIN_API_VERSION": "202608",
        },
        clear=True,
    )
    @patch("social.linkedin.requests.post")
    def test_creates_public_text_post(self, post: Mock) -> None:
        post.return_value.status_code = 201

        self.assertTrue(create_linkedin_post("A bill summary."))

        post.assert_called_once_with(
            "https://api.linkedin.com/rest/posts",
            headers={
                "Authorization": "Bearer token",
                "Content-Type": "application/json",
                "Linkedin-Version": "202608",
                "X-Restli-Protocol-Version": "2.0.0",
            },
            json={
                "author": "urn:li:organization:123",
                "commentary": "A bill summary.",
                "visibility": "PUBLIC",
                "distribution": {
                    "feedDistribution": "MAIN_FEED",
                    "targetEntities": [],
                    "thirdPartyDistributionChannels": [],
                },
                "lifecycleState": "PUBLISHED",
                "isReshareDisabledByAuthor": False,
            },
            timeout=30,
        )

    @patch.dict(os.environ, {}, clear=True)
    @patch("social.linkedin.requests.post")
    def test_skips_when_not_configured(self, post: Mock) -> None:
        self.assertFalse(create_linkedin_post("A bill summary."))
        post.assert_not_called()


class FacebookPostTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "FACEBOOK_PAGE_ID": "123",
            "FACEBOOK_PAGE_ACCESS_TOKEN": "token",
            "FACEBOOK_GRAPH_API_VERSION": "v25.0",
        },
        clear=True,
    )
    @patch("social.facebook.requests.post")
    def test_creates_text_page_post(self, post: Mock) -> None:
        post.return_value.status_code = 200

        self.assertTrue(create_facebook_post("A bill summary."))

        post.assert_called_once_with(
            "https://graph.facebook.com/v25.0/123/feed",
            data={"message": "A bill summary.", "access_token": "token"},
            timeout=30,
        )

    @patch.dict(os.environ, {}, clear=True)
    @patch("social.facebook.requests.post")
    def test_skips_when_not_configured(self, post: Mock) -> None:
        self.assertFalse(create_facebook_post("A bill summary."))
        post.assert_not_called()


class TwitterErrorLogTests(unittest.TestCase):
    def test_logs_structured_twitter_error_details_without_request_data(self) -> None:
        oauth_module = types.ModuleType("requests_oauthlib")
        oauth_module.OAuth1 = Mock()
        with patch.dict(sys.modules, {"requests_oauthlib": oauth_module}):
            twitter = importlib.import_module("social.twitter")

        response = Mock()
        response.status_code = 403
        response.json.return_value = {
            "title": "Forbidden",
            "detail": "The authenticated user is not permitted to post.",
            "errors": [{"message": "Forbidden", "code": 403}],
        }

        with patch.object(twitter.log, "warning") as warning:
            twitter._log_api_error("tweet creation", response)

        warning.assert_called_once_with(
            "Twitter %s failed: HTTP %d; response=%s",
            "tweet creation",
            403,
            (
                '{"title": "Forbidden", "detail": '
                '"The authenticated user is not permitted to post.", '
                '"errors": [{"message": "Forbidden", "code": 403}]}'
            ),
        )
