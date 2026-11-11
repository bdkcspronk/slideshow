"""Francken socks for sale: the price, and a QR code to text the seller on WhatsApp, animated in
templates/slides/socks.html. Replaces the old poster of it in media/slides/."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide


class SocksProvider(Provider):
	name = "socks"
	title = "Francken socks"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 15)   # everything is in after about 4 s
		self.link = settings.get("link", "https://wa.me/31653346489")
		self.price = settings.get("price", "€7,20")

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("socks.html", self.seconds, {"link": self.link, "price": self.price})]
