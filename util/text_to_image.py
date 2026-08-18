"""Render portrait civic-brief cards for social-video posts.

The source copy deliberately contains every useful detail for a post and a
video description. A social card needs a different treatment: it should make
the document, its context, and the takeaway understandable at a glance. This
module extracts those pieces from the existing post copy and lays them out as a
9:16 card suitable for Shorts, TikTok, and Reels.
"""

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterable

from PIL import Image, ImageDraw, ImageFilter, ImageFont


IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1920
IMAGE_MARGIN = 64
CARD_LEFT = 48
CARD_RIGHT = IMAGE_WIDTH - CARD_LEFT
FONT_PATH = "/usr/src/app/fonts/DejaVuSerif.ttf"
LOCAL_FONT_PATH = Path(__file__).resolve().parents[1] / "fonts" / "DejaVuSerif.ttf"

INK = "#10243A"
PAPER = "#F7F3EA"
PAPER_MUTED = "#DDE4E8"
GOLD = "#E8B55B"
SKY = "#9CC9DC"
MUTED_SKY = "#B6CBD7"


@dataclass(frozen=True)
class StoryCard:
    """The short, scannable pieces of a source document shown on the card."""

    category: str
    identifier: str
    event: str
    title: str
    source: str
    summary: str


def _font(size: int) -> ImageFont.FreeTypeFont:
    """Load the bundled font both in Docker and during local test runs."""
    font_path = Path(FONT_PATH)
    if not font_path.is_file():
        font_path = LOCAL_FONT_PATH
    return ImageFont.truetype(str(font_path), size)


def _wrap_line(
    draw: ImageDraw.ImageDraw,
    line: str,
    font: ImageFont.FreeTypeFont,
    maximum_width: int,
) -> list[str]:
    """Wrap a line by rendered width, including unbroken long strings."""
    if not line:
        return [""]

    lines: list[str] = []
    current_line = ""
    for word in line.split():
        candidate = f"{current_line} {word}".strip()
        if not current_line or draw.textlength(candidate, font=font) <= maximum_width:
            current_line = candidate
            continue

        lines.append(current_line)
        current_line = word
        while draw.textlength(current_line, font=font) > maximum_width:
            split_at = len(current_line) - 1
            while split_at > 1 and draw.textlength(
                current_line[:split_at], font=font
            ) > maximum_width:
                split_at -= 1
            lines.append(current_line[:split_at])
            current_line = current_line[split_at:]

    if current_line:
        lines.append(current_line)
    return lines


def _wrapped_lines(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    maximum_width: int,
) -> list[str]:
    lines: list[str] = []
    for line in text.split("\n"):
        lines.extend(_wrap_line(draw, line, font, maximum_width))
    return lines


def _line_height(font: ImageFont.FreeTypeFont) -> int:
    bbox = font.getbbox("Ag")
    return bbox[3] - bbox[1]


