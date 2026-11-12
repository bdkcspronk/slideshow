"""The Fotocie's promo: their logo with the animation of the Fotocie app's start screen (looking through a camera,
pulling focus, the flashbulb firing). An animated slide, drawn in templates/slides/fotocie.html."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class FotocieProvider(Provider):
	name = "fotocie"
	title = "Fotocie"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 16)   # the animation takes 2.6 s; the first text goes at 4.6 s, the second is complete at 7.4 s and stays for the rest

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("fotocie.html", self.seconds)]
