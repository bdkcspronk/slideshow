"""Become a member: why (€5 a year, free coffee, events) and a QR code to the sign-up form, animated in
templates/slides/membership.html. Replaces the old poster of it (10.png in media/slides/).
Only shown in the months people sign up: the start of the academic year and of the second semester."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class MembershipProvider(Provider):
	name = "membership"
	title = "Become a member"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 15)   # everything is in after about 5 s
		self.link = settings.get("link", "https://professorfrancken.nl/register")
		self.months = set(settings.get("months", [8, 9, 10, 2]))   # August to October, and February

	def slides(self, now: datetime) -> list[Slide]:
		if now.month not in self.months:
			return []
		return [Slide("membership.html", self.seconds, {"link": self.link})]
