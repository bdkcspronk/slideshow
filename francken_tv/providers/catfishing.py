"""catfishing.net: guess the Wikipedia article from its categories. Ten articles a day.

Same mechanics as connections.py: one shared game per day, clicks and typing arrive in action().
The puzzle comes from the JSON the catfishing.net game page itself loads; the answer checking
below copies the site's rules (normalising, "Did you mean ...?" for typos, "close enough").
"""

from __future__ import annotations

import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime

import requests

from ..slides import Provider, Slide
from .puzzles import PuzzleStatus

log = logging.getLogger(__name__)

GAME_URL = "https://catfishing.net/app/game"
FIRST_DAY = date(2024, 6, 23)   # day 0 of catfishing.net
POINTS = {"correct": 2, "close": 1, "incorrect": 0, "skipped": 0}
# How many typos still count as "Did you mean ...?", by the length of the name (as on the site).
TYPO_LIMITS = [(18, 4), (12, 3), (7, 2), (4, 1)]
NUMBERS = re.compile(r"\d+|\b[ivx]+(?=$| of | and )")   # years and roman numerals must match exactly


def normalise(text: str) -> str:
	"""'The Beatles (band)' -> 'beatles band'... the same way catfishing.net compares answers."""
	text = re.sub(r"\(.*\)", "", text).replace("&", " and ")
	text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c)).lower()
	text = re.sub(r"\s\s+", " ", re.sub(r"[^\w\s]+", "", text, flags=re.ASCII)).strip()   # \w: a-z, 0-9, _ only
	return re.sub(r"^(?:a|an|teh|the|thr)\s", "", text)


def edit_distance(a: str, b: str) -> int:
	previous = list(range(len(b) + 1))
	for i, ca in enumerate(a, 1):
		current = [i]
		for j, cb in enumerate(b, 1):
			current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
		previous = current
	return previous[-1]


def close_typo(guess: str, name: str) -> int | None:
	"""The number of typos if `guess` is a near miss of `name`, else None."""
	longest = max(len(guess), len(name))
	limit = next((limit for length, limit in TYPO_LIMITS if longest >= length), 0)
	if limit == 0 or abs(len(guess) - len(name)) > limit:
		return None
	if NUMBERS.findall(name) and NUMBERS.findall(guess) != NUMBERS.findall(name):
		return None
	distance = edit_distance(guess, name)
	return distance if distance <= limit else None


@dataclass
class Article:
	title: str
	categories: list[str]
	names: dict[str, str]      # normalised name -> how to show it
	veto: list[str]            # normalised names that never count
	extract: str = ""
	image: str | None = None
	image_credit: str = ""

	def check(self, guess: str) -> tuple[str, str | None]:
		"""('correct', name), ('did_you_mean', name) or ('incorrect', None)."""
		normalised = normalise(guess)
		if not normalised:
			return "incorrect", None
		if normalised in self.names:
			return "correct", self.names[normalised]
		if len(normalised) < 4 or normalised in self.veto:
			return "incorrect", None
		if close_typo(normalised, normalise(self.title)) is not None:
			return "did_you_mean", self.title
		near = [(distance, shown) for name, shown in self.names.items() if (distance := close_typo(normalised, name)) is not None]
		return ("did_you_mean", min(near)[1]) if near else ("incorrect", None)


def parse_game(data: dict) -> list[Article]:
	articles = []
	for article, preview in zip(data["articles"], data.get("previews") or [{}] * len(data["articles"])):
		preview = preview or {}
		thumbnail = preview.get("thumbnail") or {}
		names: dict[str, str] = {}
		for name in [article["title"], *article.get("names", [])]:   # the title first, so it wins
			if normalise(name):
				names.setdefault(normalise(name), name)
		articles.append(Article(
			title=article["title"],
			categories=article["categories"],
			names=names,
			veto=[normalise(name) for name in article.get("namesVeto") or []],
			extract=preview.get("extract", ""),
			image=thumbnail.get("url"),
			image_credit=" · ".join(part for part in [thumbnail.get("artist"), thumbnail.get("licenseShortName")] if part),
		))
	return articles


@dataclass
class Answer:
	result: str        # "correct", "close", "incorrect" or "skipped"
	guess: str = ""


