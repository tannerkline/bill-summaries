import requests
from requests.auth import HTTPBasicAuth
import logging
import os

# logging setup
logging.basicConfig(datefmt='%Y/%m/%d %H:%M:%S', format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

client_id = os.environ.get('REDDIT_CLIENT_ID')
client_secret = os.environ.get('REDDIT_CLIENT_SECRET')
username = os.environ.get('REDDIT_USERNAME')
password = os.environ.get('REDDIT_PASSWORD')

def post_to_reddit(title: str, text: str) -> None:
    ''' makes post to subreddit 
    **deprecated because REDDIT BANNED ME LIKE A WEENIE**
    '''
    # Send a POST request to get the access token
    response = requests.post(
        'https://www.reddit.com/api/v1/access_token', 
        auth=HTTPBasicAuth(client_id, client_secret), 
        data = {
            'grant_type': 'password',
            'username': username,
            'password': password
        }, 
        headers={
            'User-Agent': 'MyAPI/0.0.1'
        }
    )
    if response.status_code != 200:
        log.info(f"Failed to authenticate post. Status code: {response.status_code}")
        return
    access_token = response.json().get('access_token')
    if not access_token:
        log.info(f"Failed to authenticate post. Status code: {response.status_code}")
        return

    # Make the POST request to submit the post
    response = requests.post(
        'https://oauth.reddit.com/api/submit', 
        headers = {
            'User-Agent': 'MyAPI/0.0.1', 
            'Authorization': f'bearer {access_token}'
        }, 
        data = {
            'title': title,
            'text': text,
            'sr': "legislation_summary",
            'kind': 'self',
        }
    )

    if response.status_code == 200:
        log.info("Post submitted successfully!")
    else:
        log.info(f"Failed to submit post. Status code: {response.status_code}")