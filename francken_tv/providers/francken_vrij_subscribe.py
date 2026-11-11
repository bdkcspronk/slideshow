"""Get the Francken Vrij on paper: how to opt in on the website, with a cursor doing it in the website's menu and
the latest issue's cover (from providers/francken_vrij.py) popping out (templates/slides/francken_vrij_subscribe.html).
Replaces the old "Receive the physical Francken Vrij!" poster in media/slides/."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide, media_url
from .francken_vrij import FranckenVrijProvider


class FranckenVrijSubscribeProvider(Provider):
	name = "francken_vrij_subscribe"
	title = "Francken Vrij on paper"

	def __init__(self, settings: dict, magazine: FranckenVrijProvider) -> None:
		self.seconds = settings.get("seconds", 15)   # everything is done after about 7 s
		self.link = settings.get("link", "https://professorfrancken.nl/profile/francken-vrij")
		self.magazine = magazine   # for the latest cover; without a PDF the slide is shown without one

	def slides(self, now: datetime) -> list[Slide]:
		issue = self.magazine.issue
		cover = media_url(issue.pages[0]) if issue else None
		until = f"September {now.year + 1 if now.month >= 9 else now.year}"   # the website's first choice: the coming September
		return [Slide("francken_vrij_subscribe.html", self.seconds, {
			"link": self.link, "cover": cover, "aspect": round(issue.aspect, 4) if issue else 0.707, "until": until})]
