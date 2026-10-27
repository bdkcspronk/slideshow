import os
import subprocess
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from PIL import Image

from francken_tv.providers.francken_vrij import FranckenVrijProvider, issue_title, read_pauses, timeline

NOW = datetime(2026, 10, 27, 12, 0)
# What pdftohtml -xml says about an 8-page issue: the contents on page 2, bookmarks for articles on 4 and 6.
XML = """<?xml version="1.0" encoding="UTF-8"?>
<pdf2xml producer="poppler">
<page number="1" position="absolute"><text top="10" left="10"><b>Francken Vrij</b></text></page>
<page number="2" position="absolute"><text top="10" left="10">In dit nummer</text><text>Borrel ... 4</text></page>
<page number="3" position="absolute"><text>Van de voorzitter</text></page>
<page number="4" position="absolute"><text>De borrel</text></page>
<page number="5" position="absolute"><text>...</text></page>
<page number="6" position="absolute"><text>Het symposium</text></page>
<page number="7" position="absolute"><text>...</text></page>
<page number="8" position="absolute"><text>Achterkant</text></page>
<outline><item page="4">De borrel</item><outline><item page="5">Foto's</item></outline><item page="6">Het symposium</item><item page="40">Kapot</item></outline>
</pdf2xml>"""


class PartsTest(unittest.TestCase):
	def test_issue_title(self):
		self.assertEqual(issue_title(Path("29-3-3.pdf")), "Volume 29 · Issue 3")
		self.assertEqual(issue_title(Path("lustrum_special.pdf")), "lustrum special")

	def test_pauses_the_cover_the_contents_and_the_bookmarks(self):
		self.assertEqual(read_pauses(XML, 8), {1, 2, 4, 5, 6})   # a bookmark past the last page is left out
		self.assertEqual(read_pauses("<pdf2xml></pdf2xml>", 8), {1})   # no contents, no bookmarks: the cover

	def test_timeline(self):
		# 8 pages: the cover (1 + 5 s), then 4 leaves turn; the spreads 2-3 and 4-5 pause, 6-7 too, the back cover glances.
		starts, end = timeline(8, {1, 2, 4, 6}, turn=1, pause=5, glance=0.5)
		self.assertEqual(starts, [6, 12, 18, 24])
		self.assertEqual(end, 25.5)
		starts, end = timeline(7, {1}, turn=1, pause=5, glance=0.5)   # odd: the last spread (6-7) is the end
		self.assertEqual((starts, end), ([6, 7.5, 9], 10.5))


class ProviderTest(unittest.TestCase):
	def setUp(self):
		self.folder = Path(tempfile.mkdtemp())
		(self.folder / "issues").mkdir()
		self.provider = FranckenVrijProvider({"folder": str(self.folder / "issues"), "turn_seconds": 1, "pause_seconds": 5,
			"glance_seconds": 0.5}, self.folder / "cache")
		patcher = mock.patch("francken_tv.providers.francken_vrij.media_url", side_effect=lambda path: f"/files/{path.name}")
		patcher.start()
		self.addCleanup(patcher.stop)

	def poppler(self, pages=8):
		"""A fake pdftoppm (writes `pages` page images) and pdftohtml (the XML above)."""
		calls = []

		def run(*command):
			calls.append(command[0])
			if command[0] == "pdftoppm":
				for number in range(1, pages + 1):
					Image.new("RGB", (70, 100), "white").save(f"{command[-1]}-{number}.jpg")
				return subprocess.CompletedProcess(command, 0, "", "")
			return subprocess.CompletedProcess(command, 0, XML, "")
		return mock.patch("francken_tv.providers.francken_vrij.run", side_effect=run), calls

	def test_no_pdf_no_slide(self):
		self.provider.refresh(NOW)
		self.assertEqual(self.provider.slides(NOW), [])

	def test_the_newest_pdf_turns_its_pages(self):
		(self.folder / "issues" / "29-3.pdf").write_bytes(b"%PDF")
		patch, calls = self.poppler()
		with patch:
			self.provider.refresh(NOW)
			self.provider.refresh(NOW)   # the same PDF: not converted again
		self.assertEqual(calls, ["pdftoppm", "pdftohtml"])
		[slide] = self.provider.slides(NOW)
		data = slide.data
		self.assertEqual((data["title"], data["aspect"], len(data["leaves"])), ("Volume 29 · Issue 3", 0.7, 4))
		self.assertEqual([leaf["turns_at"] for leaf in data["leaves"]], [6, 12, 18, 24])   # pauses on 2, 4-5 and 6
		self.assertEqual((data["leaves"][0]["front"], data["leaves"][0]["back"]), ("/files/page-1.jpg", "/files/page-2.jpg"))
		self.assertEqual((data["opens_at"], data["closes_at"], slide.seconds), (6, 24, 26.5))

	def test_a_new_issue_replaces_the_old_pages(self):
		old = self.folder / "issues" / "29-2.pdf"
		old.write_bytes(b"%PDF")
		patch, _ = self.poppler()
		with patch:
			self.provider.refresh(NOW)
			new = self.folder / "issues" / "29-3.pdf"
			new.write_bytes(b"%PDF")
			os.utime(new, (old.stat().st_mtime + 60, old.stat().st_mtime + 60))   # newer
			self.provider.refresh(NOW)
		self.assertEqual(self.provider.slides(NOW)[0].data["title"], "Volume 29 · Issue 3")
		self.assertEqual(len([folder for folder in (self.folder / "cache").iterdir()]), 1)   # the old pages are gone

	def test_without_poppler_it_says_what_to_install(self):
		(self.folder / "issues" / "29-3.pdf").write_bytes(b"%PDF")
		with mock.patch("francken_tv.providers.francken_vrij.shutil.which", return_value=None):
			with self.assertRaisesRegex(RuntimeError, "poppler-utils"):
				self.provider.refresh(NOW)


if __name__ == "__main__":
	unittest.main()
