# Legislation Summarizer

One-shot job that summarizes legislation and posts it to social media.

## Social Media

 - [@BillSummaries](https://www.youtube.com/@BillSummaries) on YouTube
 - [banned](https://www.reddit.com/r/legislation_summary/) on Reddit
 - [@billsummaries](https://twitter.com/billsummaries) on Twitter but API access isn't free anymore so not currently posting here
 - I tried to make a facebook page for this as well, however facebook has decided that my phone number is not worthy of recieving verification texts, so I can't create a developer account
 - I haven't gotten around to hooking it up to LinkedIn
 - TikTok doesn't support fully automated posts like youtube does

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
# Optional: defaults to the current (119th) Congress. Update in 2027.
CONGRESS_NUMBER=119
# Optional: committee_or_later (default), or all to include early-stage bills.
CONGRESS_BILL_FILTER=committee_or_later
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
push-in while an offline Kokoro neural voice reads the document title and
plain-language summary. It is never posted in debug mode. The default
`af_heart` American English voice and the full-quality Kokoro model are downloaded
during the image build, so no speech request leaves the container at runtime.
Narration runs on CPU with no API key or per-video fees, in both debug mode and
YouTube publishing. The `output/` directory is
ignored by Git.

After updating from Piper, rebuild with `docker compose build app`.
Set `KOKORO_VOICE` in `.env` to choose another bundled American English voice,
such as `af_bella` or `am_michael`. Set `KOKORO_SPEED` to a number from `0.5` to
`2.0` (default `1.0`; lower is slower). Voice and speed changes take effect on
the next `docker compose run` without rebuilding. The existing one-second pause
between the introduction and summary is preserved.
For speech, numbered references such as `Calendar No. 629` are expanded to
`Calendar number 629`; displayed text keeps its original wording.
Bill and resolution prefixes before a number are also expanded for narration:

| Prefix | Spoken wording |
| --- | --- |
| `H.R.` / `S.` | House bill / Senate bill |
| `H.Res.` / `S.Res.` | House resolution / Senate resolution |
| `H.J.Res.` / `S.J.Res.` | House joint resolution / Senate joint resolution |
| `H.Con.Res.` / `S.Con.Res.` | House concurrent resolution / Senate concurrent resolution |

These also accept variations in capitalization, spacing, and periods, such as
`H. R. 42` and `HR42`. Rebuild the image after pronunciation code changes.

See the [Kokoro voice list](https://huggingface.co/hexgrad/Kokoro-82M/blob/main/VOICES.md)
for voice options. Local runs outside Docker also need `kokoro-onnx==0.6.1`,
`soundfile==0.13.1`, FFmpeg, and the `kokoro-v1.0.onnx` and `voices-v1.0.bin`
files from the [Kokoro ONNX model release](https://github.com/thewh1teagle/kokoro-onnx/releases/tag/model-files-v1.1).
Point `KOKORO_DATA_DIR` at the directory containing those files.

For a daily 9:00 AM run, add this to the crontab of the user that can run
Docker. The escaped percent sign is required by `crontab`.

```cron
0 9 * * * cd /home/tanner/code/bill-summaries && /usr/bin/docker compose run --rm -T app --date "$(date -d yesterday +\%F)" >> /home/tanner/code/bill-summaries/billsummaries.log 2>&1
```

If your account requires `sudo docker`, install that entry in root's crontab
with `sudo crontab -e`; do not rely on an interactive `sudo` password prompt
from cron.

## Topic Hashtags

Posts choose up to two topic hashtags from `TOPIC_HASHTAGS` in `app.py`, matching
the document title and summary. Topics cover health, education, work, finance,
housing, technology, energy, transportation, agriculture, defense, foreign
affairs, civil rights, and government services. Specific topics take priority
over broad categories. Matching respects word boundaries and accepts hyphenated
phrases, so unrelated words such as "parents" do not trigger a rent/housing tag.
The same selection supplies YouTube description hashtags and video tags.

## Data Sources

By default, bills must have reached full-committee reporting/approval, committee
discharge, or floor consideration before the app summarizes or posts them.
Introductions, referrals, hearings, markups without approval, subcommittee-only
approvals, and calendar placement alone do not qualify. The filter checks action
history through the selected date, so later referrals do not hide earlier
progress. Once a bill qualifies, later updates remain eligible. Executive Orders
are unaffected. This reduces volume but does not impose a daily upload cap.
Skipped bills are logged with their latest action; missing/invalid action data
does not silently bypass the filter. Set `CONGRESS_BILL_FILTER=all` in `.env` to
restore the previous behavior. Debug runs use the same filter as publishing.

Bill data comes from the authenticated [Congress.gov API](https://api.congress.gov/),
rather than browser automation. The application prefers the most recent
official CRS summary; when none exists, it summarizes the latest available
official bill text. Executive Orders come from the public
[Federal Register API](https://www.federalregister.gov/developers/documentation/api/v1),
using its published text (or its abstract only when text is unavailable). Posts
state which source was used.

## Legislative Progress

Congressional posts include a milestone bar on the PNG card (and therefore in
the narrated video), plus a text version in post copy and YouTube descriptions.
Bills follow `Introduced > House > Senate > President > Law`; Senate-originated
measures show the Senate first. The status also identifies committee/floor
consideration, unresolved differences, vetoes, and failed passage. Gold segments
mark recorded milestones; pending segments stay gray, and blocked statuses use
red. This shows procedural progress, not a probability or estimated time to pass.

The bar uses the full, paginated Congress.gov action history through the post's
date. Amendment votes and other procedural votes do not count as bill passage.
Simple resolutions end at their own chamber; concurrent resolutions end with
Congress. Joint resolutions proposing constitutional amendments omit the
president/law steps and identify state ratification as a separate requirement.
Executive Orders keep their signing-date presentation.

Rebuild with `docker compose build app` to include the progress bar in future
runs. Use `--debug` to review cards and videos before publishing.

## Machine Learning
Summaries are generated with the local Ollama model `qwen3.6:35b`. The model is
configured with `OLLAMA_MODEL`, and inference is sent to `OLLAMA_BASE_URL`.
