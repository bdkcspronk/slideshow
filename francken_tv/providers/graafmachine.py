"""A graafmachine digging: an animated slide, drawn in templates/slides/graafmachine.html."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class GraafmachineProvider(Provider):
	name = "graafmachine"
	title = "Graafmachine"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 14)   # the animation takes 14 s (style.css)

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("graafmachine.html", self.seconds)]
