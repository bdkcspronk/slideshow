"""The New York Times Wordle of the day, playable on the TV, with yesterday's word.

Same mechanics as connections.py: one shared game per day, clicks and key presses arrive in
action(). The solution stays on the server; the browser only gets the coloured letters.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from ..slides import Provider, Slide
from .puzzles import PuzzleStatus, load_state, save_state

log = logging.getLogger(__name__)

PUZZLE_URL = "https://www.nytimes.com/svc/wordle/v2/{day}.json"
MAX_GUESSES = 6
WIN_MESSAGES = ["Genius", "Magnificent", "Impressive", "Splendid", "Great", "Phew"]   # by number of guesses
KEYBOARD = ["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"]
# Guesses must be real words, like on the NYT page. These lists come with Ubuntu (packages
# wamerican, wbritish and cracklib-runtime); without them every 5-letter guess is accepted.
WORD_LISTS = [Path("/usr/share/dict/american-english"), Path("/usr/share/dict/british-english"),
	Path("/usr/share/dict/cracklib-small")]
RANK = {"absent": 1, "present": 2, "correct": 3}


def load_words() -> set[str]:
	words = set()
	for path in WORD_LISTS:
		if path.is_file():
			words.update(line.strip().upper() for line in path.read_text(errors="ignore").splitlines())
	return {word for word in words if len(word) == 5 and word.isalpha() and word.isascii()}


def score(guess: str, solution: str) -> list[str]:
	"""'correct', 'present' or 'absent' per letter, counting repeated letters like the NYT does."""
	result = ["absent"] * 5
	unused = []
	for i, (g, s) in enumerate(zip(guess, solution)):
		if g == s:
			result[i] = "correct"
		else:
			unused.append(s)
	for i, g in enumerate(guess):
		if result[i] != "correct" and g in unused:
			result[i] = "present"
			unused.remove(g)
	return result


def key_states(guesses: list[str], solution: str) -> dict[str, str]:
	"""The colour of each letter on the keyboard: the best result it got in any guess."""
	states: dict[str, str] = {}
	for guess in guesses:
		for letter, state in zip(guess, score(guess, solution)):
			if RANK[state] > RANK.get(states.get(letter, ""), 0):
				states[letter] = state
	return states


@dataclass
class Game:
	day: date
	solution: str
	guesses: list[str] = field(default_factory=list)

	@property
	def won(self) -> bool:
		return bool(self.guesses) and self.guesses[-1] == self.solution

	@property
	def lost(self) -> bool:
		return not self.won and len(self.guesses) >= MAX_GUESSES

	def guess(self, word: str, valid_words: set[str]) -> dict:
		word = word.upper()
		if self.won or self.lost:
			return {}
		if len(word) != 5 or not word.isalpha():
			return {"message": "Not enough letters", "typed": word, "shake": True}
		if valid_words and word not in valid_words and word != self.solution:
			return {"message": "Not in word list", "typed": word, "shake": True}
		self.guesses.append(word)
		result = {"new_row": len(self.guesses) - 1}
		if self.won:
			result["message"] = WIN_MESSAGES[len(self.guesses) - 1]
		elif self.lost:
			result["message"] = self.solution
		return result


class WordleProvider(Provider):
	name = "wordle"
	title = "Wordle"

	def __init__(self, settings: dict, default_seconds: float, state_path: Path | None = None) -> None:
		self.state_path = state_path   # where today's game is saved, so it survives a restart
		self.seconds = settings.get("seconds", default_seconds)
		self.show_yesterday = settings.get("show_yesterday", True)
		self.refresh_seconds = settings.get("refresh_minutes", 30) * 60
		self.solutions: dict[date, str] = {}
		self.game: Game | None = None
		self.valid_words = load_words()

	def fetch(self, day: date) -> str:
		response = requests.get(PUZZLE_URL.format(day=day.isoformat()), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
		response.raise_for_status()
		return response.json()["solution"].upper()

	def refresh(self, now: datetime) -> None:
		"""Download today's (and yesterday's) word once; afterwards this does nothing until tomorrow."""
		wanted = [now.date()] + ([now.date() - timedelta(days=1)] if self.show_yesterday else [])
		for day in wanted:
			if day not in self.solutions:
				self.solutions[day] = self.fetch(day)
				log.info("Loaded the Wordle of %s", day)
		self.solutions = {day: word for day, word in self.solutions.items() if day in wanted}

	def todays_game(self, now: datetime) -> Game | None:
		solution = self.solutions.get(now.date())
		if solution is None:
			return None
		if self.game is None or self.game.day != now.date():
			self.game = Game(now.date(), solution)   # a new day: a new game...
			saved = load_state(self.state_path, now.date())   # ...unless it was saved before a restart
			if saved:
				self.game.guesses = [guess for guess in saved["guesses"] if len(guess) == 5][:MAX_GUESSES]
		return self.game

	def status(self, now: datetime) -> PuzzleStatus | None:
		"""For the Daily puzzles slide. None if today's word isn't available."""
		game = self.todays_game(now)
		if game is None:
			return None
		count = len(game.guesses)
		if game.won:
			return PuzzleStatus("solved", f"Solved in {count} {'guess' if count == 1 else 'guesses'}")
		if game.lost:
			return PuzzleStatus("lost", "Not solved today")
		if count:
			return PuzzleStatus("playing", f"{count} of {MAX_GUESSES} guesses used")
		return PuzzleStatus("new", "Not tried yet")

	def slides(self, now: datetime, typed: str = "", shake: bool = False, new_row: int | None = None) -> list[Slide]:
		game = self.todays_game(now)
		if game is None:
			return []
		finished = game.won or game.lost
		rows = []
		for index in range(MAX_GUESSES):
			if index < len(game.guesses):
				guess = game.guesses[index]
				rows.append({"cells": list(zip(guess, score(guess, game.solution))), "input": False})
			elif index == len(game.guesses) and not finished:
				rows.append({"cells": [(typed[i] if i < len(typed) else "", "") for i in range(5)], "input": True})
			else:
				rows.append({"cells": [("", "")] * 5, "input": False})
		states = key_states(game.guesses, game.solution)
		# Keys that change colour with the newest guess only change after its tiles have flipped.
		before = key_states(game.guesses[:-1], game.solution) if new_row is not None else states
		keyboard = [[(letter, states.get(letter, ""), before.get(letter, "")) for letter in row] for row in KEYBOARD]
		return [Slide("wordle.html", self.seconds, {
			"rows": rows,
			"keyboard": keyboard,
			"new_row": new_row,
			"won": game.won,
			"finished": finished,
			"shake": shake,
			"yesterday": self.solutions.get(now.date() - timedelta(days=1)) if self.show_yesterday else None,
		})]

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""The word typed in the current row was submitted."""
		game = self.todays_game(now)
		if game is None:
			return None, None
		result = game.guess(values[0] if values else "", self.valid_words) if name == "submit" else {}
		save_state(self.state_path, game.day, {"guesses": game.guesses})
		slides = self.slides(now, typed=result.get("typed", ""), shake=result.get("shake", False), new_row=result.get("new_row"))
		return (slides[0] if slides else None), result.get("message")
