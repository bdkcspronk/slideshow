"""The MScie's promo: the committee for master students, by master students. Seven arms (black silhouettes) swing up from below the bottom of the screen
and throw black graduation caps in the air once; when the caps are gone the name and the tagline come. An animated slide, drawn in
templates/slides/mscie.html."""

from __future__ import annotations

import math
from datetime import datetime

from ..slides import Provider, Slide

ARM = 34       # vh: how far the hand reaches above the bottom of the screen when the arm is raised straight up
SHOULDER = 16  # vh: how far below the bottom of the screen the arm turns around (so the arm always starts at the edge of the screen, never floating)
REACH = ARM + SHOULDER   # vh: the length of the arm, from the shoulder to the fingertips
GRIP = 3       # vh: how far the cap sits down into the fingers
RELEASE = 0.4  # s after an arm starts swinging that the cap leaves the hand

# left (vw), peak height of the cap (vh), cap height (vh), spin (deg), start (s), flight time (s)
CAPS = [
	(12, 62, 17, -50, 0.3, 3.2),
	(26, 80, 15, 70, 0.7, 3.5),
	(40, 68, 19, -35, 0.0, 3.4),
	(54, 84, 16, 90, 0.9, 3.6),
	(68, 64, 18, -70, 0.5, 3.3),
	(82, 78, 15, 45, 1.1, 3.4),
	(92, 58, 13, -40, 0.2, 3.1),
]


def caps() -> list[dict]:
	"""The caps with, for each, the arm's angles (it swings in from the side it is on, to just past upright) and where its hand is at the moment of the throw."""
	result = []
	for left, peak, size, spin, delay, seconds in CAPS:
		side = -1 if left < 50 else 1
		lean = round(spin / 30, 1)   # deg: the angle of the arm when the cap leaves
		hand = REACH - GRIP + size / 2   # vh: from the shoulder to the middle of the cap in the hand
		angle = math.radians(lean)
		result.append({
			"left": left, "peak": peak, "size": size, "spin": spin, "delay": delay, "seconds": seconds,
			"lean": lean, "start": side * 100, "over": round(lean - side * 8, 1),
			"x": round(hand * math.sin(angle), 2),                                   # vh: how far the cap's middle is to the side of its resting place...
			"y": round(-SHOULDER + hand * math.cos(angle) - size / 2, 2),            # ...and how far above it
		})
	return result


class MscieProvider(Provider):
	name = "mscie"
	title = "MScie"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 14)   # the arms throw the caps at 0.4-1.5 s and the caps are gone by 4.9 s; the name lands at 5.4 s and the tagline fades in at 6.6 s

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("mscie.html", self.seconds, {"caps": caps(), "arm": ARM, "reach": REACH, "shoulder": SHOULDER, "grip": GRIP})]
