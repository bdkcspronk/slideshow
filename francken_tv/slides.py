"""The building blocks: a Slide, and the three kinds of plug-ins.

- Provider: contributes slides to each round of the slideshow (images, activities, ...).
- Takeover: grabs the screen at certain moments (bieruur, vrijmibo).
- Job:      does something at certain moments without a slide (play the bieruur song, greet people).

Slow work (downloading, rendering charts) belongs in Provider.refresh(), which runs in
the background. slides(), slide() and tick() must be fast.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable
from urllib.parse import quote

from .config import PROJECT_DIR


class PartsFailed(RuntimeError):
	"""refresh() of a provider with several parts (puzzles): some failed, the rest worked. Each
	failure is already logged, so the background runner logs this without a traceback."""


@dataclass
class Slide:
	template: str                      # file in francken_tv/templates/slides/
	seconds: float                     # how long it stays on screen
	data: dict = field(default_factory=dict)   # variables available in the template
	update: Callable[[datetime], dict] | None = None   # recomputes `data` while the slide is shown...
	refresh_seconds: float | None = None               # ...this often (e.g. a ticking countdown)
	announce: str | None = None        # quote text to read aloud when the slide appears


class Provider:
	"""Contributes zero or more slides to every round of the slideshow."""

	name = ""
	title = ""                             # shown in the menu (Esc); the name if empty
	nothing_to_show = "Nothing to show right now"   # in the menu and after a shortcut, when slides() is empty
	refresh_seconds: float | None = None   # how often refresh() runs; None = never

	def refresh(self, now: datetime) -> None:
		"""Fetch or render data in the background. May be slow; may raise."""

	def slides(self, now: datetime) -> list[Slide]:
		raise NotImplementedError

	def outside_daytime_slides(self, now: datetime) -> list[Slide]:
		"""For slide types in rotation.daytime_only: what to show outside the daytime anyway (e.g. the
		weather when it's going to rain). Usually nothing."""
		return []

	def shortcut_slide(self, now: datetime) -> Slide | None:
		"""The slide to show right away when its shortcut key is pressed; None if there's nothing to show."""
		slides = self.slides(now)
		return slides[0] if slides else None

	def action(self, name: str, values: list[str], now: datetime) -> tuple[Slide | None, str | None]:
		"""For interactive slides: a data-action button was clicked, with the values of the
		selected data-toggle elements. Return the redrawn slide and an optional message."""
		raise NotImplementedError


class Takeover:
	"""Interrupts the normal rotation when slide() returns a slide."""

	name = ""
	interrupts_paused = False   # True: also interrupts someone playing an interactive slide

	def slide(self, now: datetime) -> Slide | None:
		raise NotImplementedError

	def due(self, now: datetime) -> bool:
		"""Whether slide() would take over right now (without side effects)."""
		return False

	def next_start(self, now: datetime) -> datetime | None:
		"""When the next takeover starts, so the slide before it can be cut short. None = don't care."""
		return None


class Job:
	"""Called about once per second in the background."""

	name = ""

	def tick(self, now: datetime) -> None:
		raise NotImplementedError


def media_url(path: Path) -> str:
	"""URL under which the web server serves a file from the project folder.

	The modification time is added so the browser reloads files that changed.
	"""
	relative = path.resolve().relative_to(PROJECT_DIR)
	version = int(path.stat().st_mtime) if path.exists() else 0
	return f"/files/{quote(relative.as_posix())}?v={version}"