@dataclass
class Game:
	day: date
	articles: list[Article]
	answers: list[Answer] = field(default_factory=list)
	showing_answer: bool = False          # the last answer is on screen until someone presses Next
	did_you_mean: str | None = None       # waiting for "Did you mean ...?" yes/no
	pending_guess: str = ""

	@property
	def done(self) -> bool:
		return len(self.answers) == len(self.articles) and not self.showing_answer

	@property
	def score(self) -> int:
		return sum(POINTS[answer.result] for answer in self.answers)

	@property
	def article(self) -> Article | None:
		index = len(self.answers) - (1 if self.showing_answer else 0)
		return self.articles[index] if index < len(self.articles) else None

	def answer(self, result: str, guess: str = "") -> None:
		self.answers.append(Answer(result, guess))
		self.showing_answer = True
		self.did_you_mean = None

	def act(self, name: str, values: list[str]) -> dict:
		if name == "next" and self.showing_answer:
			self.showing_answer = False
		elif name == "close" and self.showing_answer and self.answers[-1].result in ("incorrect", "close"):
			last = self.answers[-1]
			last.result = "incorrect" if last.result == "close" else "close"   # honour system, like the site
		elif self.showing_answer or self.done:
			return {}
		elif name == "skip":
			self.answer("skipped")
		elif name == "did_you_mean":
			if values and values[0] == "yes":
				self.answer("correct", self.pending_guess)
			else:
				self.did_you_mean = None
				return {"typed": self.pending_guess}   # back to typing, nothing lost
		elif name == "submit":
			guess = (values[0] if values else "").strip()
			if not guess:
				return {"message": "Type a guess, or skip"}
			result, matched = self.article.check(guess)
			if result == "did_you_mean":
				self.did_you_mean, self.pending_guess = matched, guess
			else:
				self.answer(result, guess)
		return {}


class CatfishingProvider(Provider):
	name = "catfishing"
	title = "Catfishing"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("refresh_minutes", 30) * 60
		self.games: dict[date, list[Article]] = {}
		self.game: Game | None = None

	@staticmethod
	def day_number(day: date) -> int:
		return (day - FIRST_DAY).days

	def fetch(self, day: date) -> list[Article]:
		response = requests.get(GAME_URL, params={"day": self.day_number(day)}, timeout=30,
			headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
		response.raise_for_status()
		return parse_game(response.json())

	def refresh(self, now: datetime) -> None:
		"""Download today's ten articles once; afterwards this does nothing until tomorrow."""
		if now.date() not in self.games:
			self.games = {now.date(): self.fetch(now.date())}
			log.info("Loaded the catfishing game of %s", now.date())

	def todays_game(self, now: datetime) -> Game | None:
		articles = self.games.get(now.date())
		if articles is None:
			return None
		if self.game is None or self.game.day != now.date():
			self.game = Game(now.date(), articles)   # a new day: a new game
		return self.game

	def status(self, now: datetime) -> PuzzleStatus | None:
		game = self.todays_game(now)
		if game is None:
			return None
		total = 2 * len(game.articles)
		if game.done:
			return PuzzleStatus("solved", f"Done: {game.score} of {total} points")
		if game.answers:
			points = "point" if game.score == 1 else "points"
			return PuzzleStatus("playing", f"{len(game.answers)} of {len(game.articles)} answered · {game.score} {points}")
		return PuzzleStatus("new", "Not tried yet")

	def slides(self, now: datetime, typed: str = "") -> list[Slide]:
		game = self.todays_game(now)
		if game is None:
			return []
		number = len(game.answers) + (0 if game.showing_answer else 1)
		return [Slide("catfishing.html", self.seconds, {
			"game": game,
			"article": game.article,
			"number": min(number, len(game.articles)),
			"last": game.answers[-1] if game.answers else None,
			"typed": typed,
			"total_points": 2 * len(game.articles),
			"results": [answer.result for answer in game.answers] + ["open"] * (len(game.articles) - len(game.answers)),
			"summary": list(zip(game.articles, game.answers)) if game.done else [],
		})]

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		game = self.todays_game(now)
		if game is None:
			return None, None
		result = game.act(name, values)
		slides = self.slides(now, typed=result.get("typed", ""))
		return (slides[0] if slides else None), result.get("message")
