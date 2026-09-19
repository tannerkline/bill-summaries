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
MAX_TOPIC_HASHTAGS = 5

# Match subject words in the official title or plain-language summary.
# Specific topics precede broad fallbacks; each post gets at most two topic tags.
# Keep terms lowercase and list inflections explicitly to avoid substring matches.
TOPIC_HASHTAGS = (
    # Health and family policy.
    (("vaccine", "vaccines", "vaccination", "vaccinations", "immunization", "immunizations"), "#Vaccines"),
    (("mental health", "behavioral health", "suicide prevention", "psychiatric"), "#MentalHealth"),
    (("medicare", "medicaid", "chip coverage", "children's health insurance"), "#MedicareMedicaid"),
    (("prescription drugs", "drug pricing", "drug prices", "pharmaceutical", "pharmaceuticals", "insulin"), "#PrescriptionDrugs"),
    (("opioid", "opioids", "fentanyl"), "#OpioidCrisis"),
    (("overdose", "overdoses", "substance use", "addiction treatment", "addiction recovery"), "#AddictionRecovery"),
    (("maternal health", "pregnancy", "pregnant", "postpartum", "prenatal"), "#MaternalHealth"),
    (("reproductive health", "reproductive rights", "abortion", "contraception", "contraceptives", "ivf", "in vitro fertilization"), "#ReproductiveHealth"),
    (("child care", "childcare", "daycare", "day care", "early childhood", "head start"), "#Childcare"),
    (("child welfare", "foster care", "child abuse", "child protection", "adoption", "adoptions"), "#ChildWelfare"),
    (("disability", "disabilities", "accessibility", "disabled", "special education"), "#DisabilityRights"),
    (("social security", "retirement benefits", "pension", "pensions", "retirement savings"), "#Retirement"),
    (("elder care", "elder abuse", "aging adults", "older adults", "nursing home", "nursing homes", "long term care"), "#SeniorCare"),
    (("food assistance", "nutrition assistance", "food stamps", "school meals", "school lunches", "wic benefits", "snap benefits", "food insecurity", "hunger"), "#FoodAssistance"),
    # Education, work, and business.
    (("student loan", "student loans", "student debt", "college tuition", "pell grant", "pell grants", "higher education"), "#HigherEducation"),
    (("vocational", "apprenticeship", "apprenticeships", "job training", "workforce development", "career training"), "#WorkforceDevelopment"),
    (("minimum wage", "wages", "overtime", "collective bargaining", "labor union", "labor unions", "workers' rights", "worker protections", "workplace safety"), "#WorkersRights"),
    (("paid leave", "family leave", "medical leave", "parental leave", "sick leave"), "#PaidLeave"),
    (("small business", "small businesses", "entrepreneur", "entrepreneurs", "entrepreneurship", "small business administration"), "#SmallBusiness"),
    (("antitrust", "monopoly", "monopolies", "anticompetitive", "competition law", "price fixing"), "#Antitrust"),
    (("consumer protection", "consumer protections", "consumer fraud", "scams", "junk fees", "identity theft", "deceptive practices"), "#ConsumerProtection"),
    # Money, taxes, and housing.
    (("bank", "banks", "banking", "credit union", "credit unions", "financial institution", "financial institutions", "deposit insurance", "lending"), "#Banking"),
    (("securities", "capital markets", "stock market", "investment adviser", "investment advisers", "investor protection", "asset backed"), "#FinancialMarkets"),
    (("cryptocurrency", "cryptocurrencies", "crypto", "digital assets", "stablecoin", "stablecoins", "blockchain"), "#CryptoPolicy"),
    (("tax", "taxes", "taxation", "taxpayer", "taxpayers", "tax credit", "tax credits", "internal revenue"), "#TaxPolicy"),
    (("appropriation", "appropriations", "federal budget", "government spending", "debt ceiling", "national debt", "budget deficit", "budget deficits"), "#FederalBudget"),
    (("affordable housing", "public housing", "housing voucher", "housing vouchers", "homeless", "homelessness", "section 8"), "#AffordableHousing"),
    (("mortgage", "mortgages", "homebuyer", "homebuyers", "homeownership", "foreclosure", "foreclosures"), "#Homeownership"),
    # Technology and research.
    (("artificial intelligence", "machine learning", "generative ai", "ai model", "ai models", "deepfake", "deepfakes"), "#ArtificialIntelligence"),
    (("cybersecurity", "cyber security", "cyberattack", "cyberattacks", "ransomware", "data breach", "data breaches"), "#Cybersecurity"),
    (("data privacy", "personal data", "personal information", "data protection", "biometric", "biometrics", "surveillance"), "#DataPrivacy"),
    (("broadband", "internet access", "rural internet", "telecommunications", "spectrum auction", "spectrum auctions"), "#Broadband"),
    (("semiconductor", "semiconductors", "microchip", "microchips", "chip manufacturing"), "#Semiconductors"),
    (("space exploration", "spaceflight", "nasa", "satellite", "satellites", "commercial space", "space station"), "#SpacePolicy"),
    (("scientific research", "national science foundation", "research funding", "national laboratory", "national laboratories", "quantum"), "#SciencePolicy"),
    # Energy, natural resources, and disasters.
    (("renewable energy", "solar energy", "solar power", "wind energy", "wind power", "clean energy", "geothermal"), "#CleanEnergy"),
    (("nuclear energy", "nuclear power", "nuclear reactor", "nuclear reactors", "nuclear waste"), "#NuclearEnergy"),
    (("oil", "natural gas", "petroleum", "pipeline", "pipelines", "drilling", "coal"), "#EnergyPolicy"),
    (("electric grid", "power grid", "electricity", "transmission lines", "energy storage", "utility rates"), "#ElectricGrid"),
    (("drinking water", "clean water", "water quality", "wastewater", "water infrastructure", "water supply", "water conservation", "pfas"), "#WaterPolicy"),
    (("wildfire", "wildfires", "forest fire", "forest fires", "forest management", "forestry"), "#Forestry"),
    (("disaster relief", "disaster recovery", "disaster preparedness", "fema", "flood", "floods", "flooding", "hurricane", "hurricanes", "earthquake", "earthquakes"), "#DisasterRelief"),
    (("national park", "national parks", "public lands", "wildlife", "endangered species", "habitat", "habitats", "biodiversity"), "#Conservation"),
    (("animal welfare", "animal cruelty", "animal testing", "animal protection"), "#AnimalWelfare"),
    # Transportation, farming, and manufacturing.
    (("aviation", "airline", "airlines", "airport", "airports", "air traffic", "faa"), "#Aviation"),
    (("rail", "railroad", "railroads", "railway", "railways", "amtrak", "passenger rail", "freight rail"), "#RailPolicy"),
    (("public transit", "public transportation", "bus service", "bus services", "mass transit"), "#PublicTransit"),
    (("road safety", "traffic safety", "vehicle safety", "drunk driving", "impaired driving", "seat belt", "seat belts"), "#RoadSafety"),
    (("maritime", "shipping", "seaport", "seaports", "port infrastructure", "merchant marine", "shipbuilding"), "#MaritimePolicy"),
    (("agriculture", "agricultural", "farm", "farms", "farmer", "farmers", "farming", "livestock", "crop", "crops", "crop insurance"), "#Agriculture"),
    (("food safety", "food labeling", "foodborne", "meat inspection", "food inspection"), "#FoodSafety"),
    (("rural development", "rural communities", "rural economy", "rural infrastructure"), "#RuralDevelopment"),
    (("manufacturing", "manufacturer", "manufacturers", "supply chain", "supply chains", "domestic production", "made in america"), "#Manufacturing"),
    # Defense, foreign affairs, and migration.
    (("veteran", "veterans", "veterans affairs", "veterans benefits", "gi bill", "service connected"), "#Veterans"),
    (("military", "defense", "armed forces", "servicemember", "servicemembers", "service members", "national guard", "pentagon", "military readiness"), "#NationalSecurity"),
    (("foreign aid", "foreign assistance", "humanitarian aid", "humanitarian assistance", "international development", "usaid"), "#ForeignAid"),
    (("sanction", "sanctions", "export controls", "asset freeze", "asset freezes"), "#Sanctions"),
    (("tariff", "tariffs", "trade agreement", "trade agreements", "international trade", "imports", "exports", "customs duties"), "#TradePolicy"),
    (("diplomacy", "diplomatic", "foreign relations", "foreign policy", "embassy", "embassies", "nato", "treaty", "treaties"), "#ForeignPolicy"),
    (("immigration", "immigrant", "immigrants", "asylum", "visa", "visas", "deportation", "deportations", "naturalization", "border security", "border patrol", "ice detention", "ice agents", "immigration and customs enforcement"), "#Immigration"),
    (("refugee", "refugees", "resettlement", "displaced persons"), "#Refugees"),
    # Rights, justice, and government.
    (("voting rights", "voter registration", "ballot access", "voter suppression", "suffrage"), "#VotingRights"),
    (("voting", "voter", "voters", "election", "elections", "ballot", "ballots", "redistricting", "campaign finance"), "#Elections"),
    (("civil rights", "discrimination", "equal protection", "equal rights", "racial equality", "religious freedom", "free speech"), "#CivilRights"),
    (("tribal", "tribes", "tribe", "native american", "native americans", "alaska native", "alaska natives", "indian affairs", "indian health service"), "#TribalAffairs"),
    (("firearm", "firearms", "gun", "guns", "gun violence", "second amendment", "ammunition"), "#GunPolicy"),
    (("human trafficking", "sex trafficking", "forced labor", "trafficking victims"), "#HumanTrafficking"),
    (("domestic violence", "sexual assault", "stalking", "victim services", "victims of crime"), "#VictimSupport"),
    (("sentencing", "prison", "prisons", "incarceration", "parole", "probation", "reentry", "expungement"), "#JusticeReform"),
    (("police", "policing", "law enforcement", "law enforcement officers", "body cameras"), "#LawEnforcement"),
    (("cannabis", "marijuana", "hemp"), "#CannabisPolicy"),
    (("government transparency", "public records", "freedom of information", "foia", "whistleblower", "whistleblowers", "inspector general", "government ethics", "corruption"), "#GovernmentAccountability"),
    (("federal employee", "federal employees", "federal workforce", "civil service", "government employees"), "#FederalWorkforce"),
    (("postal service", "post office", "post offices", "usps", "mail delivery", "postal facility"), "#PostalService"),
    # Broad fallbacks follow the more specific subjects above.
    (("health", "healthcare", "health care", "hospital", "hospitals", "patient", "patients", "medical care", "nurse", "nurses", "physician", "physicians"), "#Healthcare"),
    (("education", "school", "schools", "student", "students", "teacher", "teachers", "college", "colleges", "university", "universities"), "#Education"),
    (("climate", "emission", "emissions", "greenhouse gas", "greenhouse gases", "carbon dioxide", "global warming"), "#ClimatePolicy"),
    (("environment", "environmental", "pollution", "clean air", "air quality", "toxic substances", "hazardous waste"), "#Environment"),
    (("energy", "fuel", "fuels", "electric vehicle", "electric vehicles"), "#Energy"),
    (("economy", "economic", "inflation", "recession", "unemployment", "treasury", "federal reserve"), "#Economy"),
    (("crime", "crimes", "criminal", "criminal justice", "court", "courts", "judicial", "judiciary"), "#CriminalJustice"),
    (("housing", "rent", "rents", "rental", "rentals", "tenant", "tenants", "landlord", "landlords", "zoning"), "#Housing"),
    (("technology", "technologies", "internet", "software", "digital infrastructure"), "#Technology"),
    (("infrastructure", "transportation", "transit", "bridge", "bridges", "road", "roads", "highway", "highways", "trucking", "motor vehicle", "motor vehicles"), "#Infrastructure"),
)

