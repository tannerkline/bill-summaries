"""One-shot legislation summarization job."""

import argparse
from datetime import date, datetime
import logging
from pathlib import Path
import re
import time

from models.ollama import OllamaGenerationError, generate_summary
from util.congress_api import CongressApiError, fetch_bills_with_latest_action_on


logging.basicConfig(datefmt="%Y/%m/%d %H:%M:%S", format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

prompt_rubric: str = """
Use the following %s to write the post's summary.
###### START SUMMARY
%s
###### END SUMMARY
Write one plain-text paragraph of at most 90 words in simple, non-technical
language. Begin immediately with the bill's substantive action or effect (for
example, "Requires ICE to ..."). Do not use an introduction, heading, title,
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
) -> None:
    """Save reviewable local outputs for one bill without contacting Twitter."""
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
    text_to_image(image_text, str(output_directory / f"{file_stem}.png"))


def summarize_date(target_date: date, debug: bool = False) -> int:
    """Fetch, summarize, and optionally post bills for one day.

    Debug runs generate all local artifacts but make no social-media requests.
    """
    date_string = target_date.isoformat()
    log.info("Starting one-shot run for date %s", date_string)
    try:
        bills = fetch_bills_with_latest_action_on(target_date)
    except CongressApiError as error:
        log.exception("Congress.gov API request failed")
        log.error("One-shot run failed: %s", error)
        return 1

    if not bills:
        log.info("No eligible bills with a summary or official text on %s", date_string)
        return 0

    # These dependencies are only needed when an API call actually returns a bill.
    from util.helpers import clean_html_string
    from util.text_to_image import text_to_image
    if not debug:
        from social.twitter import create_post

    successful_posts = 0
    debug_outputs = 0
    debug_directory = Path("output") / "debug" / date_string
    if debug:
        log.info(
            "Debug mode enabled: social-media posting is disabled; artifacts will be saved to %s",
            debug_directory,
        )
    for bill in bills:
        latest_summary = clean_html_string(bill.latest_summary)
        log.info(
            "New bill found: %s (%s length %d). Starting Ollama inference...",
            bill.legislation_number,
            bill.summary_source,
            len(latest_summary),
        )

        start = time.perf_counter()
        try:
            response = generate_summary(
                prompt_rubric % (bill.summary_source, latest_summary),
                max_tokens=SUMMARY_MAX_TOKENS,
            )
        except OllamaGenerationError as error:
            log.exception("Ollama inference failed for %s", bill.legislation_number)
            log.error("One-shot run failed: %s", error)
            return 1
        response = clean_summary_for_post(response)
        log.info("Ollama inference complete: time=%ss", time.perf_counter() - start)

        post_title = title_rubric % (
            bill.legislation_number,
            bill.latest_action,
            bill.latest_action_date,
            bill.url,
            bill.title,
            bill.sponsor_party.lower(),
        )
        post_title_short = title_rubric_short % (
            bill.legislation_number,
            bill.latest_action,
            bill.latest_action_date,
            bill.url,
            bill.sponsor_party.lower(),
        )
        post_text = post_rubric % (
            bill.legislation_number,
            bill.latest_action,
            bill.latest_action_date,
            bill.title,
            bill.congress,
            bill.sponsor,
            bill.sponsor_party,
            bill.date_of_introduction,
            bill.summary_source,
            response,
        )

        if debug:
            _write_debug_artifacts(
                debug_directory,
                bill.legislation_number,
                response,
                post_title,
                post_text,
                text_to_image,
            )
            debug_outputs += 1
            log.info("Saved debug artifacts for %s to %s", bill.legislation_number, debug_directory)
        else:
            with open(f"./{date_string}.txt", "a", encoding="utf-8") as cache_file:
                cache_file.write(f"{post_text}\n\n\n")

            image_file = "./upload.png"
            text_to_image(post_text, image_file)
            if create_post(image_file, post_title, post_title_short):
                successful_posts += 1
                log.info("Successfully created tweet for %s", bill.legislation_number)
            else:
                log.warning("Failed to create tweet for %s", bill.legislation_number)

    if debug:
        log.info(
            "Debug one-shot run complete: processed %d bill(s), wrote artifacts for %d",
            len(bills),
            debug_outputs,
        )
    else:
        log.info(
            "One-shot run complete: processed %d bill(s), posted %d",
            len(bills),
            successful_posts,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Summarize and post bills whose latest action occurred on one date."
    )
    parser.add_argument("--date", required=True, type=parse_date, help="YYYY-MM-DD")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Save local artifacts and skip all social-media requests.",
    )
    arguments = parser.parse_args()
    return summarize_date(arguments.date, debug=arguments.debug)


if __name__ == "__main__":
    raise SystemExit(main())
