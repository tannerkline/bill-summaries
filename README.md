# Legislation Summarizer

One-shot job that summarizes legislation and posts it to social media.

## Social Media
[BANNED](https://www.reddit.com/r/legislation_summary/) on reddit

[@billsummaries](https://twitter.com/billsummaries) on twitter

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

TWITTER_API_KEY=...
TWITTER_API_KEY_SECRET=...
TWITTER_ACCESS_TOKEN=...
TWITTER_ACCESS_SECRET=...
```

Run it manually with the date whose bill activity should be summarized:

```bash
docker compose run --rm app --date 2026-08-14
```

To review output without using any Twitter credentials or making any
social-media requests, add `--debug`:

```bash
docker compose run --rm -T app --date 2026-08-14 --debug
```

The run saves artifacts beneath `output/debug/2026-08-14/` on the host: one
PNG, model summary, exact tweet text, and image text per bill. The `output/`
directory is ignored by Git.

For a daily 9:00 AM run, add this to the crontab of the user that can run
Docker. The escaped percent sign is required by `crontab`.

```cron
0 9 * * * cd /home/tanner/code/bill-summaries && /usr/bin/docker compose run --rm -T app --date "$(date -d yesterday +\%F)" >> /home/tanner/code/bill-summaries/billsummaries.log 2>&1
```

If your account requires `sudo docker`, install that entry in root's crontab
with `sudo crontab -e`; do not rely on an interactive `sudo` password prompt
from cron.

## Data Sources
Legislation data comes from the authenticated [Congress.gov API](https://api.congress.gov/),
rather than browser automation. The application prefers the most recent
official CRS summary; when none exists, it summarizes the latest available
official bill text. Posts state which source was used.

## Machine Learning
Summaries are generated with the local Ollama model `qwen3.6:35b`. The model is
configured with `OLLAMA_MODEL`, and inference is sent to `OLLAMA_BASE_URL`.

## TO DO
 - implement logic for executive order monitoring
 - post to instagram
 - post to linkedin
 - post to facebook
 - post to snapchat
