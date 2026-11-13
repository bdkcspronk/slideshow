"""A graphics test for the TV PC: three Three.js scenes in steps from simple to complex, each with a live frames-per-second readout.
Watch whether they stay smooth: the scenes and the readout are in static/widgets.js (setupThree), the look in
templates/slides/three.html. Take "three" out of rotation.order in config.toml once you know."""

from __future__ import annotations

from datetime import datetime

from ..slides import Provider, Slide

SCENES = [
	("simple", "Simple", "a spinning knot and a cube, one light"),
	("medium", "Medium", "400 separate meshes in fog under three coloured lights, with a reflective floor"),
	("heavy", "Heavy", "1,000 lit spheres (340,000 triangles), two lights, no shadows"),
	("shadows", "Shadows", "only 300 spheres, but with a big shadow map: what shadows cost by themselves"),
	("triangles", "Triangles", "6,000 unlit spheres, 4 million triangles: raw geometry, no lighting, no shadows"),
	("overdraw", "Overdraw", "60 see-through glowing layers on top of each other: how many pixels it can blend"),
	("complex", "Complex", "6,000 spheres rippling (4 million triangles), 30,000 glowing points, a detailed metal knot, shadows"),
]


class ThreeProvider(Provider):
	name = "three"
	title = "Three.js test"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 15)
		self.scenes = [scene for scene in SCENES if scene[0] in settings.get("scenes", [name for name, _, _ in SCENES])]

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("three.html", self.seconds, {"scene": name, "label": label, "about": about}) for name, label, about in self.scenes]
