import csv
import random
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

QUOTES_DIR = Path(__file__).resolve().parent
BACKGROUND_PATH = QUOTES_DIR / "images" / "background.png"
OUTPUT_PATH = QUOTES_DIR / "images" / "quote.png"
QUOTES_PATH = QUOTES_DIR / "quotes.csv"


def load_quotes() -> list[dict[str, str]]:
    with QUOTES_PATH.open(newline="", encoding="utf-8-sig") as file:
        return list(csv.DictReader(file))


def find_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Italic.ttf",
    ):
        if Path(path).is_file():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)



def text_width(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
        left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
        return right - left


def text_wrap(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont, max_width: float) -> list[str]:
        words = text.split()
        lines: list[str] = []
        line = ""
        for word in words:
            candidate = f"{line} {word}".strip()
            if line and text_width(draw, candidate, font) > max_width:
                lines.append(line)
                line = word
            else:
                line = candidate
        if line:
            lines.append(line)
        return lines


def make_image(size: int = 80) -> None:
    quotes = load_quotes()
    if not quotes:
        raise ValueError(f"No quotes found in {QUOTES_PATH}")
    row = random.choice(quotes)
    string = f'"{row["Quote"].strip().capitalize()}"~{row["name"].strip().title()}'
    with Image.open(BACKGROUND_PATH) as img:
        w, h = img.size
        font = find_font(size)
        draw = ImageDraw.Draw(img)
        lines = text_wrap(draw, string, font, w * 0.8)
        distance = 90
        delta_y = 0.5 * (len(lines) - 1) * distance
        for index, line in enumerate(lines):
            left, top, right, bottom = draw.textbbox((0, 0), line, font=font)
            text_width_value = right - left
            text_height = bottom - top
            draw.text(
                (w / 2 - text_width_value / 2, h / 2 - text_height / 2 + index * distance - delta_y),
                line,
                font=font,
                fill=(0, 0, 0),
            )
        img.save(OUTPUT_PATH)


make_image()
