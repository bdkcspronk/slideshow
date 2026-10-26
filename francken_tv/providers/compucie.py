"""The Compucie's promo: a Matrix-style slide, drawn in templates/slides/compucie.html (the code rain, the
title decoding and the terminal typing itself are widgets in static/widgets.js)."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class CompucieProvider(Provider):
	name = "compucie"
	title = "Compucie"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 18)   # the terminal has typed everything after about 12 s

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("compucie.html", self.seconds)]
