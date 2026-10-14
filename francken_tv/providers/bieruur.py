"""Bieruur: a countdown slide, a takeover around 16:00, and the bieruur song."""

from __future__ import annotations

import logging
import math
import random
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path

from ..announcer import Announcer
from ..config import parse_time, parse_weekday, project_path
from ..slides import Job, Provider, Slide, Takeover

log = logging.getLogger(__name__)

AUDIO_EXTENSIONS = {".mp3", ".wav", ".ogg", ".flac", ".m4a"}
# Don't start the song if the slideshow is (re)started long after bieruur.
SONG_LATE_START_LIMIT = timedelta(minutes=2)


@dataclass
class BieruurSettings:
	time: str = "16:00"
	takeover_minutes_before: float = 2
	takeover_minutes_after: float = 2
	countdown_seconds: float = 5
	days: tuple[str, ...] = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
	songs_folder: str = "media/bieruur"
	choose_song_minutes_before: float = 10
	song_offsets: dict | None = None
	beer_fills_from: str = "08:00"   # the countdown's background is empty at this time, full of beer at bieruur

	def bieruur(self, now: datetime) -> datetime | None:
		"""Today's bieruur, or None if there is no bieruur today."""
		if now.weekday() not in {parse_weekday(day) for day in self.days}:
			return None
		return datetime.combine(now.date(), parse_time(self.time))

	def takeover_window(self, now: datetime) -> tuple[datetime, datetime] | None:
		bieruur = self.bieruur(now)
		if bieruur is None:
			return None
		return (
			bieruur - timedelta(minutes=self.takeover_minutes_before),
			bieruur + timedelta(minutes=self.takeover_minutes_after),
		)


# Clock face geometry (SVG viewBox 0 0 200 200, centre 100,100).
CLOCK_CENTRE = 100
DIAL_RADIUS = 88
NUMBER_RADIUS = 72


def dial_point(degrees: float, radius: float) -> tuple[float, float]:
	"""Point on the clock face; 0 degrees is 12 o'clock, clockwise."""
	angle = math.radians(degrees)
	return round(CLOCK_CENTRE + radius * math.sin(angle), 2), round(CLOCK_CENTRE - radius * math.cos(angle), 2)


# Positions of the numbers 1-12 on the clock face.
CLOCK_NUMBERS = [(number, *dial_point(number * 30, NUMBER_RADIUS)) for number in range(1, 13)]


def hour_angle(moment: datetime) -> float:
	return (moment.hour % 12 + moment.minute / 60 + moment.second / 3600) * 30


def wedge_path(start_degrees: float, end_degrees: float) -> str:
	"""SVG path of the pie slice between two clock positions (clockwise)."""
	sweep = (end_degrees - start_degrees) % 360
	if sweep < 0.01:
		return ""
	x1, y1 = dial_point(start_degrees, DIAL_RADIUS)
	x2, y2 = dial_point(start_degrees + sweep, DIAL_RADIUS)
	large_arc = 1 if sweep > 180 else 0
	return f"M {CLOCK_CENTRE} {CLOCK_CENTRE} L {x1} {y1} A {DIAL_RADIUS} {DIAL_RADIUS} 0 {large_arc} 1 {x2} {y2} Z"