def _fit_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    maximum_width: int,
    maximum_height: int,
    sizes: Iterable[int],
    line_spacing_ratio: float,
) -> tuple[ImageFont.FreeTypeFont, list[str], int, int]:
    """Find the largest font size that fits text in a bounded block."""
    last_result = None
    for size in sizes:
        font = _font(size)
        lines = _wrapped_lines(draw, text, font, maximum_width)
        line_height = _line_height(font)
        line_spacing = max(4, round(size * line_spacing_ratio))
        required_height = len(lines) * line_height + max(0, len(lines) - 1) * line_spacing
        last_result = (font, lines, line_height, line_spacing)
        if required_height <= maximum_height:
            return last_result

    assert last_result is not None
    font, lines, line_height, line_spacing = last_result
    visible_lines = max(1, (maximum_height + line_spacing) // (line_height + line_spacing))
    lines = lines[:visible_lines]
    if lines:
        lines[-1] = f"{lines[-1].rstrip(' .')}…"
    return font, lines, line_height, line_spacing


def _ellipsize(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    maximum_width: int,
) -> str:
    """Keep a single metadata line within its visual boundary."""
    if draw.textlength(text, font=font) <= maximum_width:
        return text
    shortened = text.rstrip(" .")
    while shortened and draw.textlength(f"{shortened}…", font=font) > maximum_width:
        shortened = shortened[:-1]
    return f"{shortened.rstrip()}…"


def _parse_story_card(text: str) -> StoryCard:
    """Pull visual-card fields from the long-form copy used elsewhere.

    ``_post_copy`` has deliberately stable paragraph boundaries. Keeping the
    parser tolerant also makes ``text_to_image`` useful for old debug copy and
    direct callers that provide only plain text.
    """
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    before_summary, marker, after_summary = normalized.partition("\nSummary:\n")
    summary = after_summary.strip() if marker else ""
    sections = [
        section.strip() for section in before_summary.split("\n\n") if section.strip()
    ]

    header = sections[0] if sections else "Civic update"
    title = sections[1] if len(sections) > 1 else header
    details = sections[2:] if len(sections) > 2 else []
    source = "Official public record"
    event = "Official update"

    for detail in details:
        if detail.lower().startswith("source:"):
            source = detail.split(":", 1)[1].strip() or source
        elif event == "Official update":
            event = detail

    if not summary:
        # A direct caller has no structured copy. It is more useful to place
        # its text in the takeaway than to render a blank card body.
        summary = normalized or "No summary was provided."

    executive_order = re.match(
        r"^(Executive Order\s+[^\s]+)(?:\s+(.+))?$", header, re.I
    )
    if executive_order:
        identifier = executive_order.group(1)
        category = "EXECUTIVE ORDER"
        event = executive_order.group(2) or event
    else:
        identifier, separator, header_event = header.partition(" ")
        # Congressional identifiers commonly include a space (for example,
        # H.R. 42), so retain a short initial identifier plus its number.
        congressional = re.match(
            r"^((?:H|S)\.[A-Z.]*\s+\d+)(?:\s+(.+))?$", header, re.I
        )
        if congressional:
            identifier = congressional.group(1)
            event = congressional.group(2) or event
        elif separator:
            event = header_event
        category = "CONGRESSIONAL UPDATE"

    event = re.sub(r"\s+", " ", event).strip()
    source = re.sub(r"\s+", " ", source).strip()
    return StoryCard(
        category=category,
        identifier=identifier,
        event=event,
        title=title,
        source=source,
        summary=summary,
    )


def _background() -> Image.Image:
    """Create a quiet layered navy background without an external image asset."""
    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), INK)
    draw = ImageDraw.Draw(image)
    top = (11, 31, 55)
    bottom = (29, 71, 94)
    for y in range(IMAGE_HEIGHT):
        progress = y / (IMAGE_HEIGHT - 1)
        color = tuple(
            round(top[index] * (1 - progress) + bottom[index] * progress)
            for index in range(3)
        )
        draw.line((0, y, IMAGE_WIDTH, y), fill=color)

    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    # Fine lines and offset rings give the card an editorial, civic feel while
    # leaving plenty of visual rest around the copy.
    for x in range(-180, IMAGE_WIDTH + 200, 86):
        overlay_draw.line(
            (x, 0, x + 380, IMAGE_HEIGHT), fill=(156, 201, 220, 15), width=2
        )
    for radius, alpha in ((520, 34), (720, 22), (920, 14)):
        overlay_draw.ellipse(
            (
                IMAGE_WIDTH - 275 - radius,
                -250 - radius,
                IMAGE_WIDTH - 275 + radius,
                -250 + radius,
            ),
            outline=(232, 181, 91, alpha),
            width=3,
        )
    for x in range(90, IMAGE_WIDTH - 60, 48):
        for y in range(80, 520, 48):
            overlay_draw.ellipse((x, y, x + 4, y + 4), fill=(211, 230, 237, 35))
    return Image.alpha_composite(image.convert("RGBA"), overlay)


def _draw_centered(
    draw: ImageDraw.ImageDraw,
    text: str,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
) -> None:
    left, _, right, _ = draw.textbbox((0, 0), text, font=font)
    draw.text(((IMAGE_WIDTH - (right - left)) / 2, y), text, font=font, fill=fill)


def _draw_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    x: int,
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    line_height: int,
    line_spacing: int,
) -> int:
    for line in lines:
        draw.text((x, y), line, fill=fill, font=font)
        y += line_height + line_spacing
    return y


def _draw_centered_lines(
    draw: ImageDraw.ImageDraw,
    lines: list[str],
    y: int,
    font: ImageFont.FreeTypeFont,
    fill: str,
    line_height: int,
    line_spacing: int,
) -> int:
    """Draw a bounded text block with each line centered on the card."""
    for line in lines:
        _draw_centered(draw, line, y, font, fill)
        y += line_height + line_spacing
    return y


