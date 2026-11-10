"""The nyan cat is pixel art in two frames, templates/nyancat.svg and nyancat1.svg, drawn inline in the activity chart."""

import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from jinja2 import Environment, FileSystemLoader, select_autoescape

from francken_tv.activity_chart import chart_view
from francken_tv.config import PROJECT_DIR
from francken_tv.devices import DeviceList
from francken_tv.presence_store import Sighting

FRAMES = [PROJECT_DIR / "francken_tv" / "templates" / name for name in ("nyancat.svg", "nyancat1.svg")]
CAT = "AA:AA:AA:AA:AA:01"


class NyanCatTest(unittest.TestCase):
	def test_both_frames_are_33_by_20_pixels(self):
		for frame in FRAMES:   # the same size, so the cat doesn't jump; the aspect-ratio in style.css
			svg = frame.read_text(encoding="utf-8")
			self.assertIn('viewBox="0 0 33 20"', svg, frame.name)
			self.assertTrue(svg.startswith("<svg"), f"{frame.name}: no XML header, it's drawn inside the page")
			shapes = " ".join(re.findall(r'\b(?:x|y|width|height|d)="([^"]*)"', svg))
			self.assertEqual(re.findall(r"\d*\.\d+", shapes), [], f"{frame.name}: everything on whole pixels, or seams show")

	def test_the_chart_draws_the_cat_inline_on_the_latest_bar(self):
		with TemporaryDirectory() as folder:
			devices = Path(folder) / "devices.json"
			devices.write_text(json.dumps([{"ssid": "Cat", "mac": CAT, "style": "nyan cat"}]))
			day = datetime(2026, 10, 14, 12)
			sightings = [Sighting(day, CAT, "Cat"), Sighting(day.replace(minute=10), CAT, "Cat")]
			chart = chart_view(sightings, DeviceList(devices).by_mac(), day.replace(hour=13))
		html = Environment(loader=FileSystemLoader(PROJECT_DIR / "francken_tv" / "templates"), autoescape=select_autoescape()
			).get_template("slides/presence.html").render(**chart)
		self.assertEqual(html.count('class="nyan-cat-sprite"'), 1)
		self.assertEqual(html.count('viewBox="0 0 33 20"'), 2)   # both frames, inline, not an <img> of a file in media/
		self.assertNotIn("<img", html)


	def test_the_cat_rides_from_the_first_bar_to_the_end_of_the_last(self):
		with TemporaryDirectory() as folder:
			devices = Path(folder) / "devices.json"
			devices.write_text(json.dumps([{"ssid": "Cat", "mac": CAT, "style": "nyan cat"}]))
			day = datetime(2026, 10, 14, 12)
			sightings = [Sighting(day.replace(minute=m), CAT, "Cat") for m in (0, 5, 40, 45)]
			first, last = chart_view(sightings, DeviceList(devices).by_mac(), day.replace(hour=13))["bars"]
		ride = last["nyan_cat"]
		self.assertIsNone(first["nyan_cat"])
		self.assertEqual((ride["from"], ride["to"]), (first["left"], round(last["left"] + last["width"], 3)))
		self.assertEqual(ride["delay"], first["delay"])   # it sets off with the first bar, at the bars' speed
		self.assertEqual(ride["grow"], first["back"]["grow"])   # and keeps pace with the faded run behind them


if __name__ == "__main__":
	unittest.main()
