"""One-shot legislation summarization job."""

import argparse
from datetime import date, datetime
import logging
from pathlib import Path
import re
import time
from typing import Optional

from models.ollama import OllamaGenerationError, generate_summary
from util.congress_api import CongressApiError, CongressBill, fetch_bills_with_latest_action_on
from util.federal_register import (
    ExecutiveOrder,
    FederalRegisterApiError,
    fetch_executive_orders_published_on,
)
from util.debug_video import NARRATION_PAUSE_MARKER


logging.basicConfig(datefmt="%Y/%m/%d %H:%M:%S", format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

prompt_rubric: str = """
Use the following %s to write the post's summary.
###### START SUMMARY
%s
###### END SUMMARY
Write one plain-text paragraph of at most 90 words in simple, non-technical
language. Begin immediately with the document's substantive action or effect
(for example, "Requires ICE to ..."). Do not use an introduction, heading, title,
closing, Markdown, bullets, numbering, asterisks, hashtags, or quotation marks.
Output only the summary paragraph.
""".strip()

title_rubric: str = "%s %s on %s (%s)\n%s\n\n#politics #bill #law #congress #%s"
title_rubric_short: str = "%s %s on %s (%s)\n#politics #bill #law #congress #%s"
post_rubric: str = """
%s %s on %s

%s

%s, Sponsored by %s (%s), Introduced on %s

Source: %s

Summary:

%s
""".strip()

SUMMARY_MAX_WORDS = 90
SUMMARY_MAX_TOKENS = 220
SOURCE_CHOICES = ("both", "bills", "executive-orders")


def parse_date(value: str) -> date:
    """Parse a command-line ISO date for argparse."""
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError("date must use YYYY-MM-DD") from error


def _debug_file_stem(legislation_number: str) -> str:
    """Make a stable, safe filename component from a bill number."""
    return re.sub(r"[^a-z0-9]+", "-", legislation_number.lower()).strip("-")


def _truncate_to_words(text: str, maximum_words: int) -> str:
    """Limit text to whole words, preferring a complete sentence when possible."""
    words = text.split()
    if len(words) <= maximum_words:
        return text

    shortened = " ".join(words[:maximum_words])
    last_sentence_end = max(shortened.rfind("."), shortened.rfind("!"), shortened.rfind("?"))
    if last_sentence_end >= len(shortened) // 2:
        return shortened[: last_sentence_end + 1]
    return f"{shortened.rstrip('.,;:')}…"


def clean_summary_for_post(summary: str) -> str:
    """Enforce concise plain text when a model does not follow the prompt exactly."""
    text = summary.replace("\r\n", "\n").replace("\r", "\n")
    # Convert the small, common subset of Markdown that a model may still emit.
    text = re.sub(r"!?(?:\[([^\]]+)\]\([^)]+\))", r"\1", text)
    text = re.sub(r"^\s{0,3}#{1,6}\s*", "", text, flags=re.MULTILINE)
    text = re.sub(r"^\s*(?:[-*+] |\d+[.)] )", "", text, flags=re.MULTILINE)
    text = text.replace("**", "").replace("__", "").replace("`", "")
    text = re.sub(r"\s+", " ", text).strip()
    # Remove only canned lead-ins, while leaving substantive first sentences intact.
    text = re.sub(
        r"^(?:here(?:'s| is)|below is|the following is)\b[^:]{0,160}:\s*",
        "",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"^summary:\s*", "", text, flags=re.IGNORECASE)
    return _truncate_to_words(text, SUMMARY_MAX_WORDS)


def _write_debug_artifacts(
    output_directory: Path,
    legislation_number: str,
    summary: str,
    tweet_text: str,
    image_text: str,
    text_to_image,
    create_narrated_video,
    narration: Optional[str] = None,
) -> Path:
    """Save reviewable local outputs for one document without posting it."""
    file_stem = _debug_file_stem(legislation_number)
    output_directory.mkdir(parents=True, exist_ok=True)

    (output_directory / f"{file_stem}-summary.txt").write_text(
        f"{summary}\n", encoding="utf-8"
    )
    (output_directory / f"{file_stem}-tweet.txt").write_text(
        f"{tweet_text}\n", encoding="utf-8"
    )
    (output_directory / f"{file_stem}-image-text.txt").write_text(
        f"{image_text}\n", encoding="utf-8"
    )
    if narration is not None:
        readable_narration = narration.replace(
            NARRATION_PAUSE_MARKER, "\n\n[one-second pause]\n\n"
        )
        (output_directory / f"{file_stem}-narration.txt").write_text(
            f"{readable_narration}\n",
            encoding="utf-8",
        )
    image_path = output_directory / f"{file_stem}.png"
    video_path = output_directory / f"{file_stem}.mp4"
    text_to_image(image_text, str(image_path))
    create_narrated_video(image_path, narration or image_text, video_path)
    return video_path


def _youtube_metadata(document, image_text: str) -> tuple[str, str, list[str]]:
    """Build the YouTube title, description, and tags for a source document."""
    if isinstance(document, CongressBill):
        identifier = document.legislation_number
        tags = ["congress", "legislation", "politics", "news"]
    elif isinstance(document, ExecutiveOrder):
        identifier = document.executive_order_number
        tags = ["executive order", "politics", "news"]
    else:
        raise TypeError(f"Unsupported document type: {type(document).__name__}")

    title = f"{identifier}: {document.title}"
    description = f"{image_text}\n\nOfficial source: {document.url}\n\n#Shorts"
    return title, description, tags


def _fetch_documents(target_date: date, source: str) -> tuple[list, list[str]]:
    """Fetch requested source types, allowing the other source to continue on error."""
    documents = []
    failures = []
    if source in ("both", "bills"):
        try:
            documents.extend(fetch_bills_with_latest_action_on(target_date))
        except CongressApiError as error:
            failures.append(f"Congress.gov: {error}")
            log.error("Congress.gov source failed: %s", error)

    if source in ("both", "executive-orders"):
        try:
            documents.extend(fetch_executive_orders_published_on(target_date))
        except FederalRegisterApiError as error:
            failures.append(f"Federal Register: {error}")
            log.error("Federal Register source failed: %s", error)

    return documents, failures


def _post_copy(document, summary: str) -> tuple[str, str, str]:
    """Build platform and image text appropriate for either document type."""
    if isinstance(document, CongressBill):
        tweet_text = title_rubric % (
            document.legislation_number,
            document.latest_action,
            document.latest_action_date,
            document.url,
            document.title,
            document.sponsor_party.lower(),
        )
        tweet_text_short = title_rubric_short % (
            document.legislation_number,
            document.latest_action,
            document.latest_action_date,
            document.url,
            document.sponsor_party.lower(),
        )
        image_text = post_rubric % (
            document.legislation_number,
            document.latest_action,
            document.latest_action_date,
            document.title,
            document.congress,
            document.sponsor,
            document.sponsor_party,
            document.date_of_introduction,
            document.summary_source,
            summary,
        )
        return tweet_text, tweet_text_short, image_text

    if isinstance(document, ExecutiveOrder):
        tweet_text = (
            f"{document.executive_order_number} signed on {document.signing_date} "
            f"({document.url})\n{document.title}\n\n"
            "#politics #executiveorder #president"
        )
        tweet_text_short = (
            f"{document.executive_order_number} signed on {document.signing_date} "
            f"({document.url})\n#politics #executiveorder #president"
        )
        image_text = (
            f"{document.executive_order_number} signed on {document.signing_date}\n\n"
            f"{document.title}\n\n"
            f"Published in the Federal Register on {document.publication_date}\n\n"
            f"Source: {document.text_source}\n\n"
            f"Summary:\n\n{summary}"
        )
        return tweet_text, tweet_text_short, image_text

    raise TypeError(f"Unsupported document type: {type(document).__name__}")


def _narration_copy(document, summary: str) -> str:
    """Make spoken copy that leads with the document, then its real-world effect.

    Visual cards retain a small source attribution, while descriptions retain
    the official URL. Narrating those publishing details makes a Short feel
    slower without helping its viewer understand the action, so the voiceover
    stays focused on the title and plain-language summary.
    """
    if isinstance(document, CongressBill):
        identifier = document.legislation_number
    elif isinstance(document, ExecutiveOrder):
        identifier = document.executive_order_number
    else:
        raise TypeError(f"Unsupported document type: {type(document).__name__}")
    title = document.title.rstrip(". ")
    return f"{identifier}. {title}.{NARRATION_PAUSE_MARKER}{summary}"


def _document_fields(document) -> tuple[str, str, str]:
    """Return identifier, source text, and its label for either document type."""
    if isinstance(document, CongressBill):
        return (
            document.legislation_number,
            document.latest_summary,
            document.summary_source,
        )
    if isinstance(document, ExecutiveOrder):
        return document.executive_order_number, document.text, document.text_source
    raise TypeError(f"Unsupported document type: {type(document).__name__}")


def summarize_date(
    target_date: date,
    debug: bool = False,
    source: str = "both",
) -> int:
    """Fetch, summarize, and optionally post selected document sources for one day.

    Debug runs generate all local artifacts but make no social-media requests.
    """
    date_string = target_date.isoformat()
    log.info("Starting one-shot run for date %s (source=%s)", date_string, source)
    documents, source_failures = _fetch_documents(target_date, source)

    if not documents:
        if source_failures:
            log.error("One-shot run failed: no requested source completed successfully")
            return 1
        log.info("No eligible documents found on %s for source=%s", date_string, source)
        return 0

    # These dependencies are only needed when an API call actually returns a bill.
    from util.helpers import clean_html_string
    from util.text_to_image import text_to_image
    if debug:
        from util.debug_video import create_narrated_video
    if not debug:
        from social.facebook import create_post as create_facebook_post
        from social.linkedin import create_post as create_linkedin_post
        from social.twitter import create_post as create_twitter_post
        from social.youtube import create_post as create_youtube_post
        from util.debug_video import create_narrated_video

    successful_posts = 0
    debug_outputs = 0
    debug_directory = Path("output") / "debug" / date_string
    if debug:
        log.info(
            "Debug mode enabled: social-media posting is disabled; artifacts will be saved to %s",
            debug_directory,
        )
    for document in documents:
        document_identifier, source_text, source_label = _document_fields(document)
        source_text = clean_html_string(source_text)
        log.info(
            "New document found: %s (%s length %d). Starting Ollama inference...",
            document_identifier,
            source_label,
            len(source_text),
        )

        start = time.perf_counter()
        try:
            response = generate_summary(
                prompt_rubric % (source_label, source_text),
                max_tokens=SUMMARY_MAX_TOKENS,
            )
        except OllamaGenerationError as error:
            log.exception("Ollama inference failed for %s", document_identifier)
            log.error("One-shot run failed: %s", error)
            return 1
        response = clean_summary_for_post(response)
        log.info("Ollama inference complete: time=%ss", time.perf_counter() - start)

        post_title, post_title_short, post_text = _post_copy(document, response)
        narration = _narration_copy(document, response)

        if debug:
            _write_debug_artifacts(
                debug_directory,
                document_identifier,
                response,
                post_title,
                post_text,
                text_to_image,
                create_narrated_video,
                narration=narration,
            )
            debug_outputs += 1
            log.info("Saved debug artifacts for %s to %s", document_identifier, debug_directory)
        else:
            with open(f"./{date_string}.txt", "a", encoding="utf-8") as cache_file:
                cache_file.write(f"{post_text}\n\n\n")

            # image_file = "./upload.png"
            # text_to_image(post_text, image_file)
            # if create_twitter_post(image_file, post_title, post_title_short):
            #     successful_posts += 1
            #     log.info("Successfully created tweet for %s", document_identifier)
            # else:
            #     log.warning("Failed to create tweet for %s", document_identifier)

            youtube_image_file = "./youtube-upload.png"
            youtube_video_file = "./youtube-upload.mp4"
            text_to_image(post_text, youtube_image_file)
            create_narrated_video(
                Path(youtube_image_file), narration, Path(youtube_video_file)
            )
            youtube_title, youtube_description, youtube_tags = _youtube_metadata(
                document, post_text
            )
            if create_youtube_post(
                youtube_video_file, youtube_title, youtube_description, youtube_tags
            ):
                successful_posts += 1
                log.info("Successfully uploaded YouTube Short for %s", document_identifier)
            else:
                log.warning("Failed to upload YouTube Short for %s", document_identifier)

            # if create_linkedin_post(post_text):
            #     log.info("Successfully created LinkedIn post for %s", document_identifier)
            # else:
            #     log.warning("Failed to create LinkedIn post for %s", document_identifier)

            # if create_facebook_post(post_text):
            #     log.info("Successfully created Facebook post for %s", document_identifier)
            # else:
            #     log.warning("Failed to create Facebook post for %s", document_identifier)

    if debug:
        log.info(
            "Debug one-shot run complete: processed %d document(s), wrote artifacts for %d",
            len(documents),
            debug_outputs,
        )
    else:
        log.info(
            "One-shot run complete: processed %d document(s), posted %d",
            len(documents),
            successful_posts,
        )
    return 1 if source_failures else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize and post bills and Executive Orders for one date."
    )
    parser.add_argument("--date", required=True, type=parse_date, help="YYYY-MM-DD")
    parser.add_argument(
        "--source",
        choices=SOURCE_CHOICES,
        default="both",
        help="Document source to process; defaults to both.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save local artifacts and skip all social-media requests.",
    )
    arguments = parser.parse_args()
    return summarize_date(arguments.date, debug=arguments.debug, source=arguments.source)


if __name__ == "__main__":
    raise SystemExit(main())
