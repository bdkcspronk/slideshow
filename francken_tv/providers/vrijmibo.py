"""The vrijmibo takeover: on Fridays it takes over the screen once every 15 minutes.

A chomper eats the beers in a neon maze and barfs out "Vrijmibo?", in 3D (templates/slides/vrijmibo.html,
static/vrijmibo_3d.js). The animation is 15 seconds; the slide lasts as long.
"""

from __future__ import annotations

from datetime import datetime

from ..config import parse_weekday
from ..slides import Slide, Takeover

SECONDS = 15   # as long as the animation (VM.duration in static/vrijmibo_3d.js)


class VrijmiboTakeover(Takeover):
	name = "vrijmibo"
	title = "Vrijmibo"

	def __init__(self, settings: dict) -> None:
		self.weekday = parse_weekday(settings.get("weekday", "friday"))
		self.every_minutes = settings.get("every_minutes", 15)
		self.last_shown_slot: tuple | None = None

	def slide(self, now: datetime) -> Slide | None:
		if not self.on_today(now):
			return None
		slot = (now.date(), now.hour, now.minute // self.every_minutes)
		if slot == self.last_shown_slot:
			return None
		self.last_shown_slot = slot
		return self.show()

	def on_today(self, now: datetime) -> bool:
		return now.weekday() == self.weekday

	def show(self) -> Slide:
		return Slide("vrijmibo.html", SECONDS, {})

	def menu_slide(self, now: datetime) -> Slide | None:
		"""In the menu on Fridays (Fun), any time: the animation, without using up the slot of the next takeover."""
		return self.show() if self.on_today(now) else None
