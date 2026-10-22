"""timeguessr.com daily challenge: five photos; guess where (a pin on the map) and when (a year).

Same mechanics as catfishing.py: one shared game per day, clicks arrive in action(). The rounds
come from the daily challenge page itself (its "playArray"), the photos are downloaded to the
cache, and the scoring copies the site's (up to 5000 points for the year and 5000 for the place,
per round). The map is Leaflet (static/widgets.js), with tiles through the slideshow (maptiles.py).
"""

from __future__ import annotations

import json
import logging
import math
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import requests

from ..slides import Provider, Slide, media_url
from .puzzles import HighScores, PuzzleStatus, load_state, save_state

log = logging.getLogger(__name__)

DAILY_URL = "https://timeguessr.com/play?mode=daily"
HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"}
MAX_POINTS = 5000   # for the year, and again for the place, per round
TILES = "/tiles/{z}/{x}/{y}.png"   # served by the slideshow, see maptiles.py


def js_round(x: float) -> int:
	"""Math.round in JavaScript: halves go up (Python's round() goes to the even number)."""
	return math.floor(x + 0.5)


def year_points(off: int, version: int = 1) -> int:
	"""Points for a year guess `off` years from the answer, as on timeguessr.com."""
	off = abs(off)
	if version == 2:
		return js_round(5000 / (1 + (off / 12) ** 2))
	for limit, points in [(0, 5000), (1, 4950), (2, 4800), (3, 4600), (4, 4300), (5, 3900),
			(7, 3400), (10, 2500), (15, 2000), (20, 1000)]:
		if off <= limit:
			return points
	return 0


def place_points(metres: float, version: int = 1) -> int:
	"""Points for a pin `metres` from the answer, as on timeguessr.com."""
	if version == 2:
		km = max(0, metres / 1000 - 0.05)
		return js_round(5000 * math.exp(-((km / 6000) ** 0.62) - (km / 3000) ** 1.5))
	if metres <= 50:
		return 5000
	for limit, start, per_metre in [(1e3, 5000, 0.02), (5e3, 4980, 0.016), (1e5, 4900, 0.004),
			(1e6, 4500, 0.001), (2e6, 3500, 5e-4), (3e6, 2500, 33333e-8), (6e6, 1500, 2e-4)]:
		if metres <= limit:
			return js_round(start - metres * per_metre)
	return 12


def distance(a: tuple[float, float], b: tuple[float, float]) -> float:
	"""Metres between two (lat, lng) points, the way the site works it out (haversine)."""
	d_lat, d_lng = math.radians(b[0] - a[0]), math.radians(b[1] - a[1])
	h = math.sin(d_lat / 2) ** 2 + math.cos(math.radians(a[0])) * math.cos(math.radians(b[0])) * math.sin(d_lng / 2) ** 2
	return 6371 * 2 * math.atan2(math.sqrt(h), math.sqrt(1 - h)) * 1000


def js_to_json(text: str) -> str:
	"""A JavaScript object literal ({No:"1",Location:{lat:-.2}}) as JSON: quote the keys and write
	numbers like -.2 as -0.2. Text inside strings is left alone."""
	out, i = [], 0
	while i < len(text):
		c = text[i]
		if c == '"':   # a string, with its escapes, as is
			end = i + 1
			while text[end] != '"':
				end += 2 if text[end] == "\\" else 1
			out.append(text[i:end + 1])
			i = end + 1
		elif key := re.match(r"[A-Za-z_$][\w$]*(?=\s*:)", text[i:]):
			out.append(f'"{key.group()}"')
			i += key.end()
		elif number := re.match(r"-?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?", text[i:]):   # a whole number at once
			out.append(re.sub(r"^(-?)\.", r"\g<1>0.", number.group()).rstrip("."))
			i += number.end()
		else:
			out.append(c)
			i += 1
	return "".join(out)


@dataclass
class Photo:
	number: str          # the daily challenge number, e.g. "1235"
	image_id: str
	url: str             # on images.timeguessr.com
	year: int
	lat: float
	lng: float
	description: str
	credit: str
	country: str
	scoring: int = 1     # the site's scoring version
	image: str = ""      # the downloaded copy, as a /files/ url


def parse_daily(html: str) -> list[Photo]:
	"""The photos of the daily challenge from its page."""
	start = html.find("playArray:[")
	if start < 0:
		raise ValueError("No playArray on the daily challenge page; did the website change?")
	start += len("playArray:")
	depth = 0
	for end in range(start, len(html)):
		depth += {"[": 1, "]": -1}.get(html[end], 0)
		if depth == 0:
			break
	return [Photo(
		number=str(item["No"]),
		image_id=item["ImageId"],
		url=item["URL"],
		year=int(item["Year"]),
		lat=float(item["Location"]["lat"]),
		lng=float(item["Location"]["lng"]),
		description=item.get("Description", ""),
		credit=item.get("License", ""),
		country=item.get("Country", ""),
		scoring=int(item.get("scoringVersion") or 1),
	) for item in json.loads(js_to_json(html[start:end + 1])) if isinstance(item, dict)]   # the list ends in a 0


@dataclass
class Guess:
	lat: float
	lng: float
	year: int
	metres: float
	year_points: int
	place_points: int

	@property
	def points(self) -> int:
		return self.year_points + self.place_points

	@property
	def distance(self) -> str:
		"""850 m, 4.2 km, 1,234 km"""
		if self.metres < 1000:
			return f"{self.metres:.0f} m"
		km = self.metres / 1000
		return f"{km:.1f} km" if km < 10 else f"{km:,.0f} km"


