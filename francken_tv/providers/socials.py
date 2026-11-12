"""Where to find us: QR codes to the WhatsApp announcement group, LinkedIn, Instagram and the website, as
polaroids pegged on a washing line (templates/slides/socials.html). Replaces the old "Scan here" poster in
media/slides/."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide

LINE_SAG = 7   # vh: how far the washing line hangs down in the middle (the pegs follow it)


class SocialsProvider(Provider):
	name = "socials"
	title = "Find us online"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 15)   # everything is in after about 4 s
		self.links = {
			"whatsapp": settings.get("whatsapp", "https://chat.whatsapp.com/JhyvxwWNQU5IP9h4YK5CFp"),
			"linkedin": settings.get("linkedin", "https://linkedin.com/company/t.f.v.-professor-francken"),
			"instagram": settings.get("instagram", "https://instagram.com/tfvprofessorfrancken"),
			"website": settings.get("website", "https://professorfrancken.nl"),
		}

	def slides(self, now: datetime) -> list[Slide]:
		cards = []
		for i, (kind, link) in enumerate((kind, link) for kind, link in self.links.items() if link):
			cards.append({"kind": kind, "link": link, "i": i})
		if not cards:
			return []
		for card in cards:   # spread evenly along the line, each peg on the line where it sags
			x = (card["i"] + 0.5) / len(cards)
			card["x"] = round(x * 100, 2)
			card["y"] = round(4 * x * (1 - x) * LINE_SAG, 2)
		return [Slide("socials.html", self.seconds, {"cards": cards, "sag": LINE_SAG})]