def text_to_image(text: str, image_path: str) -> None:
    """Render a polished 1080 by 1920 brief card from post copy.

    The layout intentionally foregrounds the latest action, document title, and
    AI summary over publishing metadata. Full source links remain in the post
    description; the card keeps a small source attribution for trust and
    context.
    """
    card = _parse_story_card(text)
    image = _background()
    draw = ImageDraw.Draw(image)

    brand_font = _font(26)
    category_font = _font(24)
    identifier_font = _font(52)
    _draw_centered(draw, "BILL SUMMARIES", 58, brand_font, PAPER)
    _draw_centered(draw, "─  PUBLIC RECORD, PLAIN LANGUAGE  ─", 106, category_font, SKY)

    pill_text = card.category
    pill_bbox = draw.textbbox((0, 0), pill_text, font=category_font)
    pill_width = pill_bbox[2] - pill_bbox[0] + 46
    pill_left = (IMAGE_WIDTH - pill_width) // 2
    draw.rounded_rectangle(
        (pill_left, 174, pill_left + pill_width, 222), radius=24, fill=GOLD
    )
    _draw_centered(draw, pill_text, 182, category_font, INK)

    _draw_centered(draw, card.identifier, 260, identifier_font, PAPER)
    action_label = "SIGNED" if card.category == "EXECUTIVE ORDER" else "LATEST ACTION"
    _draw_centered(draw, action_label, 331, _font(22), GOLD)
    event_font, event_lines, event_height, event_spacing = _fit_text(
        draw,
        card.event,
        IMAGE_WIDTH - 180,
        110,
        range(30, 19, -1),
        0.16,
    )
    _draw_centered_lines(
        draw,
        event_lines,
        366,
        event_font,
        MUTED_SKY,
        event_height,
        event_spacing,
    )
    draw.line((352, 478, 728, 478), fill=GOLD, width=4)

    title_font, title_lines, title_height, title_spacing = _fit_text(
        draw,
        card.title,
        IMAGE_WIDTH - IMAGE_MARGIN * 2,
        225,
        range(54, 31, -2),
        0.18,
    )
    _draw_lines(
        draw,
        title_lines,
        IMAGE_MARGIN,
        512,
        title_font,
        PAPER,
        title_height,
        title_spacing,
    )

    # The content card starts at a predictable point so a viewer knows where
    # to look for the takeaway from one Short to the next.
    card_top = 782
    card_bottom = 1775
    shadow = Image.new("RGBA", image.size, (0, 0, 0, 0))
    shadow_draw = ImageDraw.Draw(shadow)
    shadow_draw.rounded_rectangle(
        (CARD_LEFT + 7, card_top + 12, CARD_RIGHT + 7, card_bottom + 12),
        radius=38,
        fill=(0, 0, 0, 100),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(16))
    image.alpha_composite(shadow)
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (CARD_LEFT, card_top, CARD_RIGHT, card_bottom), radius=38, fill=PAPER
    )
    draw.rounded_rectangle(
        (CARD_LEFT, card_top, CARD_RIGHT, card_top + 12), radius=38, fill=GOLD
    )
    draw.text((92, card_top + 61), "WHAT IT DOES", font=_font(27), fill=INK)
    draw.line((92, card_top + 111, 267, card_top + 111), fill=GOLD, width=5)

    summary_font, summary_lines, summary_height, summary_spacing = _fit_text(
        draw,
        card.summary,
        860,
        660,
        range(42, 25, -1),
        0.22,
    )
    _draw_lines(
        draw,
        summary_lines,
        92,
        card_top + 160,
        summary_font,
        INK,
        summary_height,
        summary_spacing,
    )

    source_font = _font(23)
    source_text = _ellipsize(
        draw, f"SOURCE  •  {card.source.upper()}", source_font, 820
    )
    draw.line(
        (92, card_bottom - 116, CARD_RIGHT - 44, card_bottom - 116),
        fill=PAPER_MUTED,
        width=2,
    )
    draw.text((92, card_bottom - 79), source_text, font=source_font, fill="#486172")

    footer_font = _font(23)
    _draw_centered(draw, "BILL SUMMARIES  •  KNOW WHAT CHANGED", 1830, footer_font, PAPER)
    image.convert("RGB").save(image_path, quality=95)
