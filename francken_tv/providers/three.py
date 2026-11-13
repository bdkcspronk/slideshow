"""A graphics test for the TV PC: three Three.js scenes in steps from simple to complex, each with a live frames-per-second readout.
Watch whether they stay smooth: the scenes and the readout are in static/widgets.js (setupThree), the look in
templates/slides/three.html. Tap a scene or a resolution to switch (or press S and R); that also stops the slideshow on this slide until nobody has touched it for
5 minutes. Take "three" out of rotation.order in config.toml once you know."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from ..config import PROJECT_DIR
from ..slides import Provider, Slide

BENCHMARKS = PROJECT_DIR / "benchmarks"   # where the benchmark's results are saved (committed from the TV PC)

SCENES = [
	("simple", "Simple", "a spinning knot and a cube, one light"),
	("medium", "Medium", "400 separate meshes in fog under three coloured lights, with a reflective floor"),
	("heavy", "Heavy", "1,000 lit spheres (340,000 triangles), two lights, no shadows"),
	("shadows", "Shadows", "only 300 spheres, but with a big shadow map: what shadows cost by themselves"),
	("triangles", "Triangles", "6,000 unlit spheres, 4 million triangles: raw geometry, no lighting, no shadows"),
	("overdraw", "Overdraw", "60 see-through glowing layers on top of each other: how many pixels it can blend"),
	("complex", "Complex", "6,000 spheres rippling (4 million triangles), 30,000 glowing points, a detailed metal knot, shadows"),
]

# The resolutions to try: how much of the screen's pixels are drawn (the rest is scaled up), as (scale, label).
SCALES = [(1, "100%"), (0.75, "75%"), (0.5, "50%")]


class ThreeProvider(Provider):
	name = "three"
	title = "Three.js test"

	def __init__(self, settings: dict) -> None:
		self.seconds = settings.get("seconds", 15)
		self.scenes = [scene for scene in SCENES if scene[0] in settings.get("scenes", [name for name, _, _ in SCENES])]

	def slides(self, now: datetime) -> list[Slide]:
		everything = [{"name": name, "label": label, "about": about} for name, label, about in self.scenes]
		return [Slide("three.html", self.seconds, {"scene": name, "label": label, "about": about, "scenes": everything, "scales": SCALES}) for name, label, about in self.scenes]


class ThreeBenchmarkProvider(Provider):
	"""The 3D benchmark: a slide (not in the rotation; Esc -> Fun -> "3D benchmark") that runs a series of Three.js tests when Start is
	tapped (static/three_benchmark.js) and has the server save what came out in benchmarks/ (save()), to commit from the TV PC.
	What the results mean is in docs/07-3d-limits.md."""

	name = "three_benchmark"
	title = "3D benchmark"

	def __init__(self, folder: Path = BENCHMARKS) -> None:
		self.folder = folder

	def slides(self, now: datetime) -> list[Slide]:
		return [Slide("three_benchmark.html", 600)]

	def save(self, results: dict, now: datetime) -> tuple[Path, Path]:
		"""Write the results as JSON and as a readable Markdown page; returns both paths."""
		if not isinstance(results.get("tests"), list) or not results["tests"]:
			raise ValueError("no results")
		self.folder.mkdir(exist_ok=True)
		stem = f"3d-{now:%Y-%m-%d-%H%M}"
		json_path, markdown_path = self.folder / f"{stem}.json", self.folder / f"{stem}.md"
		json_path.write_text(json.dumps(results, indent="\t") + "\n", encoding="utf-8")
		markdown_path.write_text(markdown(results), encoding="utf-8")
		return json_path, markdown_path


def cell(value) -> str:
	return "" if value is None else str(value).replace("|", "/").replace("\n", " ")


def markdown(results: dict) -> str:
	"""The results as a page: the PC's details, then per test a table of its steps and (for a ramp) the last step that held 60 fps."""
	lines = ["# 3D benchmark", "",
		f"- When: {cell(results.get('when'))}",
		f"- Graphics: {cell(results.get('gpu'))} (WebGL {2 if results.get('webgl2') else 1}, largest texture {cell(results.get('max_texture_size'))})",
		f"- Screen: {cell(results.get('screen'))}, drawn on {cell(results.get('canvas'))} (pixel ratio {cell(results.get('pixel_ratio'))})",
		f"- Three.js r{cell(results.get('three'))}, {cell(results.get('browser'))}", "",
		f"- Empty scene: {cell(results.get('floor_ms'))} ms of work (reading a pixel back costs that by itself; a real slide doesn't pay it)", "",
		'"Holds 60" means at least 55 fps and 95% of the frames took 14 ms of work or less beyond the empty scene\'s. "Work" is the median time '
		'to draw a frame including waiting for the graphics chip. "First frame" is when shaders compile and textures upload.', ""]
	for test in results["tests"]:
		lines += [f"## {cell(test.get('title'))}", ""]
		if test.get("best") is not None:
			lines += [f"**Largest step that holds 60 fps: {cell(test['best'])}**", ""]
		lines += ["| Step | fps | Work ms | 95% ms | First frame ms | Triangles | Draw calls | Holds 60 |", "|---|---|---|---|---|---|---|---|"]
		for step in test.get("steps", []):
			holds = "yes" if step.get("holds") else "no"
			if step.get("error"):
				lines.append(f"| {cell(step.get('label'))} | | | | | | | error: {cell(step['error'])} |")
				continue
			lines.append("| " + " | ".join([cell(step.get("label")), cell(step.get("fps")), cell(step.get("work_ms")), cell(step.get("p95_ms")),
				cell(step.get("first_ms")), cell(step.get("triangles")), cell(step.get("calls")), holds]) + " |")
		lines.append("")
	return "\n".join(lines)