@dataclass
class Game:
	number: str
	photos: list[Photo]
	guesses: list[Guess] = field(default_factory=list)
	showing_answer: bool = False   # the last answer is on screen until someone presses Next

	@property
	def done(self) -> bool:
		return len(self.guesses) == len(self.photos) and not self.showing_answer

	@property
	def score(self) -> int:
		return sum(guess.points for guess in self.guesses)

	@property
	def photo(self) -> Photo | None:
		index = len(self.guesses) - (1 if self.showing_answer else 0)
		return self.photos[index] if index < len(self.photos) else None

	def act(self, name: str, values: list[str]) -> str | None:
		"""'guess' with values ["lat,lng", "year"], or 'next'. Returns a message, if any."""
		if name == "next" and self.showing_answer:
			self.showing_answer = False
		elif name == "guess" and not self.showing_answer and not self.done:
			try:
				lat, lng = (float(part) for part in values[0].split(","))
				year = int(values[1])
			except (IndexError, ValueError):
				return "Tap the map to place your pin first"
			photo = self.photo
			metres = distance((lat, lng), (photo.lat, photo.lng))
			self.guesses.append(Guess(lat, lng, year, metres, year_points(year - photo.year, photo.scoring),
				place_points(metres, photo.scoring)))
			self.showing_answer = True
		return None


class TimeGuessrProvider(Provider):
	name = "timeguessr"
	title = "TimeGuessr"

	def __init__(self, settings: dict, default_seconds: float, cache_folder: Path, state_path: Path | None = None,
			attribution: str = "", highscores: HighScores | None = None) -> None:
		self.state_path = state_path   # where today's game is saved, so it survives a restart
		self.highscores = highscores or HighScores(None)
		self.cache_folder = cache_folder
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("refresh_minutes", 30) * 60
		self.first_year = settings.get("first_year", 1900)
		self.attribution = attribution   # of the map tiles
		self.photos: list[Photo] = []
		self.game: Game | None = None

	def refresh(self, now: datetime) -> None:
		"""Check for a new daily challenge (the site starts one every day) and download its photos."""
		response = requests.get(DAILY_URL, headers=HEADERS, timeout=30)
		response.raise_for_status()
		photos = parse_daily(response.text)
		if not photos:
			raise ValueError("The daily challenge has no photos")
		if self.photos and photos[0].number == self.photos[0].number:
			return
		self.cache_folder.mkdir(parents=True, exist_ok=True)
		for photo in photos:
			path = self.cache_folder / (photo.image_id + Path(photo.url).suffix.lower())
			if not path.exists():
				image = requests.get(photo.url, headers=HEADERS, timeout=60)
				image.raise_for_status()
				path.write_bytes(image.content)
			photo.image = media_url(path)
		for old in self.cache_folder.iterdir():   # the photos of older challenges
			if not any(old.name.startswith(photo.image_id) for photo in photos):
				old.unlink()
		self.photos = photos
		log.info("Loaded TimeGuessr daily challenge #%s", photos[0].number)

	def todays_game(self, now: datetime) -> Game | None:
		if not self.photos:
			return None
		number = self.photos[0].number
		if self.game is None or self.game.number != number:
			self.game = Game(number, self.photos)   # a new challenge: a new game...
			saved = load_state(self.state_path, now.date())   # ...unless it was saved before a restart
			if saved and saved.get("number") == number and len(saved["guesses"]) <= len(self.photos):
				self.game.guesses = [Guess(**guess) for guess in saved["guesses"]]
				self.game.showing_answer = saved["showing_answer"] and bool(self.game.guesses)
		return self.game

	def status(self, now: datetime) -> PuzzleStatus | None:
		game = self.todays_game(now)
		if game is None:
			return None
		total = MAX_POINTS * 2 * len(game.photos)
		self.check_highscore(game, now)
		best = self.highscores.text(self.name)
		if game.done:
			return PuzzleStatus("solved", f"Done: {game.score:,} of {total:,} points", best)
		if game.guesses:
			return PuzzleStatus("playing", f"{len(game.guesses)} of {len(game.photos)} photos · {game.score:,} points", best)
		return PuzzleStatus("new", "Not tried yet", best)

	def check_highscore(self, game: Game, now: datetime) -> None:
		if game.done:
			self.highscores.record(self.name, game.score, now.date())

	def slides(self, now: datetime) -> list[Slide]:
		game = self.todays_game(now)
		if game is None:
			return []
		number = len(game.guesses) + (0 if game.showing_answer else 1)
		last_year = now.year
		return [Slide("timeguessr.html", self.seconds, {
			"game": game,
			"photo": game.photo,
			"last": game.guesses[-1] if game.guesses else None,
			"number": min(number, len(game.photos)),
			"total_points": MAX_POINTS * 2 * len(game.photos),
			"round_points": MAX_POINTS * 2,
			"first_year": min([self.first_year] + [photo.year for photo in game.photos]),
			"last_year": last_year,
			"start_year": (self.first_year + last_year) // 2,
			"tiles": TILES,
			"attribution": self.attribution,
			"summary": list(zip(game.photos, game.guesses)) if game.done else [],
			"highscore": self.highscores.best(self.name, now.date()) if game.done else None,
		})]

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		game = self.todays_game(now)
		if game is None:
			return None, None
		message = game.act(name, values)
		self.check_highscore(game, now)
		save_state(self.state_path, now.date(), {"number": game.number, "showing_answer": game.showing_answer,
			"guesses": [guess.__dict__ for guess in game.guesses]})
		slides = self.slides(now)
		return (slides[0] if slides else None), message
