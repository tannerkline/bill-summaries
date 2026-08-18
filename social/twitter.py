import requests
import os
import logging
import time
import json
from requests_oauthlib import OAuth1

# logging setup
logging.basicConfig(datefmt='%Y/%m/%d %H:%M:%S', format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

TWITTER_API_KEY = os.environ.get("TWITTER_API_KEY")
TWITTER_API_KEY_SECRET = os.environ.get("TWITTER_API_KEY_SECRET")
TWITTER_ACCESS_TOKEN = os.environ.get("TWITTER_ACCESS_TOKEN")
TWITTER_ACCESS_SECRET = os.environ.get("TWITTER_ACCESS_SECRET")
oauth = OAuth1(
    client_key=TWITTER_API_KEY,
    client_secret=TWITTER_API_KEY_SECRET,
    resource_owner_key=TWITTER_ACCESS_TOKEN,
    resource_owner_secret=TWITTER_ACCESS_SECRET
)


def _response_json(response: requests.Response) -> dict:
    """Return a JSON object when Twitter supplied one, otherwise an empty object."""
    try:
        data = response.json()
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _error_details(response: requests.Response) -> str:
    """Extract useful Twitter error fields without logging request credentials."""
    response_data = _response_json(response)
    if response_data:
        details = {}
        for field_name in ("title", "detail", "type", "errors"):
            if field_name in response_data:
                details[field_name] = response_data[field_name]
        if details:
            return json.dumps(details, ensure_ascii=False)[:2_000]

    response_text = getattr(response, "text", "")
    if isinstance(response_text, str) and response_text.strip():
        return " ".join(response_text.split())[:1_000]
    return "Twitter did not provide a readable error body"


def _log_api_error(operation: str, response: requests.Response) -> None:
    """Log response details needed to diagnose non-success Twitter responses."""
    log.warning(
        "Twitter %s failed: HTTP %d; response=%s",
        operation,
        response.status_code,
        _error_details(response),
    )


def _is_success(response: requests.Response) -> bool:
    return 200 <= response.status_code < 300


def _is_tweet_too_long(response: requests.Response) -> bool:
    errors = _response_json(response).get("errors", [])
    return (
        isinstance(errors, list)
        and len(errors) == 1
        and isinstance(errors[0], dict)
        and str(errors[0].get("message", "")).startswith("Your Tweet text is too long")
    )


def _retry_rate_limited_request(request, operation: str) -> requests.Response:
    """Retry a Twitter request after 429 responses, returning its final response."""
    response = request()
    retry_count = 0
    while response.status_code == 429:
        _log_api_error(operation, response)
        if retry_count >= 10:
            log.warning("Twitter %s timed out while waiting for rate limiting", operation)
            return response
        retry_count += 1
        log.info("Twitter %s was rate limited; waiting 30 minutes before retry %d", operation, retry_count)
        time.sleep(60 * 30)
        response = request()
    return response

def create_post(file_path: str, text: str, text_short: str) -> bool:
    """Upload the image and create a tweet, with safe API-error diagnostics."""
    resp = _retry_rate_limited_request(
        lambda: upload_media(file_path), "media upload"
    )
    if not _is_success(resp):
        _log_api_error("media upload", resp)
        return False

    media_id = _response_json(resp).get("media_id_string", "")
    if not media_id:
        log.warning(
            "Twitter media upload succeeded but returned no media ID; response=%s",
            _error_details(resp),
        )
        return False

    resp = _retry_rate_limited_request(
        lambda: create_tweet(text, media_id), "tweet creation"
    )
    if _is_success(resp):
        return True
    _log_api_error("tweet creation", resp)

    if not _is_tweet_too_long(resp):
        return False

    log.info("Tweet text is too long; trying the reduced title")
    resp = create_tweet(text_short, media_id)
    if _is_success(resp):
        return True
    _log_api_error("tweet creation with reduced title", resp)

    if not _is_tweet_too_long(resp):
        return False

    log.info("Reduced tweet text is too long; trying the image without text")
    resp = create_tweet("", media_id)
    if not _is_success(resp):
        _log_api_error("tweet creation without text", resp)
        return False
    return True


def upload_media(file_path: str) -> requests.Response:
    ''' uploads media to twitter '''
    with open(file_path, 'rb') as media_file:
        response = requests.post(
            'https://upload.twitter.com/1.1/media/upload.json?media_category=tweet_image',
            auth=oauth,
            files={
                'media': media_file,
            }
        )
    return response


def create_tweet(text: str, media_id: str) -> requests.Response:
    ''' create tweet with media id '''
    response = requests.post(
        'https://api.twitter.com/2/tweets',
        auth=oauth,
        headers={
            'Content-Type': 'application/json',
        }, 
        json={
            'text': text,
            'media': {
                'media_ids': [media_id]
            }
        }
    )
    return response
