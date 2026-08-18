# Legislation Summarizer

One-shot job that summarizes legislation and posts it to social media.

## Social Media

[@BillSummaries](https://www.youtube.com/@BillSummaries) on youtube

[BANNED](https://www.reddit.com/r/legislation_summary/) on reddit

[@billsummaries](https://twitter.com/billsummaries) on twitter but API access isn't free anymore so not posting here anymore

I tried to make a facebook page for this as well, however facebook has decided that my phone number is not worthy of recieving verification texts, so I can't get a developer account

## Deployment
The application generates summaries through a locally deployed Ollama model. It
expects the Ollama container and this application to share the external Docker
network `hermes-net` (the network used by the command below).

Start Ollama and download the model:

``` bash
docker run -d \
  --name ollama \
  --restart unless-stopped \
  --network hermes-net \
  -p 0.0.0.0:11434:11434 \
  -v ollama:/root/.ollama \
  -e OLLAMA_HOST=0.0.0.0:11434 \
  -e OLLAMA_CONTEXT_LENGTH=65536 \
  -e OLLAMA_NUM_PARALLEL=1 \
  -e OLLAMA_MAX_LOADED_MODELS=1 \
  -e OLLAMA_KEEP_ALIVE=30m \
  -e OLLAMA_NO_CLOUD=1 \
  -e OLLAMA_FLASH_ATTENTION=1 \
  -e OLLAMA_KV_CACHE_TYPE=q8_0 \
  ollama/ollama:latest

docker exec ollama ollama pull qwen3.6:35b

# build the one-shot job image
docker compose build
```

The defaults are `OLLAMA_BASE_URL=http://ollama:11434`,
`OLLAMA_MODEL=qwen3.6:35b`, a 600-second request timeout, and
`OLLAMA_THINK=false`. Disabling thinking reserves the 1,000 generated-token
budget for the public-facing summary rather than Qwen's internal reasoning.
Override these settings in
your Compose environment if needed. If running `app.py` directly on the Docker
host instead, set `OLLAMA_BASE_URL=http://localhost:11434`.

Create a `.env` file alongside `docker-compose.yml` before deploying. The
Congress API key is passed only to the running container and is never baked
into the application image:

```env
CONGRESS_API_KEY=your-key
# Optional: defaults to 30 seconds
CONGRESS_API_TIMEOUT_SECONDS=30
# Optional: caps raw bill-text fallback before it is sent to Ollama
CONGRESS_BILL_TEXT_MAX_CHARACTERS=100000
# Optional: Federal Register API timeout and Executive Order text cap
FEDERAL_REGISTER_TIMEOUT_SECONDS=30
EXECUTIVE_ORDER_TEXT_MAX_CHARACTERS=100000

TWITTER_API_KEY=...
TWITTER_API_KEY_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...

# Configure these only after creating the corresponding Pages. The posting
# calls remain disabled in app.py until you explicitly uncomment them.
LINKEDIN_ACCESS_TOKEN=...
LINKEDIN_ORGANIZATION_URN=urn:li:organization:...
# A currently supported LinkedIn API version in YYYYMM form.
LINKEDIN_API_VERSION=...

FACEBOOK_PAGE_ID=...
FACEBOOK_PAGE_ACCESS_TOKEN=...
# The Graph API version enabled for your Meta app, for example v25.0.
FACEBOOK_GRAPH_API_VERSION=...

# YouTube's social publisher accepts an existing access token. For recurring
# runs, provide a refresh token together with the OAuth client values.
YOUTUBE_ACCESS_TOKEN=...
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...
# Optional: public (default), private, or unlisted.
YOUTUBE_PRIVACY_STATUS=public
```

Run it manually with the date whose bill activity and Executive Orders should
be summarized. `both` is the default:

```bash
docker compose run --rm app --date 2026-08-14 --source both
```

To run only one document type:

```bash
docker compose run --rm -T app --date 2026-08-14 --source bills
docker compose run --rm -T app --date 2026-08-14 --source executive-orders
```

Executive Orders are selected by Federal Register publication date so the daily
job does not miss orders signed before they are published; the post also shows
their signing date. No separate Federal Register API key is required.

To review output without using any Twitter credentials or making any
social-media requests, add `--debug`:

```bash
docker compose run --rm -T app --date 2026-08-14 --debug
```

The run saves artifacts beneath `output/debug/2026-08-14/` on the host: one
PNG, narrated MP4, model summary, exact tweet text, and image text per document.
Each PNG is a 1080×1920 Bill Summaries card, and its MP4 adds a subtle slow
push-in while an offline Piper neural voice reads the document title and
plain-language summary. It is never posted in debug mode. The default
`en_US-lessac-high` voice model is downloaded during the image build, so no
speech request leaves the container at runtime. The `output/` directory is
ignored by Git.

## Uploading YouTube Shorts

The YouTube publisher follows the same pattern as LinkedIn and Facebook:
it is implemented but disabled by default in `app.py`. It renders the same
portrait MP4 and uploads it with the YouTube Data API. YouTube classifies square
or vertical videos no longer than three minutes as Shorts; there is no special
Shorts API parameter.

Set the same OAuth values you already use to obtain a YouTube API token in
`.env`. A current `YOUTUBE_ACCESS_TOKEN` works for a manual upload. For a
scheduled job, use `YOUTUBE_REFRESH_TOKEN` together with the client ID and
secret so the social publisher refreshes it automatically:

```env
YOUTUBE_ACCESS_TOKEN=...
# Recommended for recurring posts:
YOUTUBE_CLIENT_ID=...
YOUTUBE_CLIENT_SECRET=...
YOUTUBE_REFRESH_TOKEN=...
YOUTUBE_PRIVACY_STATUS=public
```

Remove the comment markers from the `create_youtube_post(...)` block in
`app.py` to enable it during ordinary non-debug runs. Uploads default to
`public`; set `YOUTUBE_PRIVACY_STATUS=private` or `unlisted` when you want to
review a post before it is visible on the channel.

## Enabling LinkedIn and Facebook

The LinkedIn Organization Page and Facebook Page publishers are implemented
but disabled by default. After their credentials above are configured, remove
the comment markers from the corresponding `create_linkedin_post(post_text)`
or `create_facebook_post(post_text)` block in `app.py`. Both publish the full
plain-text bill summary; neither uses the generated PNG.

For a daily 9:00 AM run, add this to the crontab of the user that can run
Docker. The escaped percent sign is required by `crontab`.

```cron
0 9 * * * cd /home/tanner/code/bill-summaries && /usr/bin/docker compose run --rm -T app --date "$(date -d yesterday +\%F)" >> /home/tanner/code/bill-summaries/billsummaries.log 2>&1
```

If your account requires `sudo docker`, install that entry in root's crontab
with `sudo crontab -e`; do not rely on an interactive `sudo` password prompt
from cron.

## Data Sources
Bill data comes from the authenticated [Congress.gov API](https://api.congress.gov/),
rather than browser automation. The application prefers the most recent
official CRS summary; when none exists, it summarizes the latest available
official bill text. Executive Orders come from the public
[Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1),
using its published text (or its abstract only when text is unavailable). Posts
state which source was used.

## Machine Learning
Summaries are generated with the local Ollama model `qwen3.6:35b`. The model is
configured with `OLLAMA_MODEL`, and inference is sent to `OLLAMA_BASE_URL`.

## TO DO
 - post to linkedin
 - post to facebook
