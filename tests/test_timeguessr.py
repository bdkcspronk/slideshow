import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

from francken_tv.providers.timeguessr import (Game, TimeGuessrProvider, distance, js_to_json, parse_daily,
	place_points, year_points)

FIXTURE = Path(__file__).parent / "fixtures" / "timeguessr.html"
NOW = datetime(2026, 10, 17, 12, 0)
BERLIN = "52.52,13.405"


class FakeResponse:
	def __init__(self, text="", content=b""):
		self.status_code, self.text, self.content = 200, text, content

	def raise_for_status(self):
		pass


class ParseTest(unittest.TestCase):
	def test_reads_the_five_photos(self):
		photos = parse_daily(FIXTURE.read_text(encoding="utf-8"))
		self.assertEqual([photo.year for photo in photos], [1969, 2013, 1978, 1988, 1945])
		kabul = photos[0]
		self.assertEqual((kabul.number, kabul.country, kabul.scoring), ("1235", "Afghanistan", 1))
		self.assertAlmostEqual(kabul.lat, 34.5605, places=3)
		self.assertAlmostEqual(photos[1].lng, -0.2155, places=3)   # written as -.2154... on the page
		self.assertTrue(kabul.url.startswith("https://images.timeguessr.com/"))

	def test_js_object_to_json(self):
		text = '{No:"1",lat:-.25,lng:34.5,big:1e3,text:"a:-.5, {b:1}",list:[1,-2]}'
		self.assertEqual(json.loads(js_to_json(text)),
			{"No": "1", "lat": -0.25, "lng": 34.5, "big": 1000.0, "text": "a:-.5, {b:1}", "list": [1, -2]})

	def test_page_without_a_game(self):
		with self.assertRaises(ValueError):
			parse_daily("<html></html>")


class ScoringTest(unittest.TestCase):
	"""The same points as timeguessr.com (its scoring versions 1 and 2)."""

	def test_year(self):
		self.assertEqual([year_points(off) for off in [0, 1, 2, 5, 6, 7, 10, 20, 21]],
			[5000, 4950, 4800, 3900, 3400, 3400, 2500, 1000, 0])
		self.assertEqual(year_points(-3), year_points(3))
		self.assertEqual([year_points(off, 2) for off in [0, 12, 3]], [5000, 2500, 4706])

	def test_place(self):
		self.assertEqual(place_points(40), 5000)
		self.assertEqual(place_points(500), 4990)
		self.assertEqual(place_points(572_000), 3928)
		self.assertEqual(place_points(7_000_000), 12)
		self.assertEqual(place_points(0, 2), 5000)

	def test_distance(self):
		self.assertAlmostEqual(distance((52.37, 4.90), (52.52, 13.405)) / 1000, 577, delta=1)   # Amsterdam - Berlin


class GameTest(unittest.TestCase):
	def setUp(self):
		self.game = Game("1235", parse_daily(FIXTURE.read_text(encoding="utf-8")))

	def test_guess_then_next(self):
		self.game.act("guess", ["34.56,69.21", "1972"])   # right next to the Kabul answer, 3 years off
		self.assertTrue(self.game.showing_answer)
		guess = self.game.guesses[0]
		self.assertEqual(guess.year_points, 4600)
		self.assertEqual(guess.place_points, 4997)   # about 160 m away: 5000 - 160 * 0.02
		self.assertEqual(self.game.photo.country, "Afghanistan")   # still the answer on screen
		self.game.act("guess", ["0,0", "2000"])   # ignored until Next
		self.assertEqual(len(self.game.guesses), 1)
		self.game.act("next", [])
		self.assertEqual(self.game.photo.country, "Ghana")

	def test_a_guess_needs_a_pin(self):
		self.assertIn("pin", self.game.act("guess", ["", "1970"]))
		self.assertEqual(self.game.guesses, [])

	def test_done_after_five(self):
		for _ in range(5):
			self.game.act("guess", [BERLIN, "1988"])
			self.game.act("next", [])
		self.assertTrue(self.game.done)
		self.assertEqual(self.game.score, sum(guess.points for guess in self.game.guesses))
		self.assertEqual(self.game.guesses[3].points, 4903 + 5000)   # West Berlin, 4.8 km from the centre; the right year


class ProviderTest(unittest.TestCase):
	def setUp(self):
		self.folder = Path(tempfile.mkdtemp())
		self.addCleanup(lambda: [path.unlink() for path in self.folder.rglob("*") if path.is_file()])
		self.provider = TimeGuessrProvider({}, 20, self.folder / "cache", self.folder / "timeguessr.json")
		page = FIXTURE.read_text(encoding="utf-8")
		get = lambda url, **kwargs: FakeResponse(text=page) if "timeguessr.com/play" in url else FakeResponse(content=b"image")
		with mock.patch("francken_tv.providers.timeguessr.requests.get", side_effect=get) as self.request, \
				mock.patch("francken_tv.providers.timeguessr.media_url", side_effect=lambda path: f"/files/{path.name}"):
			self.provider.refresh(NOW)
			self.provider.refresh(NOW)   # the same challenge: nothing downloaded again

	def test_refresh_downloads_the_photos_once(self):
		self.assertEqual(len(self.request.call_args_list), 1 + 5 + 1)
		self.assertEqual(len(list((self.folder / "cache").iterdir())), 5)
		self.assertTrue(self.provider.photos[0].image.startswith("/files/"))

	def test_status_and_saved_game(self):
		self.assertEqual(self.provider.status(NOW).text, "Not tried yet")
		slide, message = self.provider.action("guess", [BERLIN, "1970"], NOW)
		self.assertEqual((slide.template, message), ("timeguessr.html", None))
		self.assertEqual(self.provider.status(NOW).state, "playing")
		restarted = TimeGuessrProvider({}, 20, self.folder / "cache", self.folder / "timeguessr.json")
		restarted.photos = self.provider.photos
		game = restarted.todays_game(NOW)
		self.assertEqual((len(game.guesses), game.showing_answer), (1, True))

	def test_slide_data(self):
		[slide] = self.provider.slides(NOW)
		self.assertEqual((slide.data["first_year"], slide.data["last_year"], slide.data["total_points"]), (1900, 2026, 50_000))


if __name__ == "__main__":
	unittest.main()
