"""The nyan cat is pixel art in templates/nyancat.svg, drawn inline in the activity chart."""

import json
import re
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from jinja2 import Environment, FileSystemLoader, select_autoescape
from PIL import Image

from francken_tv.activity_chart import chart_view
from francken_tv.config import PROJECT_DIR
from francken_tv.devices import DeviceList
from francken_tv.presence_store import Sighting

SVG = PROJECT_DIR / "francken_tv" / "templates" / "nyancat.svg"
SOURCE = PROJECT_DIR / "tools" / "nyancat.png"
BLOCK = 8   # the source PNG: one art pixel is 8 x 8 pixels
CAT = "AA:AA:AA:AA:AA:01"


def cells(svg: str) -> dict[tuple[int, int], str]:
	found = {}
	for colour, path in re.findall(r'<path fill="(#\w+)" d="([^"]+)"', svg):
		for x, y, width, height in re.findall(r"M(\d+) (\d+)h(\d+)v(\d+)h-\d+z", path):
			for row in range(int(y), int(y) + int(height)):
				for column in range(int(x), int(x) + int(width)):
					assert (column, row) not in found, "rectangles overlap"
					found[(column, row)] = colour
	return found


class NyanCatTest(unittest.TestCase):
	def test_the_svg_is_the_pixel_art(self):
		image = Image.open(SOURCE).convert("RGBA")
		expected = {(x, y): "#%02x%02x%02x" % image.getpixel((x * BLOCK, y * BLOCK))[:3]
			for y in range(image.height // BLOCK) for x in range(image.width // BLOCK) if image.getpixel((x * BLOCK, y * BLOCK))[3]}
		self.assertEqual(cells(SVG.read_text(encoding="utf-8")), expected)
		self.assertIn('viewBox="0 0 33 20"', SVG.read_text(encoding="utf-8"))

	def test_the_chart_draws_the_cat_inline_on_the_latest_bar(self):
		with TemporaryDirectory() as folder:
			devices = Path(folder) / "devices.json"
			devices.write_text(json.dumps([{"ssid": "Cat", "mac": CAT, "style": "nyan cat", "x_offset": 5}]))
			day = datetime(2026, 10, 14, 12)
			sightings = [Sighting(day, CAT, "Cat"), Sighting(day.replace(minute=10), CAT, "Cat")]
			chart = chart_view(sightings, DeviceList(devices).by_mac(), day.replace(hour=13))
		html = Environment(loader=FileSystemLoader(PROJECT_DIR / "francken_tv" / "templates"), autoescape=select_autoescape()
			).get_template("slides/presence.html").render(**chart)
		self.assertEqual(html.count('class="nyan-cat-sprite"'), 1)
		self.assertIn('viewBox="0 0 33 20"', html)   # the SVG itself, not an <img> of a file in media/
		self.assertNotIn("<img", html)


if __name__ == "__main__":
	unittest.main()