def countdown_data(now: datetime, bieruur: datetime, settings: BieruurSettings | None = None) -> dict:
	"""Everything the bieruur slide shows at this moment (see templates/slides/bieruur.html)."""
	settings = settings or BieruurSettings()
	remaining = int((bieruur - now).total_seconds())
	if remaining <= 0:
		return {"state": "bieruur"}

	hours, rest = divmod(remaining, 3600)
	minutes, seconds = divmod(rest, 60)
	fill_from = datetime.combine(now.date(), parse_time(settings.beer_fills_from))
	fill = (now - fill_from) / (bieruur - fill_from) if bieruur > fill_from else 1.0
	fill = min(max(fill, 0.0), 1.0)
	return {
		"state": "final" if remaining <= settings.takeover_minutes_before * 60 else "countdown",
		"countdown": f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}",
		"hour_angle": round(hour_angle(now), 2),
		"minute_angle": round((now.minute + now.second / 60) * 6, 2),
		"second_angle": now.second * 6,
		# Beer-coloured slice from now until bieruur (only when bieruur is less than 12 hours away).
		"wedge": wedge_path(hour_angle(now), hour_angle(bieruur)) if remaining < 12 * 3600 else "",
		"bieruur_number": bieruur.hour % 12 or 12,   # this number on the clock gets a beer badge...
		"bieruur_label": f"{bieruur:%H}",            # ...showing "16"
		"numbers": CLOCK_NUMBERS,
		"beer_level": round(fill * 100, 2),   # % of the screen filled with beer
	}


def countdown_slide(settings: BieruurSettings, bieruur: datetime, seconds: float) -> Slide:
	return Slide(
		"bieruur.html",
		seconds,
		update=lambda now: countdown_data(now, bieruur, settings),
		refresh_seconds=1,
	)


class BieruurCountdownProvider(Provider):
	"""Shows the countdown for a few seconds every round, until the takeover starts."""

	name = "bieruur_countdown"

	def __init__(self, settings: BieruurSettings) -> None:
		self.settings = settings

	def slides(self, now: datetime) -> list[Slide]:
		window = self.settings.takeover_window(now)
		if window is None or now >= window[0]:
			return []
		return [countdown_slide(self.settings, self.settings.bieruur(now), self.settings.countdown_seconds)]


class BieruurTakeover(Takeover):
	"""Fills the screen from 2 minutes before until 2 minutes after bieruur."""

	name = "bieruur"
	interrupts_paused = True   # even someone solving the puzzle gets the countdown

	def __init__(self, settings: BieruurSettings) -> None:
		self.settings = settings

	def due(self, now: datetime) -> bool:
		window = self.settings.takeover_window(now)
		return window is not None and window[0] <= now < window[1]

	def slide(self, now: datetime) -> Slide | None:
		if not self.due(now):
			return None
		window = self.settings.takeover_window(now)
		seconds_left = (window[1] - now).total_seconds()
		return countdown_slide(self.settings, self.settings.bieruur(now), seconds_left)

	def next_start(self, now: datetime) -> datetime | None:
		window = self.settings.takeover_window(now)
		if window is None or now >= window[0]:
			return None
		return window[0]


class BieruurSong(Job):
	"""Picks a random song shortly before bieruur and plays it on time."""

	name = "bieruur_song"

	def __init__(self, settings: BieruurSettings, announcer: Announcer) -> None:
		self.settings = settings
		self.announcer = announcer
		self.folder = project_path(settings.songs_folder)
		self.offsets = settings.song_offsets or {}
		self.chosen: Path | None = None
		self.chosen_on: date | None = None
		self.played_on: date | None = None

	def songs(self) -> list[Path]:
		if not self.folder.is_dir():
			return []
		return sorted(p for p in self.folder.iterdir() if p.suffix.lower() in AUDIO_EXTENSIONS)

	def start_time(self, song: Path, bieruur: datetime) -> datetime:
		return bieruur + timedelta(seconds=self.offsets.get(song.name, 0))

	def tick(self, now: datetime) -> None:
		bieruur = self.settings.bieruur(now)
		if bieruur is None or self.played_on == now.date():
			return
		if self.chosen_on != now.date():
			if now < bieruur - timedelta(minutes=self.settings.choose_song_minutes_before):
				return
			songs = self.songs()
			if not songs:
				return
			self.chosen = random.choice(songs)
			self.chosen_on = now.date()
			log.info("Bieruur song for today: %s", self.chosen.name)
		start = self.start_time(self.chosen, bieruur)
		if now < start:
			return
		self.played_on = now.date()
		if now - start <= SONG_LATE_START_LIMIT:
			self.announcer.play_music(self.chosen)
