from __future__ import annotations

import re
import urllib.request
from datetime import date, datetime
from html.parser import HTMLParser
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .config import PROJECT_DIR


ACTIVITIES_URL = "https://professorfrancken.nl/association/activities"
ACTIVITIES_IMAGE = PROJECT_DIR / "slides" / "activities.png"
NETWORK_TIMEOUT_SECONDS = 30
EVENT_LINK = re.compile(r"/association/activities/(\d{4}-\d{2}-\d{2})-[^/?#]+")
TIME_PATTERN = re.compile(r"\bat\s+(\d{1,2}:\d{2})\b", re.IGNORECASE)
LEADING_DATE = re.compile(r"^\d{1,2}\s+[A-Z]{3}\s+", re.IGNORECASE)
LONG_DATE = re.compile(
	r"\b\d{1,2}(?:\s*-\s*\d{1,2})?\s+"
	r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\b",
	re.IGNORECASE,
)
FFL_TITLE = re.compile(r"^(FFL:\s+)(\S+\s+\S+)", re.IGNORECASE)


class _ActivityParser(HTMLParser):
	def __init__(self) -> None:
		super().__init__()
		self.current_href: str | None = None
		self.current_text: list[str] = []
		self.activities: list[tuple[date, str, str]] = []

	def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
		if tag != "a":
			return
		href = dict(attrs).get("href")
		if href is not None and EVENT_LINK.search(href):
			self.current_href = href
			self.current_text = []

	def handle_data(self, data: str) -> None:
		if self.current_href is not None:
			self.current_text.append(data)

	def handle_endtag(self, tag: str) -> None:
		if tag != "a" or self.current_href is None:
			return
		match = EVENT_LINK.search(self.current_href)
		text = re.sub(r"[^\x20-\x7e]", " ", " ".join(self.current_text))
		text = re.sub(r"\s+", " ", text).strip()
		if match and text:
			event_date = date.fromisoformat(match.group(1))
			time_match = TIME_PATTERN.search(text)
			time_text = time_match.group(1) if time_match else ""
			title = LEADING_DATE.sub("", text)
			long_date = LONG_DATE.search(title)
			if long_date:
				title = title[:long_date.start()].strip()
			ffl_title = FFL_TITLE.match(title)
			if ffl_title:
				title = f"{ffl_title.group(1)}{ffl_title.group(2)}..."
			self.activities.append((event_date, title, time_text))
		self.current_href = None
		self.current_text = []


def sync_activity_slide() -> Path:
	request = urllib.request.Request(ACTIVITIES_URL, headers={"User-Agent": "slideshow activities updater"})
	with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
		parser = _ActivityParser()
		parser.feed(response.read().decode("utf-8", errors="replace"))

	activities = []
	seen: set[tuple[date, str]] = set()
	for event_date, title, time_text in sorted(parser.activities):
		key = (event_date, title)
		if event_date >= date.today() and key not in seen:
			seen.add(key)
			activities.append((event_date, title, time_text))
	if not activities:
		raise RuntimeError("No upcoming association activities found")

	ACTIVITIES_IMAGE.parent.mkdir(parents=True, exist_ok=True)
	_draw_activity_image(activities[:6])
	return ACTIVITIES_IMAGE


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
	font_name = "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"
	return ImageFont.truetype(font_name, size)


def _draw_activity_image(activities: list[tuple[date, str, str]]) -> None:
	image = Image.new("RGB", (1920, 1080), (18, 28, 40))
	draw = ImageDraw.Draw(image)
	draw.rectangle((0, 0, 28, 1080), fill=(196, 48, 48))
	draw.text((110, 78), "UPCOMING ACTIVITIES", font=_font(78, True), fill=(244, 240, 228))
	draw.text((114, 166), "T.F.V. 'Professor Francken'", font=_font(29), fill=(174, 190, 198))

	row_y = 270
	for event_date, title, time_text in activities:
		weekday_text = event_date.strftime("%a").upper()
		date_text = event_date.strftime("%d %b").upper()
		date_font = _font(34, True)
		time_font = _font(29)
		draw.text((115, row_y), weekday_text, font=date_font, fill=(236, 82, 82))
		date_width = draw.textbbox((0, 0), date_text, font=date_font)[2]
		draw.text((365 - date_width, row_y), date_text, font=date_font, fill=(236, 82, 82))
		time_text = time_text or ""
		time_width = draw.textbbox((0, 0), time_text, font=time_font)[2]
		draw.text((365 - time_width, row_y + 45), time_text, font=time_font, fill=(206, 157, 157))
		details = title or "Association activity"
		title_font = _font(54, True)
		while draw.textlength(details, font=title_font) > 1400 and len(details) > 3:
			details = details[:-4].rstrip() + "..."
		date_top = draw.textbbox((0, 0), date_text, font=date_font)[1]
		title_top = draw.textbbox((0, 0), details, font=title_font)[1]
		draw.text((390, row_y + date_top - title_top), details, font=title_font, fill=(244, 240, 228))
		row_y += 115

	updated_text = f"Updated {datetime.now().strftime('%d %b %Y, %H:%M')}"
	updated_font = _font(24)
	updated_width = draw.textbbox((0, 0), updated_text, font=updated_font)[2]
	draw.text(
		(1920 - 115 - updated_width, 1000),
		updated_text,
		font=updated_font,
		fill=(137, 158, 169),
	)
	image.save(ACTIVITIES_IMAGE)