# Compile once; spaces in phrases also accept hyphens and line breaks.
_TOPIC_PATTERNS = tuple(
    (
        re.compile(
            r"(?<!\w)(?:"
            + "|".join(re.escape(term).replace(r"\ ", r"[\s\-\u2010-\u2015]+") for term in terms)
            + r")(?!\w)"
        ),
        hashtag,
    )
    for terms, hashtag in TOPIC_HASHTAGS
)


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


def _document_hashtags(document, summary: str) -> list[str]:
    """Return a concise, document-specific group of discovery hashtags."""
    if isinstance(document, CongressBill):
        hashtags = [
            "#Politics",
            "#Congress",
            "#Bill",
            "#Law",
            "#Legislation",
            "#PublicPolicy",
            "#USPolitics",
        ]
    elif isinstance(document, ExecutiveOrder):
        hashtags = [
            "#Politics",
            "#ExecutiveOrder",
            "#WhiteHouse",
            "#FederalRegister",
            "#Law",
            "#PublicPolicy",
            "#USPolitics",
        ]
    else:
        raise TypeError(f"Unsupported document type: {type(document).__name__}")

    searchable_text = f"{document.title} {summary}".casefold()
    base_hashtag_count = len(hashtags)
    for pattern, hashtag in _TOPIC_PATTERNS:
        if pattern.search(searchable_text):
            hashtags.append(hashtag)
        if len(hashtags) == base_hashtag_count + MAX_TOPIC_HASHTAGS:
            break
    return hashtags


