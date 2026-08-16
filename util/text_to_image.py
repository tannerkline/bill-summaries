from PIL import Image, ImageDraw, ImageFont
import logging

# logging setup
logging.basicConfig(datefmt='%Y/%m/%d %H:%M:%S', format='%(asctime)s %(message)s')
log = logging.getLogger(__name__)
log.setLevel(logging.INFO)

IMAGE_WIDTH = 1080
IMAGE_HEIGHT = 1350
IMAGE_MARGIN = 48
FONT_PATH = "/usr/src/app/fonts/DejaVuSerif.ttf"


def _wrap_line(draw: ImageDraw.ImageDraw, line: str, font, maximum_width: int) -> list:
    """Wrap a line by its rendered width, including unbroken long strings."""
    if not line:
        return [""]

    lines = []
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
            while split_at > 1 and draw.textlength(current_line[:split_at], font=font) > maximum_width:
                split_at -= 1
            lines.append(current_line[:split_at])
            current_line = current_line[split_at:]

    if current_line:
        lines.append(current_line)
    return lines


def _wrapped_lines(draw: ImageDraw.ImageDraw, text: str, font, maximum_width: int) -> list:
    lines = []
    for line in text.split("\n"):
        lines.extend(_wrap_line(draw, line, font, maximum_width))
    return lines


def text_to_image(text: str, image_dir: str):
    """Render a readable fixed-size 1080 by 1350 social-media image."""
    image = Image.new("RGB", (IMAGE_WIDTH, IMAGE_HEIGHT), "black")
    draw = ImageDraw.Draw(image)
    maximum_width = IMAGE_WIDTH - (IMAGE_MARGIN * 2)
    maximum_height = IMAGE_HEIGHT - (IMAGE_MARGIN * 2)

    for font_size in range(40, 19, -2):
        font = ImageFont.truetype(FONT_PATH, font_size)
        lines = _wrapped_lines(draw, text, font, maximum_width)
        line_height = font.getbbox("Ag")[3] - font.getbbox("Ag")[1]
        line_spacing = max(6, font_size // 5)
        required_height = (len(lines) * line_height) + (max(0, len(lines) - 1) * line_spacing)
        if required_height <= maximum_height:
            break
    else:
        # The summary is capped before rendering. This protects the fixed image
        # from unusually long bill metadata without creating an oversized PNG.
        visible_lines = max(1, maximum_height // (line_height + line_spacing))
        lines = lines[:visible_lines]
        if lines:
            lines[-1] = f"{lines[-1].rstrip(' .')}…"

    current_height = IMAGE_MARGIN
    for line in lines:
        draw.text((IMAGE_MARGIN, current_height), line, fill="white", font=font)
        current_height += line_height + line_spacing

    image.save(image_dir)
