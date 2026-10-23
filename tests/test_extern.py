"""The extern's slide (a made-up extern: the real one isn't in git)."""

import json
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from jinja2 import Environment, FileSystemLoader, select_autoescape

from francken_tv.config import DATA_DIR, PROJECT_DIR
from francken_tv.providers.extern import ExternProvider

NOW = datetime(2026, 10, 23, 12, 0)


class ExternTest(unittest.TestCase):
	def setUp(self):
		DATA_DIR.mkdir(exist_ok=True)
		self.folder = TemporaryDirectory(dir=DATA_DIR)   # inside the project, like media/extern/
		self.addCleanup(self.folder.cleanup)
		self.path = Path(self.folder.name) / "extern.json"
		self.photo = Path(self.folder.name) / "alex.png"
		self.photo.write_bytes(b"png")

	def write(self, data):
		self.path.write_text(json.dumps(data), encoding="utf-8")
		return ExternProvider({"file": str(self.path)}, 15)

	def test_the_extern_with_photo_and_contacts(self):
		provider = self.write({"ask": "Ask our extern - Alex", "photo": str(self.photo),
			"background": str(Path(self.folder.name) / "missing.png"),
			"contacts": [{"label": "Phone", "value": "+31 6 12345678", "note": "(also WhatsApp)"}, {"label": "Email", "value": "extern@example.com"}]})
		[slide] = provider.slides(NOW)
		self.assertEqual(slide.data["questions"], ["Internship?", "Job?", "Thesis?"])
		self.assertTrue(slide.data["photo"].startswith("/files/"))
		self.assertIsNone(slide.data["background"])   # missing: the plain blue
		html = Environment(loader=FileSystemLoader(PROJECT_DIR / "francken_tv" / "templates"), autoescape=select_autoescape()).get_template(
			"slides/extern.html").render(**slide.data)
		self.assertIn("+31 6 12345678&ensp;(also WhatsApp)", html)
		self.assertIn('style="--i: 4"', html)   # the second contact comes in after the three questions and the first contact

	def test_no_file_no_slide(self):
		self.assertEqual(ExternProvider({"file": str(self.path)}, 15).slides(NOW), [])
		self.assertEqual(self.write({"ask": "x"}).slides(NOW)[0].template, "extern.html")
		self.path.write_text("{broken", encoding="utf-8")
		self.assertEqual(ExternProvider({"file": str(self.path)}, 15).slides(NOW), [])


if __name__ == "__main__":
	unittest.main()
