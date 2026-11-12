"""The Borrelcie's promo, after the Beatles: a piano keyboard playing, then THE BORRELCIE in their lettering.
An animated slide, drawn in templates/slides/borrelcie.html. Replaces the old static poster of it.
The verse is sung in Dutch and in English in turn (same notes, same syllable counts)."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide

# (x of the key, start in seconds, word): a word rises from the key of its first syllable, when that note is played
DUTCH = [
	(922.5, 0.00, "Ik"), (922.5, 0.25, "kwam"), (922.5, 0.50, "een"), (997.5, 0.75, "dag"), (922.5, 1.25, "bij"),
	(1147.5, 1.50, "Francken"),
	(1222.5, 2.50, "Zocht"), (1297.5, 2.62, "naar"), (1297.5, 2.75, "de"), (1297.5, 3.00, "reëelste"),
	(1222.5, 3.50, "commissie"),
	(1297.5, 4.75, "Had"), (1297.5, 4.88, "ik"), (1372.5, 5.12, "snel"), (1297.5, 5.38, "gevonden"),
	(1297.5, 6.50, "Borrelcie"),
]
ENGLISH = [
	(922.5, 0.00, "I"), (922.5, 0.25, "came"), (922.5, 0.50, "by"), (997.5, 0.75, "Francken"),
	(1147.5, 1.50, "one"), (1222.5, 1.75, "day"),
	(1222.5, 2.50, "Searching"), (1297.5, 2.75, "for"), (1297.5, 3.00, "the"), (1222.5, 3.12, "hardest"),
	(1222.5, 3.50, "committee"),
	(1297.5, 4.75, "Found"), (1297.5, 4.88, "it"), (1372.5, 5.12, "in"), (1297.5, 5.38, "no"), (1297.5, 5.50, "time"),
	(1297.5, 6.50, "Borrelcie"),
]


class BorrelcieProvider(Provider):
	name = "borrelcie"
	title = "Borrelcie"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 17)   # the leg has grown out after about 14 s (style.css)
		self.rounds = 0

	def slides(self, now: datetime) -> list[Slide]:
		self.rounds += 1   # Dutch, English, Dutch...
		return [Slide("borrelcie.html", self.seconds, {"words": DUTCH if self.rounds % 2 else ENGLISH})]
