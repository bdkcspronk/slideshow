"""The New York Times "Connections" puzzle of the day, with yesterday's answers.

The puzzle comes from the JSON the NYT game page itself loads. If that ever changes,
only parse_puzzle() needs fixing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta

import requests

from ..slides import Provider, Slide

log = logging.getLogger(__name__)

PUZZLE_URL = "https://www.nytimes.com/svc/connections/v2/{day}.json"


@dataclass
class Puzzle:
	day: date
	words: list[str]                       # in the starting order of the 4x4 grid
	groups: list[tuple[str, list[str]]]    # (category, words), easiest (yellow) to hardest (purple)


def parse_puzzle(data: dict) -> Puzzle:
	cards = [card for category in data["categories"] for card in category["cards"]]
	return Puzzle(
		day=date.fromisoformat(data["print_date"]),
		words=[card["content"] for card in sorted(cards, key=lambda card: card["position"])],
		groups=[(category["title"], [card["content"] for card in category["cards"]]) for category in data["categories"]],
	)


class ConnectionsProvider(Provider):
	name = "connections"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.seconds = settings.get("seconds", default_seconds)
		self.show_yesterday = settings.get("show_yesterday", True)
		self.refresh_seconds = settings.get("refresh_minutes", 30) * 60
		self.puzzles: dict[date, Puzzle] = {}

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

	def slides(self, now: datetime) -> list[Slide]:
		today = self.puzzles.get(now.date())
		if today is None:
			return []
		yesterday = self.puzzles.get(now.date() - timedelta(days=1)) if self.show_yesterday else None
		return [Slide("connections.html", self.seconds, {"today": today, "yesterday": yesterday})]
