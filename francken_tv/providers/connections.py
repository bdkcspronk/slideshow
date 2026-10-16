"""The New York Times "Connections" puzzle of the day, playable on the TV, with yesterday's answers.

The puzzle comes from the JSON the NYT game page itself loads. If that ever changes,
only parse_puzzle() needs fixing.

There is one shared game per day: progress stays when the slideshow moves on, and a new
game starts with the new puzzle at midnight. Clicks arrive in action() (see server.py).
"""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

import requests

from ..slides import Provider, Slide
from .puzzles import PuzzleStatus, load_state, save_state

log = logging.getLogger(__name__)

PUZZLE_URL = "https://www.nytimes.com/svc/connections/v2/{day}.json"
MAX_MISTAKES = 4
WIN_MESSAGES = ["Perfect!", "Great!", "Solid!", "Phew!"]   # by number of mistakes


@dataclass
class Puzzle:
	day: date
	words: list[str]                       # in the starting order of the 4x4 grid
	groups: list[tuple[str, list[str]]]    # (category, words), easiest (yellow) to hardest (purple)


@dataclass
class Game:
	puzzle: Puzzle
	order: list[str]                                   # words still on the board, in grid order
	found: list[int] = field(default_factory=list)     # indices into puzzle.groups, in the order found
	mistakes: int = 0
	guesses: set[frozenset[str]] = field(default_factory=set)

	@property
	def won(self) -> bool:
		return len(self.found) == len(self.puzzle.groups)

	@property
	def lost(self) -> bool:
		return self.mistakes >= MAX_MISTAKES

	def guess(self, words: list[str]) -> dict:
		"""Check four words. Returns what to show: a message, and whether to keep the selection."""
		chosen = set(words)
		if self.won or self.lost or len(chosen) != 4 or not chosen <= set(self.order):
			return {}
		if frozenset(chosen) in self.guesses:
			return {"message": "Already guessed!", "selected": words}
		self.guesses.add(frozenset(chosen))

		for index, (_title, group) in enumerate(self.puzzle.groups):
			if set(group) == chosen:
				self.found.append(index)
				self.remove_into_top_row(chosen)
				result = {"new_group": index}
				if self.won:
					result["message"] = WIN_MESSAGES[self.mistakes]
				return result

		self.mistakes += 1
		if self.lost:
			return {"message": "Next time!"}
		closest = max(len(chosen & set(group)) for index, (_title, group) in enumerate(self.puzzle.groups) if index not in self.found)
		return {"message": "One away..." if closest == 3 else "Not quite", "selected": words, "shake": True}


	def remove_into_top_row(self, chosen: set[str]) -> None:
		"""Like on the NYT page: the found words swap places with the other words in the top row
		(in reading order), and then the top row becomes the coloured bar. player.js animates the
		same swap, so the board after the animation matches."""
		order = list(self.order)
		moving_up = [word for word in order[4:] if word in chosen]
		making_room = [word for word in order[:4] if word not in chosen]
		for up, down in zip(moving_up, making_room):
			i, j = order.index(up), order.index(down)
			order[i], order[j] = order[j], order[i]
		self.order = order[4:]


def parse_puzzle(data: dict) -> Puzzle:
	cards = [card for category in data["categories"] for card in category["cards"]]
	return Puzzle(
		day=date.fromisoformat(data["print_date"]),
		words=[card["content"] for card in sorted(cards, key=lambda card: card["position"])],
		groups=[(category["title"], [card["content"] for card in category["cards"]]) for category in data["categories"]],
	)


