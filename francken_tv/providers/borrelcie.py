"""The Borrelcie's promo, after the Beatles: a piano keyboard playing, then THE BORRELCIE in their lettering.
An animated slide, drawn in templates/slides/borrelcie.html. Replaces the old static poster of it."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class BorrelcieProvider(Provider):
	name = "borrelcie"
	title = "Borrelcie"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 17)   # the leg has grown out after about 14 s (style.css)

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("borrelcie.html", self.seconds)]