def _youtube_metadata(document, image_text: str) -> tuple[str, str, list[str]]:
    """Build the YouTube title, description, and tags for a source document."""
    if isinstance(document, CongressBill):
        identifier = document.legislation_number
    elif isinstance(document, ExecutiveOrder):
        identifier = document.executive_order_number
    else:
        raise TypeError(f"Unsupported document type: {type(document).__name__}")

    hashtags = _document_hashtags(document, image_text)
    tags = [hashtag.lstrip("#") for hashtag in hashtags]
    title = f"{identifier}: {document.title}"
    description = (
        f"{image_text}\n\nOfficial source: {document.url}\n\n"
        f"#Shorts {' '.join(hashtags)}"
    )
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
        hashtags = " ".join(_document_hashtags(document, summary))
        tweet_text = (
            f"{document.legislation_number} {document.latest_action} on "
            f"{document.latest_action_date} ({document.url})\n{document.title}\n\n{hashtags}"
        )
        tweet_text_short = (
            f"{document.legislation_number} {document.latest_action} on "
            f"{document.latest_action_date} ({document.url})\n\n{hashtags}"
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
        hashtags = " ".join(_document_hashtags(document, summary))
        tweet_text = (
            f"{document.executive_order_number} signed on {document.signing_date} "
            f"({document.url})\n{document.title}\n\n"
            f"{hashtags}"
        )
        tweet_text_short = (
            f"{document.executive_order_number} signed on {document.signing_date} "
            f"({document.url})\n{hashtags}"
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
    stays focused on the latest action, title, and plain-language summary.
    """
    if isinstance(document, CongressBill):
        action = document.latest_action.rstrip(". ")
        action_date = document.latest_action_date.strftime("%B %d, %Y").replace(
            " 0", " "
        )
        introduction = (
            f"{document.legislation_number}. Latest action: {action}. "
            f"On {action_date}."
        )
    elif isinstance(document, ExecutiveOrder):
        signing_date = document.signing_date.strftime("%B %d, %Y").replace(" 0", " ")
        introduction = f"{document.executive_order_number}. Signed on {signing_date}."
    else:
        raise TypeError(f"Unsupported document type: {type(document).__name__}")
    title = document.title.rstrip(". ")
    return f"{introduction} {title}.{NARRATION_PAUSE_MARKER}{summary}"


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
