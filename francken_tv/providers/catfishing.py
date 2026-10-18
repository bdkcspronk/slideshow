"""catfishing.net: guess the Wikipedia article from its categories. Ten articles a day.

Same mechanics as connections.py: one shared game per day, clicks and typing arrive in action().
The puzzle comes from the JSON the catfishing.net game page itself loads; the answer checking
below copies the site's rules (normalising, "Did you mean ...?" for typos, "close enough").
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from ..slides import Provider, Slide
from .puzzles import PuzzleStatus, load_state, save_state

log = logging.getLogger(__name__)

GAME_URL = "https://catfishing.net/app/game"
FIRST_DAY = date(2024, 6, 23)   # day 0 of catfishing.net
ARCHIVE_START = date(2024, 7, 1)   # the first day catfishing.net still has (day 8)
ARCHIVE_DAYS_KEPT = 5            # downloaded days kept in memory
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
			if self.did_you_mean is None:
				return {}   # a click on an old copy of the slide (e.g. after skipping back)
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
	"""Today's game, plus any earlier day from catfishing.net's archive ("Archive": a month calendar).
	Every day played is kept in history_path, so the calendar shows which days are done (and their
	score) or started, and an archive day can be finished later. Today's game also has its own save
	file (state_path), which "start over" in the menu removes."""

	name = "catfishing"
	title = "Catfishing"

	def __init__(self, settings: dict, default_seconds: float, state_path: Path | None = None,
			history_path: Path | None = None) -> None:
		self.state_path = state_path   # where today's game is saved, so it survives a restart
		self.history_path = history_path
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = settings.get("refresh_minutes", 30) * 60
		self.games: dict[date, list[Article]] = {}   # downloaded days (today, and archive days opened)
		self.game: Game | None = None                # today's
		self.archive_game: Game | None = None        # an earlier day being played
		self.day_shown: date | None = None           # whose game the buttons act on
		self.history = self.load_history()

	@staticmethod
	def day_number(day: date) -> int:
		return (day - FIRST_DAY).days

	def fetch(self, day: date) -> list[Article]:
		response = requests.get(GAME_URL, params={"day": self.day_number(day)}, timeout=30,
			headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
		response.raise_for_status()
		return parse_game(response.json())

	def articles(self, day: date) -> list[Article]:
		"""A day's articles, downloaded once (raises if catfishing.net can't be reached)."""
		if day not in self.games:
			self.games[day] = self.fetch(day)
			for old in sorted(self.games)[:-ARCHIVE_DAYS_KEPT]:   # only the last few days opened
				del self.games[old]
		return self.games[day]

	def refresh(self, now: datetime) -> None:
		"""Download today's ten articles once; afterwards this does nothing until tomorrow."""
		if now.date() not in self.games:
			self.articles(now.date())
			log.info("Loaded the catfishing game of %s", now.date())

	# -- history: every day played --

	def load_history(self) -> dict[str, dict]:
		if self.history_path is None or not self.history_path.exists():
			return {}
		try:
			return json.loads(self.history_path.read_text(encoding="utf-8"))
		except (OSError, ValueError) as error:
			log.warning("Ignoring unreadable catfishing history %s: %s", self.history_path, error)
			return {}

	def record(self, game: Game) -> None:
		self.history[game.day.isoformat()] = {"answers": [[a.result, a.guess] for a in game.answers],
			"showing_answer": game.showing_answer, "total": len(game.articles), "score": game.score}
		if self.history_path is None:
			return
		self.history_path.parent.mkdir(parents=True, exist_ok=True)
		temporary = self.history_path.with_suffix(".tmp")
		temporary.write_text(json.dumps(self.history, indent=1, sort_keys=True), encoding="utf-8")
		temporary.replace(self.history_path)   # in one go, so a restart while saving can't leave half a file

	def restore(self, game: Game, saved: dict | None) -> Game:
		if saved and len(saved["answers"]) <= len(game.articles):
			game.answers = [Answer(result, guess) for result, guess in saved["answers"]]
			game.showing_answer = saved["showing_answer"] and bool(game.answers)
		return game

	def todays_game(self, now: datetime) -> Game | None:
		articles = self.games.get(now.date())
		if articles is None:
			return None
		if self.game is None or self.game.day != now.date():
			saved = load_state(self.state_path, now.date())   # saved before a restart
			if saved is None and self.history.pop(now.date().isoformat(), None) is not None:
				self.record_removed()   # today was started over (menu): it's not played any more
			self.game = self.restore(Game(now.date(), articles), saved)   # a new day: a new game
		return self.game

	def record_removed(self) -> None:
		if self.history_path is not None and self.history_path.exists():
			self.history_path.write_text(json.dumps(self.history, indent=1, sort_keys=True), encoding="utf-8")

	def shown_game(self, now: datetime) -> Game | None:
		if self.day_shown is not None and self.day_shown != now.date() and self.archive_game and self.archive_game.day == self.day_shown:
			return self.archive_game
		return self.todays_game(now)

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

	# -- slides --

	def slides(self, now: datetime, typed: str = "") -> list[Slide]:
		game = self.todays_game(now)
		if game is None:
			return []
		self.day_shown = now.date()
		return [self.game_slide(game, now, typed)]

	def game_slide(self, game: Game, now: datetime, typed: str = "") -> Slide:
		number = len(game.answers) + (0 if game.showing_answer else 1)
		return Slide("catfishing.html", self.seconds, {
			"game": game,
			"article": game.article,
			"number": min(number, len(game.articles)),
			"last": game.answers[-1] if game.answers else None,
			"typed": typed,
			"total_points": 2 * len(game.articles),
			"results": [answer.result for answer in game.answers] + ["open"] * (len(game.articles) - len(game.answers)),
			"summary": list(zip(game.articles, game.answers)) if game.done else [],
			"today": game.day == now.date(),
			"day_label": game.day.strftime("%-d %b %Y"),
		})

	def day_status(self, day: date, now: datetime) -> dict:
		"""How far a day got: {"state": "done"/"playing"/"new", "text": "14/20" or "3/10"}."""
		saved = self.history.get(day.isoformat())
		if not saved or not saved["answers"]:
			return {"state": "new", "text": ""}
		total = saved.get("total", 10)
		if len(saved["answers"]) == total and not saved["showing_answer"]:
			return {"state": "done", "text": f"{saved.get('score', 0)}/{2 * total}"}
		return {"state": "playing", "text": f"{len(saved['answers'])}/{total}"}

	def archive_slide(self, month: date, now: datetime, error: str = "") -> Slide:
		"""A month calendar of catfishing.net's days: done (with the score), started, or not played."""
		month = max(min(month.replace(day=1), now.date().replace(day=1)), ARCHIVE_START.replace(day=1))
		first = month - timedelta(days=month.weekday())   # the Monday the calendar starts on
		next_month = (month + timedelta(days=32)).replace(day=1)
		weeks = []
		day = first
		while day < next_month:
			week = []
			for _ in range(7):
				playable = ARCHIVE_START <= day <= now.date()
				week.append({"date": day, "in_month": day.month == month.month, "playable": playable,
					"today": day == now.date(), **(self.day_status(day, now) if playable else {"state": "", "text": ""})})
				day += timedelta(days=1)
			weeks.append(week)
		statuses = [self.day_status(date.fromisoformat(iso), now)["state"] for iso in self.history]
		previous_month = (month - timedelta(days=1)).replace(day=1)
		return Slide("catfishing_archive.html", self.seconds, {
			"month": month, "weeks": weeks, "error": error,
			"previous": previous_month.strftime("%Y-%m") if previous_month >= ARCHIVE_START.replace(day=1) else None,
			"next": next_month.strftime("%Y-%m") if next_month <= now.date() else None,
			"done": statuses.count("done"), "started": statuses.count("playing"),
			"days": (now.date() - ARCHIVE_START).days + 1,
		})

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""'archive' shows a month (values: ["2026-09"]), 'open_day' plays a day (["2026-09-14"]),
		'today' goes back to today's game; the rest are moves in the game on screen (Game.act)."""
		if name == "archive":
			try:
				month = date.fromisoformat(values[0] + "-01")
			except (IndexError, ValueError):
				month = self.day_shown or now.date()
			return self.archive_slide(month, now), None
		if name == "open_day" and values:
			try:
				day = date.fromisoformat(values[0])
			except ValueError:
				return None, None
			if day == now.date() or not ARCHIVE_START <= day < now.date():
				return self.action("today", [], now)
			try:
				articles = self.articles(day)
			except requests.RequestException as error:
				log.warning("Could not load the catfishing game of %s: %s", day, error)
				return self.archive_slide(day, now, error=f"The game of {day:%-d %B} can't be loaded right now."), None
			if not (self.archive_game and self.archive_game.day == day):
				self.archive_game = self.restore(Game(day, articles), self.history.get(day.isoformat()))
			self.day_shown = day
			return self.game_slide(self.archive_game, now), None
		if name == "today":
			slides = self.slides(now)
			return (slides[0] if slides else None), None
		game = self.shown_game(now)
		if game is None:
			return None, None
		result = game.act(name, values)
		if game.day == now.date():
			save_state(self.state_path, game.day, {"answers": [[a.result, a.guess] for a in game.answers],
				"showing_answer": game.showing_answer})
		if game.answers or game.day.isoformat() in self.history:
			self.record(game)
		return self.game_slide(game, now, typed=result.get("typed", "")), result.get("message")
