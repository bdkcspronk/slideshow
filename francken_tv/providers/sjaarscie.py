"""The Sjaarscie's promo: the first-year questions, then "Join the Sjaarscie!" with the Zwitsal baby, on baby blue and pink. An animated slide, drawn in
templates/slides/sjaarscie.html."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class SjaarscieProvider(Provider):
	name = "sjaarscie"
	title = "Sjaarscie"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 14)   # the questions come at 0.3 s and 2.8 s, the baby and "Join the Sjaarscie!" at 5.3 s

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("sjaarscie.html", self.seconds)]
