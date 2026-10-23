"""The info slide: in turn news, the weather, the next buses and today's Applied Physics timetable.
After bieruur (rotation.daytime_only) only a rain warning, when rain is expected within two hours.

One info slide per round, the next part each time; a part with nothing to show is skipped. All
sources are free and need no key; each part is fetched on its own schedule, and one that fails
doesn't stop the others (the last error shows on /status):
- news: RSS feeds (Dagblad van het Noorden, NU.nl, BBC World by default; [info] news_feeds in
  config.toml). Tapping a headline opens the article: from the feed when it has the whole text,
  else from the article's page (BBC), else the feed's summary (NU.nl and DvhN block fetching
  their pages). The
  slideshow downloads each headline's picture itself (data/cache/news): one that can't be fetched
  is left out, instead of a broken image making the player skip the slide.
- weather: open-meteo.com for the weather now and the next days; Buienradar's rain forecast for
  the next two hours (the same as their app)
- buses: live departures from OVapi (v0.ovapi.nl, the same national real-time data 9292 shows);
  the stop is a list of timing point codes (from the national stop list, GTFS stops.txt)
- timetable: rooster.rug.nl; the programmes are found by name and year of study every refresh,
  because their ids change every academic year.
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass, field, replace
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from ..config import parse_time
from ..slides import PartsFailed, Provider, Slide, media_url

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "FranckenTV-slideshow/1.0 (the TV in the T.F.V. 'Professor Francken' room)"}
NEWS_FEEDS = [
	["Dagblad van het Noorden", "https://www.dvhn.nl/rss"],
	["NU.nl", "https://www.nu.nl/rss/Algemeen"],
	["BBC World", "https://feeds.bbci.co.uk/news/world/rss.xml"],
]
ADS = re.compile(r"commerci[eë]le[ -]content|advertorial|sponsored|gesponsord|partnercontent", re.IGNORECASE)
ZERNIKE = (53.2406, 6.5364)
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
RAIN_URL = "https://gpsgadget.buienradar.nl/data/raintext"
OVAPI_URL = "http://v0.ovapi.nl/tpc/{codes}"
ALETTA_JACOBSHAL = ["10004120"]   # Groningen, Aletta Jacobshal: the side towards the city centre (10004110 is the other side)
# Qbuzz's colours for the Groningen city lines (Qlink), as on their site and the buses: [background, text].
# From route_color/route_text_color in the national GTFS (gtfs.ovapi.nl/nl, routes.txt); the regional lines
# (107, 109, 171, ...) have none there and keep the slide's blue.
BUS_LINE_COLORS = {
	"1": ["#00be46", "#000000"], "2": ["#8cdc32", "#000000"], "3": ["#1078be", "#ffffff"],
	"4": ["#00bcf2", "#000000"], "5": ["#b400be", "#ffffff"], "6": ["#c85aff", "#ffffff"],
	"9": ["#ff00ff", "#ffffff"], "11": ["#00be46", "#000000"], "15": ["#ff5f00", "#000000"],
	"18": ["#99c200", "#000000"],
}
ROOSTER_URL = "https://rooster.rug.nl/maat/api/{year}"
TIMETABLE = [["BSc Applied Physics", 1], ["BSc Applied Physics", 2], ["BSc Applied Physics", 3], ["MSc Applied Physics", 1]]
PARTS = ["news", "weather", "buses", "timetable"]
# How often each part is fetched again (the buses also count down by themselves in between).
REFRESH_MINUTES = {"news": 15, "weather": 10, "buses": 1, "timetable": 180}


# ---- News ----------------------------------------------------------------------------------

@dataclass
class Headline:
	title: str
	time: datetime | None   # local time
	link: str = ""
	paragraphs: list[str] = field(default_factory=list)   # the article, or its summary, from the feed
	image_url: str = ""   # the feed's picture, in a size fit for the TV (larger_image)
	image: str = ""       # the downloaded copy, as a /files/ url; "" if there's none


def is_ad(item: ElementTree.Element) -> bool:
	"""Whether a feed item is sponsored content: by its category or link (DvhN's "Commerciële content")."""
	text = " ".join([item.findtext("link") or ""] + [category.text or "" for category in item.iter("category")])
	return bool(ADS.search(text))


def parse_feed(xml: bytes | str) -> list[Headline]:
	"""The items of an RSS feed, newest first, without the ads."""
	headlines = []
	for item in ElementTree.fromstring(xml).iter("item"):
		title = (item.findtext("title") or "").strip()
		if not title or is_ad(item):
			continue
		try:
			time = parsedate_to_datetime(item.findtext("pubDate") or "").astimezone().replace(tzinfo=None)
		except (TypeError, ValueError):
			time = None
		headlines.append(Headline(title, time, (item.findtext("link") or "").strip(), html_paragraphs(item.findtext("description") or ""),
			larger_image(feed_image(item))))
	return sorted(headlines, key=lambda headline: headline.time or datetime.min, reverse=True)


def feed_image(item: ElementTree.Element) -> str:
	"""The picture of a feed item: an <enclosure> (NOS, NU.nl) or <media:thumbnail>/<media:content> (BBC)."""
	for child in item:
		tag = child.tag.rsplit("}", 1)[-1]
		url = child.attrib.get("url", "")
		if url and (tag in ("thumbnail", "content") or (tag == "enclosure" and child.attrib.get("type", "image").startswith("image"))):
			return url
	return ""


def larger_image(url: str) -> str:
	"""The same picture in a size for the TV: NU.nl's feed has 256x256 squares and the BBC's 240 pixels
	wide, while both sites also have larger versions at nearly the same address."""
	url = re.sub(r"_sqr\d+/", "_wd1280/", url) if "images.nu.nl" in url else url
	return re.sub(r"/standard/\d+/", "/standard/976/", url) if "ichef.bbci.co.uk" in url else url


def html_paragraphs(html: str) -> list[str]:
	"""The text of a feed description or page part, as paragraphs."""
	soup = BeautifulSoup(html, "html.parser")
	paragraphs = [text for p in soup.find_all(["p", "h2", "h3", "li"]) if (text := p.get_text(" ", strip=True))]
	if not paragraphs and (text := soup.get_text(" ", strip=True)):
		paragraphs = [text]   # plain text, no tags
	return paragraphs


ARTICLE_SKIP = ["script", "style", "aside", "nav", "footer", "figure", "header", "form", "button"]


def article_paragraphs(html: str) -> list[str]:
	"""The paragraphs of an article page: those in its <article> (or <main>), leaving out captions,
	menus and the like, and lines too short to be text."""
	soup = BeautifulSoup(html, "html.parser")
	for tag in soup(ARTICLE_SKIP):
		tag.decompose()
	box = soup.find("article") or soup.find("main")
	if box is None:
		return []
	return [text for p in box.find_all("p") if len(text := p.get_text(" ", strip=True)) > 40]


def ago(time: datetime | None, now: datetime) -> str:
	"""'just now', '12 min ago', '3 hours ago', 'yesterday'"""
	if time is None:
		return ""
	minutes = int((now - time).total_seconds() // 60)
	if minutes < 2:
		return "just now"
	if minutes < 60:
		return f"{minutes} min ago"
	if minutes < 24 * 60:
		hours = minutes // 60
		return f"{hours} hour{'s' if hours > 1 else ''} ago"
	return "yesterday" if minutes < 48 * 60 else f"{minutes // (24 * 60)} days ago"


# ---- Weather -------------------------------------------------------------------------------

# WMO weather codes (open-meteo): description and an icon.
WEATHER_CODES = {
	0: ("Clear sky", "☀️"), 1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁️"),
	45: ("Fog", "🌫️"), 48: ("Freezing fog", "🌫️"),
	51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌧️"), 56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
	61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"), 66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
	71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"), 77: ("Snow grains", "🌨️"),
	80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌧️"), 82: ("Heavy showers", "🌧️"), 85: ("Snow showers", "🌨️"), 86: ("Snow showers", "🌨️"),
	95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm with hail", "⛈️"), 99: ("Thunderstorm with hail", "⛈️"),
}
NIGHT_ICONS = {"☀️": "🌙", "🌤️": "🌙", "⛅": "☁️"}
# The animated background of the weather slide for each WMO code (default: cloudy).
WEATHER_SCENES = {
	0: "clear", 1: "clear", 2: "partly", 3: "cloudy", 45: "fog", 48: "fog",
	51: "drizzle", 53: "drizzle", 55: "drizzle", 56: "drizzle", 57: "drizzle",
	61: "rain", 63: "rain", 65: "heavy-rain", 66: "rain", 67: "heavy-rain", 80: "rain", 81: "rain", 82: "heavy-rain",
	71: "snow", 73: "snow", 75: "snow", 77: "snow", 85: "snow", 86: "snow",
	95: "storm", 96: "storm", 99: "storm",
}
WIND_DIRECTIONS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def weather_look(code: int, is_day: bool = True) -> tuple[str, str]:
	text, icon = WEATHER_CODES.get(code, ("", "🌡️"))
	return text, icon if is_day else NIGHT_ICONS.get(icon, icon)


@dataclass
class Day:
	day: date
	high: float
	low: float
	text: str
	icon: str
	rain_chance: int   # %, the highest of the day


@dataclass
class Weather:
	temperature: float
	feels_like: float
	text: str
	icon: str
	wind_kmh: float
	wind_from: str     # "NE"
	days: list[Day] = field(default_factory=list)   # today first
	rain: list[tuple[str, float]] = field(default_factory=list)   # ("14:35", mm/h) per 5 minutes, two hours ahead
	code: int = 3      # the WMO weather code now
	is_day: bool = True

	@property
	def rain_summary(self) -> str:
		return rain_summary(self.rain)

	@property
	def scene(self) -> str:
		"""The weather slide's animated background: clear, partly, cloudy, fog, drizzle, rain, heavy-rain, snow or storm."""
		return WEATHER_SCENES.get(self.code, "cloudy")


def parse_weather(data: dict) -> Weather:
	current = data["current"]
	text, icon = weather_look(current["weather_code"], bool(current.get("is_day", 1)))
	daily = data["daily"]
	days = [Day(date.fromisoformat(day), high, low, *weather_look(code), chance or 0)
		for day, high, low, code, chance in zip(daily["time"], daily["temperature_2m_max"], daily["temperature_2m_min"],
			daily["weather_code"], daily["precipitation_probability_max"])]
	return Weather(
		temperature=current["temperature_2m"],
		feels_like=current["apparent_temperature"],
		text=text,
		icon=icon,
		wind_kmh=current["wind_speed_10m"],
		wind_from=WIND_DIRECTIONS[round(current["wind_direction_10m"] / 45) % 8],
		days=days,
		code=current["weather_code"],
		is_day=bool(current.get("is_day", 1)),
	)


def parse_rain(text: str) -> list[tuple[str, float]]:
	"""Buienradar's 'value|HH:MM' lines as (HH:MM, mm/h); the value is 0-255, 0 is dry."""
	rain = []
	for line in text.splitlines():
		value, _, time = line.strip().partition("|")
		if value.isdigit() and time:
			rain.append((time, 0.0 if int(value) == 0 else round(10 ** ((int(value) - 109) / 32), 2)))
	return rain


def rain_words(mm: float) -> str:
	return "light rain" if mm < 1 else "rain" if mm < 4 else "heavy rain"


RAIN_LEVELS = [("Light", 0.1), ("Medium", 1.0), ("Heavy", 4.0)]   # where each kind of rain starts, mm/h


def rain_top(rain: list[tuple[str, float]]) -> float:
	return max([mm for _, mm in rain] + [2.0])   # the chart's top: at least 2 mm/h


def rain_bars(rain: list[tuple[str, float]]) -> list[dict]:
	"""The rain per 5 minutes, with its height in the chart (0-100) relative to the chart's top (square
	root, so light rain still shows)."""
	top = rain_top(rain)
	return [{"time": time, "mm": mm, "level": rain_level(mm), "height": round(100 * math.sqrt(mm / top), 1)} for time, mm in rain]


def smooth_path(points: list[tuple[float, float]]) -> str:
	"""An SVG path through the points as a smooth curve (Catmull-Rom), never dipping below the
	bottom (y = 100) or above the top (y = 0)."""
	d = f"M{points[0][0]:.2f},{points[0][1]:.2f}"
	for i in range(len(points) - 1):
		p0, p1, p2, p3 = points[max(i - 1, 0)], points[i], points[i + 1], points[min(i + 2, len(points) - 1)]
		c1 = (p1[0] + (p2[0] - p0[0]) / 6, min(100, max(0, p1[1] + (p2[1] - p0[1]) / 6)))
		c2 = (p2[0] - (p3[0] - p1[0]) / 6, min(100, max(0, p2[1] - (p3[1] - p1[1]) / 6)))
		d += f" C{c1[0]:.2f},{c1[1]:.2f} {c2[0]:.2f},{c2[1]:.2f} {p2[0]:.2f},{p2[1]:.2f}"
	return d


def rain_chart(rain: list[tuple[str, float]]) -> dict | None:
	"""The line chart of the rain (rain_chart.html), in a 100 x 100 SVG box: the line, the area under
	it and the times along the bottom, every half hour."""
	if len(rain) < 2:
		return None
	bars = rain_bars(rain)
	points = [(100 * i / (len(bars) - 1), 100 - bar["height"]) for i, bar in enumerate(bars)]
	line = smooth_path(points)
	return {"line": line, "area": f"{line} L100,100 L0,100 Z",
		"times": [{"x": round(points[i][0], 2), "time": bars[i]["time"]} for i in range(0, len(bars), 6)]}


def rain_lines(rain: list[tuple[str, float]]) -> list[dict]:
	"""Lines across the rain chart where light, medium and heavy rain start, as high as a bar of that
	much rain; only those within the chart, and none when it stays dry."""
	if not any(mm >= 0.1 for _, mm in rain):
		return []
	top = rain_top(rain)
	return [{"label": label, "height": round(100 * math.sqrt(mm / top), 1)} for label, mm in RAIN_LEVELS if mm <= top]


def rain_level(mm: float) -> str:
	"""For the chart's colours: "dry", "light" (< 1 mm/h), "medium" (< 4) or "heavy"."""
	return "dry" if mm < 0.1 else "light" if mm < 1 else "medium" if mm < 4 else "heavy"


DRY_STRETCH = 6        # "dry from" only when it then stays dry this many five minutes (half an hour)...
DRY_STRETCH_AT_END = 3   # ...or, at the end of the forecast, at least this many (a quarter)


def dry_from(rain: list[tuple[str, float]]) -> str | None:
	"""When it stops raining for a while: the start of the first dry half hour, not the first dry
	five minutes between two showers. None if there's no such stretch in the forecast."""
	wet = [mm >= 0.1 for _, mm in rain]
	for i in range(len(wet)):
		stretch = wet[i:i + DRY_STRETCH]
		if not any(stretch) and (len(stretch) == DRY_STRETCH or len(stretch) >= DRY_STRETCH_AT_END):
			return rain[i][0]
	return None


def rain_summary(rain: list[tuple[str, float]]) -> str:
	"""'Dry for the next 2 hours', 'Light rain from 14:35', 'Rain now, dry from 15:10'"""
	wet = [mm >= 0.1 for _, mm in rain]
	if not rain or not any(wet):
		return "Dry for the next 2 hours"
	heaviest = max(mm for _, mm in rain)
	if wet[0]:
		dry = dry_from(rain)
		return f"{rain_words(heaviest).capitalize()} now, dry from {dry}" if dry else f"{rain_words(heaviest).capitalize()} for the next 2 hours"
	start = next(time for (time, _), is_wet in zip(rain, wet) if is_wet)
	return f"{rain_words(heaviest).capitalize()} from {start}"


# ---- Buses ---------------------------------------------------------------------------------

@dataclass
class Departure:
	line: str
	destination: str
	planned: datetime
	expected: datetime
	cancelled: bool = False

	@property
	def delay(self) -> int:
		"""Minutes late (0 if on time or early)."""
		return max(0, round((self.expected - self.planned).total_seconds() / 60))


def parse_departures(data: dict) -> list[Departure]:
	"""All passes at the asked timing points (OVapi /tpc/...), soonest first."""
	departures = []
	for timing_point in data.values():
		for item in (timing_point.get("Passes") or {}).values():
			if item.get("JourneyStopType") == "LAST":   # arriving at its last stop: not departing
				continue
			departures.append(Departure(
				line=item["LinePublicNumber"],
				destination=item["DestinationName50"],
				planned=datetime.fromisoformat(item["TargetDepartureTime"]),
				expected=datetime.fromisoformat(item["ExpectedDepartureTime"]),
				cancelled=item.get("TripStopStatus") == "CANCEL",
			))
	return sorted(departures, key=lambda departure: departure.expected)


# ---- Timetable -----------------------------------------------------------------------------

def academic_year(day: date) -> str:
	"""'2026-2027' from September 2026 to August 2027."""
	start = day.year if day.month >= 9 else day.year - 1
	return f"{start}-{start + 1}"


@dataclass
class Lecture:
	start: datetime
	end: datetime
	course: str
	kind: str           # "Lecture", "Tutorial", ...
	rooms: list[str]

	@property
	def group(self) -> str:
		"""The colour group of the kind: "lecture", "tutorial", "practical", "exam" or "other"."""
		return KIND_GROUPS.get(self.kind.lower(), "other")


# rooster.rug.nl's kinds of activity, in colour groups (the timetable slide colours them; see style.css).
KIND_GROUPS = {
	"lecture": "lecture",
	"tutorial": "tutorial", "workshop": "tutorial", "q&a": "tutorial",
	"practical": "practical", "computer practical": "practical", "lab session": "practical", "projects": "practical",
	"exam": "exam", "exam digital": "exam", "midterm": "exam", "midterm digital": "exam",
	"resit": "exam", "resit digital": "exam", "inspection": "exam",
}
GENERIC_ROOM_NAMES = {"", "-", "collegezaal", "werkcollegezaal", "zaal", "lecture hall"}


def room_label(room: dict) -> str:
	"""'5161.0289', or '5113.0202 Max Gruberzaal' when the room has a name of its own."""
	code, name = room.get("code") or "", (room.get("displayNameEn") or "").strip()
	return f"{code} {name}".strip() if name.lower() not in GENERIC_ROOM_NAMES else code


def parse_timetable(events: list[dict], columns: dict[int, str]) -> dict[str, list[Lecture]]:
	"""rooster.rug.nl events per column (programme id -> "BSc 1"), in time order. Events that only
	differ in room (e.g. tutorial groups) become one, with all the rooms."""
	merged: dict[tuple, Lecture] = {}
	for event in events:
		start, end = datetime(*event["start"]), datetime(*event["end"])
		course = (event.get("courseOfferings") or [{}])[0].get("displayNameEn") or event.get("description") or ""
		kind = (event.get("activityType") or {}).get("displayNameEn", "")
		rooms = [label for room in event.get("rooms") or [] if (label := room_label(room))]
		for programme in event.get("programmeOfferings") or []:
			column = columns.get(programme.get("id"))
			if column is None:
				continue
			key = (column, start, end, course, kind)
			if key in merged:
				merged[key].rooms += [room for room in rooms if room not in merged[key].rooms]
			else:
				merged[key] = Lecture(start, end, course, kind, list(dict.fromkeys(rooms)))
	timetable: dict[str, list[Lecture]] = {column: [] for column in columns.values()}
	for (column, *_), lecture in sorted(merged.items(), key=lambda item: item[1].start):
		timetable[column].append(lecture)
	return timetable


def column_name(name: str, year: int) -> str:
	"""'BSc Applied Physics', 1 -> 'BSc 1'"""
	return f"{name.split()[0]} {year}"


# ---- The slide -----------------------------------------------------------------------------

class InfoProvider(Provider):
	name = "info"
	title = "Info"
	nothing_to_show = "No news, weather, buses or timetable yet"
	refresh_seconds = 60   # each part has its own interval (REFRESH_MINUTES)

	def __init__(self, settings: dict, default_seconds: float, image_folder: Path | None = None) -> None:
		self.image_folder = image_folder   # the news pictures; None: no pictures
		self.seconds = settings.get("seconds", default_seconds)
		self.part_seconds = {"timetable": settings.get("timetable_seconds", 25)}   # parts that need longer to read
		self.parts = settings.get("show", PARTS)
		self.news_feeds = settings.get("news_feeds", NEWS_FEEDS)
		self.headlines_per_feed = settings.get("headlines_per_feed", 3)
		self.place = settings.get("weather_place", "Zernike campus")
		self.location = settings.get("weather_location", list(ZERNIKE))
		self.stop_name = settings.get("bus_stop_name", "Aletta Jacobshal")
		self.stop_codes = settings.get("bus_stop_codes", ALETTA_JACOBSHAL)
		self.departures_shown = settings.get("departures_shown", 8)
		self.walk_minutes = settings.get("bus_walk_minutes", 2)   # from the association to the stop
		self.line_colors = settings.get("bus_line_colors", BUS_LINE_COLORS)
		self.timetable_name = settings.get("timetable_name", "Applied Physics")
		self.timetable_programmes = settings.get("timetable", TIMETABLE)
		self.next_day_from = settings.get("timetable_next_day_from_hour", 18)
		self.news: dict[str, list[Headline]] = {}
		self.articles: dict[str, list[str]] = {}   # fetched article pages by link (see article_text)
		self.weather: Weather | None = None
		self.departures: list[Departure] = []
		self.timetable: dict[str, list[Lecture]] = {}
		self.fetched: dict[str, datetime] = {}
		self.turn = 0

	# -- fetching --

	def refresh(self, now: datetime) -> None:
		"""Fetch the parts that are due. One that fails keeps its old data and is tried again next minute."""
		failed = []
		for part in self.parts:
			last = self.fetched.get(part)
			if last is not None and now - last < timedelta(minutes=REFRESH_MINUTES[part]) and now.date() == last.date():
				continue
			try:
				getattr(self, f"fetch_{part}")(now)
				self.fetched[part] = now
			except Exception as error:
				log.warning("Could not fetch the %s: %s", part, error)
				failed.append(f"{part}: {error!r}")
		if failed:
			raise PartsFailed("; ".join(failed))

	def fetch_news(self, now: datetime) -> None:
		news = {}
		for name, url in self.news_feeds:
			try:
				response = requests.get(url, headers=HEADERS, timeout=20)
				response.raise_for_status()
				news[name] = parse_feed(response.content)[: self.headlines_per_feed]
			except Exception as error:   # one feed down: the others still show
				log.warning("Could not read the %s feed: %s", name, error)
				if name in self.news:
					news[name] = self.news[name]
		if not news:
			raise RuntimeError("no news feed could be read")
		self.download_images([headline for headlines in news.values() for headline in headlines])
		self.news = news
		links = {headline.link for headlines in news.values() for headline in headlines}
		self.articles = {link: text for link, text in self.articles.items() if link in links}   # only what can still be opened

	def download_images(self, headlines: list[Headline]) -> None:
		"""Download the headlines' pictures (once each) and delete those of headlines that are gone."""
		if self.image_folder is None:
			return
		self.image_folder.mkdir(parents=True, exist_ok=True)
		keep = set()
		for headline in headlines:
			if not headline.image_url:
				continue
			suffix = Path(headline.image_url.split("?")[0]).suffix.lower() or ".jpg"
			path = self.image_folder / (hashlib.sha1(headline.image_url.encode()).hexdigest()[:16] + suffix)
			if not path.exists():
				try:
					response = requests.get(headline.image_url, headers=HEADERS, timeout=20)
					response.raise_for_status()
					if not response.headers.get("Content-Type", "").startswith("image/"):
						raise ValueError(f"not an image: {response.headers.get('Content-Type')}")
					path.write_bytes(response.content)
				except (requests.RequestException, ValueError) as error:
					log.warning("Could not fetch the picture %s: %s", headline.image_url, error)
					continue
			keep.add(path.name)
			headline.image = media_url(path)
		for old in self.image_folder.iterdir():
			if old.name not in keep:
				old.unlink()

	def fetch_weather(self, now: datetime) -> None:
		lat, lon = self.location
		response = requests.get(WEATHER_URL, headers=HEADERS, timeout=20, params={
			"latitude": lat, "longitude": lon, "timezone": "Europe/Amsterdam", "forecast_days": 7,
			"current": "temperature_2m,apparent_temperature,weather_code,wind_speed_10m,wind_direction_10m,is_day",
			"daily": "temperature_2m_max,temperature_2m_min,weather_code,precipitation_probability_max",
		})
		response.raise_for_status()
		weather = parse_weather(response.json())
		try:
			rain = requests.get(RAIN_URL, headers=HEADERS, timeout=20, params={"lat": round(lat, 2), "lon": round(lon, 2)})
			rain.raise_for_status()
			weather.rain = parse_rain(rain.text)
		except requests.RequestException as error:   # no rain forecast: the rest still shows
			log.warning("Could not fetch the rain forecast: %s", error)
		self.weather = weather

	def fetch_buses(self, now: datetime) -> None:
		response = requests.get(OVAPI_URL.format(codes=",".join(self.stop_codes)), headers=HEADERS, timeout=20)
		response.raise_for_status()
		self.departures = parse_departures(response.json())

	def fetch_timetable(self, now: datetime) -> None:
		year = academic_year(now.date())
		api = ROOSTER_URL.format(year=year)
		columns = {}
		for name, year_of_study in self.timetable_programmes:
			response = requests.post(f"{api}/programme-offerings/search", headers=HEADERS, timeout=30,
				json={"searchText": name, "academicYear": year, "limit": 50})
			response.raise_for_status()
			normalised = " ".join(name.lower().split())
			match = next((programme for programme in response.json().get("results", [])
				if " ".join(programme["displayNameEn"].lower().split()).startswith(normalised)
				and programme.get("yearOfStudy") == year_of_study and programme.get("specialisation") == "Base programme"), None)
			if match is None:
				log.warning("No programme %r year %s in rooster.rug.nl %s", name, year_of_study, year)
				continue
			columns[match["id"]] = column_name(name, year_of_study)
		if not columns:
			raise RuntimeError(f"none of the programmes found in the {year} timetable")
		response = requests.post(f"{api}/schedule/generate", headers=HEADERS, timeout=60,
			json={"objects": list(columns), "courseOfferings": []})
		response.raise_for_status()
		self.timetable = parse_timetable(response.json().get("results", []), columns)

	# -- showing --

	def slides(self, now: datetime) -> list[Slide]:
		"""The next part that has something to show; the round after, the one after that."""
		for step in range(len(self.parts)):
			part = self.parts[(self.turn + step) % len(self.parts)]
			data = self.data(part, now)
			if data is not None:
				self.turn = (self.turn + step + 1) % len(self.parts)
				return [self.part_slide(part, data)]
		return []

	def outside_daytime_slides(self, now: datetime) -> list[Slide]:
		"""After bieruur and at night (rotation.daytime_only): no news, buses or timetable, but a rain
		warning (info_rain.html) when rain is expected within two hours."""
		data = self.rain_data(now) if "weather" in self.parts else None
		return [self.part_slide("rain", data)] if data else []

	def rain_preview(self, now: datetime) -> Slide | None:
		"""For /preview/rain: the rain warning, with the real forecast, or when it stays dry with an
		example shower starting in half an hour (marked as an example)."""
		if self.weather is None:
			return None
		if self.rain_coming(now):
			return self.part_slide("rain", self.rain_data(now))
		start = now.replace(second=0, microsecond=0) - timedelta(minutes=now.minute % 5)
		shower = [0] * 6 + [0.2, 0.5, 1.1, 2.3, 3.6, 2.8, 1.9, 1.2, 0.6, 0.3, 0.1] + [0] * 7
		real = self.weather
		self.weather = replace(real, rain=[((start + timedelta(minutes=5 * i)).strftime("%H:%M"), mm) for i, mm in enumerate(shower)])
		try:
			data = self.rain_data(now) | {"example": True}
		finally:
			self.weather = real
		return Slide("info_rain.html", self.seconds, data)

	def part_slide(self, part: str, data: dict) -> Slide:
		# Worked out again when shown: the round is planned ahead, and buses leave meanwhile.
		return Slide(f"info_{part}.html", self.part_seconds.get(part, self.seconds), data, update=lambda when: self.data(part, when) or data)

	def upcoming_rain(self, now: datetime) -> list[tuple[str, float]]:
		"""Buienradar's forecast from the current five minutes on: it's fetched every 10 minutes, so
		its first values may be past already. At most the next two hours."""
		if self.weather is None or not self.weather.rain:
			return []
		first = datetime.combine(now.date(), parse_time(self.weather.rain[0][0]))
		if first > now + timedelta(hours=12):   # fetched just before midnight
			first -= timedelta(days=1)
		upcoming = []
		for hhmm, mm in self.weather.rain:
			when = datetime.combine(first.date(), parse_time(hhmm))
			if when < first:   # after midnight
				when += timedelta(days=1)
			if now - timedelta(minutes=5) < when <= now + timedelta(hours=2):
				upcoming.append((hhmm, mm))
		return upcoming

	def rain_coming(self, now: datetime) -> bool:
		"""Rain in Buienradar's forecast for the next two hours (or now)."""
		return any(mm >= 0.1 for _, mm in self.upcoming_rain(now))

	def data(self, part: str, now: datetime) -> dict | None:
		return getattr(self, f"{part}_data")(now)

	def news_data(self, now: datetime) -> dict | None:
		if not self.news:
			return None
		return {"feeds": [{"name": name, "headlines": [{"title": headline.title, "ago": ago(headline.time, now), "link": headline.link,
			"image": headline.image} for headline in headlines]} for name, headlines in self.news.items() if headlines]}

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""'article' (values = [its link]): the article to read; 'news': back to the headlines."""
		if name == "article" and values:
			found = next(((feed, headline) for feed, headlines in self.news.items() for headline in headlines
				if headline.link == values[0]), None)
			if found is None:
				return None, "That article is no longer in the news"
			feed, headline = found
			paragraphs, whole = self.article_text(headline)
			return Slide("info_article.html", self.seconds, {"feed": feed, "headline": headline, "ago": ago(headline.time, now),
				"paragraphs": paragraphs, "whole": whole}), None
		data = self.news_data(now)
		return (Slide("info_news.html", self.seconds, data) if data else None), None

	def article_text(self, headline: Headline) -> tuple[list[str], bool]:
		"""The article's paragraphs, and whether that's the whole article (not only a summary)."""
		if len(headline.paragraphs) >= 3:   # the feed has the whole article
			return headline.paragraphs, True
		if headline.link not in self.articles:
			try:
				response = requests.get(headline.link, headers=HEADERS, timeout=15)
				response.raise_for_status()
				self.articles[headline.link] = article_paragraphs(response.text)
			except requests.RequestException as error:
				log.warning("Could not fetch the article %s: %s", headline.link, error)
				return headline.paragraphs, False
		paragraphs = self.articles[headline.link]
		return (paragraphs, True) if len(paragraphs) >= 2 else (headline.paragraphs, False)

	def weather_data(self, now: datetime) -> dict | None:
		if self.weather is None:
			return None
		days = [day for day in self.weather.days if day.day >= now.date()][:6]   # today and the next five
		rain = self.upcoming_rain(now)
		return {"weather": self.weather, "place": self.place, "days": days, "today": now.date(), "rain": rain_bars(rain),
			"chart": rain_chart(rain), "rain_lines": rain_lines(rain), "rain_summary": rain_summary(rain)}

	def rain_data(self, now: datetime) -> dict | None:
		"""The rain warning (after bieruur): when, how heavy, and the chart; None when it stays dry."""
		rain = self.upcoming_rain(now)
		if not any(mm >= 0.1 for _, mm in rain):
			return None
		heaviest = max(mm for _, mm in rain)
		return {"summary": rain_summary(rain), "heaviest": rain_words(heaviest), "place": self.place,
			"rain": rain_bars(rain), "chart": rain_chart(rain), "rain_lines": rain_lines(rain), "weather": self.weather}

	def buses_data(self, now: datetime) -> dict | None:
		"""The buses that can still be caught: those leaving at least walk_minutes from now. One you have to
		leave for right away (less than a minute to spare) is a "last call"."""
		catchable = now + timedelta(minutes=self.walk_minutes)
		upcoming = [departure for departure in self.departures if departure.expected >= catchable]
		if not upcoming:
			return None
		shown = []
		for departure in upcoming[: self.departures_shown]:
			minutes = int((departure.expected - now).total_seconds() // 60)
			shown.append({"departure": departure, "minutes": minutes, "colors": self.line_colors.get(departure.line),
				"last_call": departure.expected < catchable + timedelta(minutes=1)})
		return {"stop": self.stop_name, "departures": shown, "walk_minutes": self.walk_minutes}

	def timetable_data(self, now: datetime) -> dict | None:
		"""Today's lectures that aren't over yet, until the evening; else those of the next day that has
		any (within a week). A lecture from 9:00 to 11:00 is gone at 11:00."""
		if not self.timetable:
			return None
		start_day = now.date() if now.hour < self.next_day_from else now.date() + timedelta(days=1)
		for offset in range(8):
			day = start_day + timedelta(days=offset)
			columns = {column: [lecture for lecture in lectures if lecture.start.date() == day and lecture.end > now] for column, lectures in self.timetable.items()}
			if any(columns.values()):
				label = "today" if day == now.date() else "tomorrow" if day == now.date() + timedelta(days=1) else day.strftime("%A %-d %B")
				return {"name": self.timetable_name, "day": label, "columns": columns, "now": now}
		return None