class ConnectionsProvider(Provider):
	name = "connections"
	title = "Connections"

	def __init__(self, settings: dict, default_seconds: float, state_path: Path | None = None) -> None:
		self.state_path = state_path   # where today's game is saved, so it survives a restart
		self.seconds = settings.get("seconds", default_seconds)
		self.show_yesterday = settings.get("show_yesterday", True)
		self.refresh_seconds = settings.get("refresh_minutes", 30) * 60
		self.puzzles: dict[date, Puzzle] = {}
		self.game: Game | None = None

	def fetch(self, day: date) -> Puzzle:
		response = requests.get(PUZZLE_URL.format(day=day.isoformat()), timeout=30, headers={"User-Agent": "Mozilla/5.0"})
		response.raise_for_status()
		return parse_puzzle(response.json())

	def refresh(self, now: datetime) -> None:
		"""Download today's (and yesterday's) puzzle once; afterwards this does nothing until tomorrow."""
		wanted = [now.date()] + ([now.date() - timedelta(days=1)] if self.show_yesterday else [])
		for day in wanted:
			if day not in self.puzzles:
				self.puzzles[day] = self.fetch(day)
				log.info("Loaded the Connections puzzle of %s", day)
		self.puzzles = {day: puzzle for day, puzzle in self.puzzles.items() if day in wanted}

	def todays_game(self, now: datetime) -> Game | None:
		puzzle = self.puzzles.get(now.date())
		if puzzle is None:
			return None
		if self.game is None or self.game.puzzle is not puzzle:
			self.game = Game(puzzle, list(puzzle.words))   # a new day: a new game...
			saved = load_state(self.state_path, puzzle.day)   # ...unless it was saved before a restart
			if saved and sorted(saved["order"] + [w for i in saved["found"] for w in puzzle.groups[i][1]]) == sorted(puzzle.words):
				self.game.order, self.game.found, self.game.mistakes = saved["order"], saved["found"], saved["mistakes"]
				self.game.guesses = {frozenset(guess) for guess in saved["guesses"]}
		return self.game

	def save(self) -> None:
		game = self.game
		save_state(self.state_path, game.puzzle.day, {"order": game.order, "found": game.found,
			"mistakes": game.mistakes, "guesses": [sorted(guess) for guess in game.guesses]})

	def status(self, now: datetime) -> PuzzleStatus | None:
		"""For the Daily puzzles slide. None if today's puzzle isn't available."""
		game = self.todays_game(now)
		if game is None:
			return None
		if game.won:
			return PuzzleStatus("solved", "Solved")
		if game.lost:
			return PuzzleStatus("lost", f"Lost: {len(game.found)} of 4 groups found")
		if game.found or game.mistakes:
			return PuzzleStatus("playing", f"{len(game.found)} of 4 groups found")
		return PuzzleStatus("new", "Not tried yet")

	def slides(self, now: datetime, selected: list[str] | None = None, shake: bool = False,
			new_group: int | None = None) -> list[Slide]:
		game = self.todays_game(now)
		if game is None:
			return []
		puzzle = game.puzzle
		# Found groups first; after a loss, also the groups nobody found.
		shown = game.found + ([i for i in range(len(puzzle.groups)) if i not in game.found] if game.lost else [])
		yesterday = self.puzzles.get(now.date() - timedelta(days=1)) if self.show_yesterday else None
		return [Slide("connections.html", self.seconds, {
			"groups": [(index, *puzzle.groups[index]) for index in shown],
			"words": [] if game.lost else game.order,
			"mistakes_left": MAX_MISTAKES - game.mistakes,
			"finished": game.won or game.lost,
			"selected": selected or [],
			"shake": shake,
			"new_group": new_group,   # just found: player.js animates it into place
			"yesterday": yesterday,
		})]

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""A button on the slide was clicked. Returns the redrawn slide and a message to show."""
		game = self.todays_game(now)
		if game is None:
			return None, None
		result = {}
		if name == "submit":
			result = game.guess(values)
		elif name == "shuffle":
			random.shuffle(game.order)
		self.save()
		slides = self.slides(now, selected=result.get("selected"), shake=result.get("shake", False),
			new_group=result.get("new_group"))
		return (slides[0] if slides else None), result.get("message")
