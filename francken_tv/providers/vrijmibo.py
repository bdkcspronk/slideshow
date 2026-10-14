"""The vrijmibo GIF: on Fridays it takes over the screen once every 15 minutes."""

from __future__ import annotations

from datetime import datetime

from ..config import parse_weekday, project_path
from ..media import animation_seconds
from ..slides import Slide, Takeover, media_url


class VrijmiboTakeover(Takeover):
	name = "vrijmibo"

	def __init__(self, settings: dict) -> None:
		self.path = project_path(settings.get("file", "media/vrijmibo.gif"))
		self.weekday = parse_weekday(settings.get("weekday", "friday"))
		self.every_minutes = settings.get("every_minutes", 15)
		self.last_shown_slot: tuple | None = None

	def slide(self, now: datetime) -> Slide | None:
		if now.weekday() != self.weekday or not self.path.is_file():
			return None
		slot = (now.date(), now.hour, now.minute // self.every_minutes)
		if slot == self.last_shown_slot:
			return None
		self.last_shown_slot = slot
		# The URL changes every time so the browser starts the GIF from the first frame.
		url = f"{media_url(self.path)}&t={now.timestamp():.0f}"
		return Slide("image.html", max(1.0, animation_seconds(self.path)), {"url": url})
