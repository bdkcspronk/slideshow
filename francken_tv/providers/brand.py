"""The brand slide: our name, logo and colours, animated (templates/slides/brand.html)."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from ..slides import Provider, Slide

LOGO = Path(__file__).resolve().parent.parent / "static" / "francken-logo.svg"


class BrandProvider(Provider):
	name = "brand"

	def __init__(self, settings: dict, default_seconds: float) -> None:
		self.seconds = settings.get("seconds", default_seconds)
		# The logo goes into the page itself (not as an <img>), so CSS can colour and animate it.
		svg = LOGO.read_text(encoding="utf-8")
		self.logo = svg[svg.index("<svg"):]

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("brand.html", self.seconds, {"logo": self.logo})]
