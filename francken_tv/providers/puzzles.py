"""The "Daily puzzles" slide: one half per puzzle (Connections | Wordle) with today's status.

Tapping a half opens that puzzle on the spot; its "All puzzles" button comes back here.
To add a puzzle: write a provider with a `title`, a `status(now)` method and an interactive
slide (see connections.py), create it in app.py and add its name to puzzles.order in config.toml.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from ..slides import Provider, Slide

log = logging.getLogger(__name__)


@dataclass
class PuzzleStatus:
	state: str     # "new", "playing", "solved" or "lost"
	text: str      # e.g. "2 of 4 groups"


def load_state(path: Path | None, day: date) -> dict | None:
	"""Today's saved game (see save_state), or None: nothing saved, saved on another day, or unreadable."""
	if path is None or not path.exists():
		return None
	try:
		state = json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError) as error:
		log.warning("Ignoring unreadable saved game %s: %s", path, error)
		return None
	return state if state.get("day") == day.isoformat() else None


def save_state(path: Path | None, day: date, state: dict) -> None:
	"""Save a game so it survives a restart of the slideshow (data/puzzles/<puzzle>.json)."""
	if path is None:
		return
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = path.with_suffix(".tmp")
	temporary.write_text(json.dumps({"day": day.isoformat(), **state}), encoding="utf-8")
	temporary.replace(path)   # in one go, so a restart while saving can't leave half a file


class PuzzlesProvider(Provider):
	name = "puzzles"

	def __init__(self, settings: dict, puzzles: list[Provider], default_seconds: float) -> None:
		self.puzzles = puzzles
		self.seconds = settings.get("seconds", default_seconds)
		self.refresh_seconds = min(puzzle.refresh_seconds for puzzle in puzzles) if puzzles else None

	def refresh(self, now: datetime) -> None:
		"""Refresh every puzzle; one that fails (e.g. the NYT is down) doesn't stop the others."""
		failed = []
		for puzzle in self.puzzles:
			try:
				puzzle.refresh(now)
			except Exception as error:
				log.warning("Could not load the %s puzzle: %s", puzzle.name, error)
				failed.append(f"{puzzle.name}: {error!r}")
		if failed:
			raise RuntimeError("; ".join(failed))

	def slides(self, now: datetime) -> list[Slide]:
		cards = []
		for puzzle in self.puzzles:
			status = puzzle.status(now)
			if status is not None:   # None: today's puzzle couldn't be downloaded
				cards.append({"name": puzzle.name, "title": puzzle.title, "state": status.state, "status": status.text})
		if not cards:
			return []
		return [Slide("puzzles.html", self.seconds, {"cards": cards})]

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""'open' a puzzle (values = [its name]) or go 'back' to this overview."""
		if name == "open":
			puzzle = next((p for p in self.puzzles if values and p.name == values[0]), None)
			slides = puzzle.slides(now) if puzzle else []
			if slides:
				return slides[0], None
		slides = self.slides(now)
		return (slides[0] if slides else None), None
