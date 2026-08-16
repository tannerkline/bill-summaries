import requests
import os
import logging
import time
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

def create_post(file_path: str, text: str, text_short: str) -> bool:
    '''
    Creates full twitter post (media upload and tweet) 
    with retries and error handling
    '''
    success = True
    resp = upload_media(file_path)
    if not (200 <= resp.status_code < 300):
        log.info("Bad status code from media upload: %d", resp.status_code)
        # handle rate limiting
        i: int = 0
        while resp.status_code == 429:
            if i > 10:
                log.info("Timed out waiting for rate limiting")
                success = False
                break
            else:
                i += 1
            log.info("Got rate limited; waiting 30 minutes and trying again later")
            time.sleep(60*30)
            resp = upload_media(file_path)

    media_id: str = resp.json().get('media_id_string', '')
    if not media_id:
        log.info("No media ID in request. Upload failed")
        success = False
    
    if not success:
        return success

    resp = create_tweet(text, media_id)
    if not (200 <= resp.status_code < 300):
        log.info("Bad status code from tweet creation: %d", resp.status_code)
        
        # handle rate limiting
        i: int = 0
        while resp.status_code == 429:
            if i > 10:
                log.info("Timed out waiting for rate limiting")
                success = False
                break
            else:
                i += 1
            log.info("Got rate limited; waiting 30 minutes and trying again later")
            time.sleep(60*30)
            resp = create_tweet(text, media_id)

        # check if tweet was too long
        errors: list = resp.json().get('errors', [])
        if len(errors) == 1 and errors[0].get('message').startswith("Your Tweet text is too long"):
                log.info("Tweet too long; trying with reduced title")
                resp = create_tweet(text_short, media_id)
                if not (200 <= resp.status_code < 300):
                    # if tweet is still too long, try with no title
                    errors: list = resp.json().get('errors', [])
                    if len(errors) == 1 and errors[0].get('message').startswith("Your Tweet text is too long"):
                        resp = create_tweet("", media_id)
                        if not (200 <= resp.status_code < 300):
                            log.info("Failed to create no title tweet", resp.status_code)
                    else:
                        log.info("Failed to create short title tweet", resp.status_code)
                        success = False

        # A non-rate-limit HTTP error (such as 401 or 403) previously fell
        # through and was reported as a successful post.
        if not (200 <= resp.status_code < 300):
            success = False

    return success


def upload_media(file_path: str) -> requests.Response:
    ''' uploads media to twitter '''
    response = requests.post(
        'https://upload.twitter.com/1.1/media/upload.json?media_category=tweet_image', 
        auth=oauth,
        files={
            'media': open(file_path, 'rb'),
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
