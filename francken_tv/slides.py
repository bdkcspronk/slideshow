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
	refresh_seconds: float | None = None   # how often refresh() runs; None = never

	def refresh(self, now: datetime) -> None:
		"""Fetch or render data in the background. May be slow; may raise."""

	def slides(self, now: datetime) -> list[Slide]:
		raise NotImplementedError


class Takeover:
	"""Interrupts the normal rotation when slide() returns a slide."""

	name = ""

	def slide(self, now: datetime) -> Slide | None:
		raise NotImplementedError

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
