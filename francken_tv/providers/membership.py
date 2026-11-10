"""Become a member: why (€5 a year, free coffee, events) and a QR code to the sign-up form, animated in
templates/slides/membership.html. Replaces the old poster of it (10.png in media/slides/)."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class MembershipProvider(Provider):
	name = "membership"
	title = "Become a member"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 15)   # everything is in after about 5 s
		self.link = settings.get("link", "https://professorfrancken.nl/register")

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("membership.html", self.seconds, {"link": self.link})]
