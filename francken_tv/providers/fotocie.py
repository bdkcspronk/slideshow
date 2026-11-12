"""The Fotocie's promo: their logo with the animation of the Fotocie app's start screen (looking through a camera,
pulling focus, the flashbulb firing). An animated slide, drawn in templates/slides/fotocie.html."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class FotocieProvider(Provider):
	name = "fotocie"
	title = "Fotocie"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 8)   # the animation takes 2.6 s, the rest is the logo staying

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("fotocie.html", self.seconds)]
