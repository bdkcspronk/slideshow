import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from francken_tv.config import DATA_DIR
from francken_tv.providers.bieruur import BieruurCountdownProvider, BieruurSettings, BieruurTakeover, countdown_data
from francken_tv.providers.vrijmibo import VrijmiboTakeover
from francken_tv.scheduler import EMPTY_SLIDE, Scheduler
from francken_tv.slides import Provider, Slide

THURSDAY = datetime(2026, 10, 15)
FRIDAY = datetime(2026, 10, 16)


def at(day: datetime, hhmmss: str) -> datetime:
	hour, minute, second = map(int, hhmmss.split(":"))
	return day.replace(hour=hour, minute=minute, second=second)


class FixedProvider(Provider):
	def __init__(self, name, count, seconds=8):
		self.name, self.count, self.seconds = name, count, seconds

	def slides(self, now):
		return [Slide("image.html", self.seconds, {"name": f"{self.name}{i}"}) for i in range(self.count)]


class BrokenProvider(Provider):
	name = "broken"

	def slides(self, now):
		raise RuntimeError("website down")


class RotationTest(unittest.TestCase):
	def test_rounds_follow_provider_order_and_repeat(self):
		scheduler = Scheduler([FixedProvider("a", 2), FixedProvider("b", 1)], [])
		now = at(THURSDAY, "10:00:00")
		names = [scheduler.next_slide(now).data["name"] for _ in range(6)]
		self.assertEqual(names, ["a0", "a1", "b0", "a0", "a1", "b0"])

	def test_broken_provider_is_skipped(self):
		scheduler = Scheduler([BrokenProvider(), FixedProvider("a", 1)], [])
		with self.assertLogs("francken_tv.scheduler", "ERROR"):
			self.assertEqual(scheduler.next_slide(at(THURSDAY, "10:00:00")).data["name"], "a0")

	def test_nothing_to_show(self):
		self.assertIs(Scheduler([], []).next_slide(at(THURSDAY, "10:00:00")), EMPTY_SLIDE)


class BieruurTest(unittest.TestCase):
	def setUp(self):
		self.settings = BieruurSettings()
		self.scheduler = Scheduler([FixedProvider("a", 3)], [BieruurTakeover(self.settings)])

	def test_takeover_window_is_two_minutes_before_until_two_minutes_after(self):
		takeover = BieruurTakeover(self.settings)
		self.assertIsNone(takeover.slide(at(THURSDAY, "15:57:59")))
		self.assertIsNotNone(takeover.slide(at(THURSDAY, "15:58:00")))
		self.assertIsNotNone(takeover.slide(at(THURSDAY, "16:01:59")))
		self.assertIsNone(takeover.slide(at(THURSDAY, "16:02:00")))

	def test_takeover_slide_lasts_until_end_of_window_and_ticks(self):
		slide = self.scheduler.next_slide(at(THURSDAY, "15:59:00"))
		self.assertEqual(slide.template, "bieruur.html")
		self.assertEqual(slide.seconds, 180)
		self.assertEqual(slide.refresh_seconds, 1)
		self.assertEqual(slide.update(at(THURSDAY, "15:59:30"))["countdown"], "00:30")
		self.assertEqual(slide.update(at(THURSDAY, "15:59:30"))["state"], "final")
		self.assertEqual(slide.update(at(THURSDAY, "16:00:00")), {"state": "bieruur"})

	def test_slide_before_takeover_is_cut_short(self):
		slide = self.scheduler.next_slide(at(THURSDAY, "15:57:57"))
		self.assertEqual(slide.template, "image.html")
		self.assertEqual(slide.seconds, 3)

	def test_countdown_in_rotation_only_before_takeover(self):
		provider = BieruurCountdownProvider(self.settings)
		self.assertEqual(len(provider.slides(at(THURSDAY, "09:00:00"))), 1)
		self.assertEqual(provider.slides(at(THURSDAY, "15:58:00")), [])
		self.assertEqual(provider.slides(at(THURSDAY, "17:00:00")), [])

	def test_countdown_text(self):
		bieruur = at(THURSDAY, "16:00:00")
		data = countdown_data(at(THURSDAY, "09:30:05"), bieruur)
		self.assertEqual((data["countdown"], data["state"]), ("6:29:55", "countdown"))

	def test_clock_hands(self):
		data = countdown_data(at(THURSDAY, "15:30:15"), at(THURSDAY, "16:00:00"))
		self.assertAlmostEqual(data["hour_angle"], 105.12, places=2)    # halfway between 3 and 4
		self.assertAlmostEqual(data["minute_angle"], 181.5)
		self.assertEqual(data["second_angle"], 90)
		self.assertEqual(data["bieruur_number"], 4)

	def test_wedge_from_now_until_bieruur(self):
		bieruur = at(THURSDAY, "16:00:00")
		self.assertTrue(countdown_data(at(THURSDAY, "13:00:00"), bieruur)["wedge"].startswith("M 100 100"))
		self.assertEqual(countdown_data(at(THURSDAY, "03:00:00"), bieruur)["wedge"], "")   # more than 12 hours away

	def test_glass_fills_up_during_the_day(self):
		bieruur = at(THURSDAY, "16:00:00")
		tops = [countdown_data(at(THURSDAY, t), bieruur)["beer_top"] for t in ("07:00:00", "08:00:00", "12:00:00", "15:59:59")]
		self.assertEqual(tops[0], tops[1])         # empty until 08:00
		self.assertGreater(tops[1], tops[2])       # the surface rises (smaller y)...
		self.assertGreater(tops[2], tops[3])
		self.assertAlmostEqual(tops[3], 30, places=0)   # ...until the glass is full

	def test_days_setting(self):
		settings = BieruurSettings(days=("friday",))
		self.assertIsNone(BieruurTakeover(settings).slide(at(THURSDAY, "15:59:00")))
		self.assertIsNotNone(BieruurTakeover(settings).slide(at(FRIDAY, "15:59:00")))


class VrijmiboTest(unittest.TestCase):
	def setUp(self):
		DATA_DIR.mkdir(exist_ok=True)
		self.folder = TemporaryDirectory(dir=DATA_DIR)   # media_url() only serves files inside the project
		path = Path(self.folder.name) / "vrijmibo.gif"
		frames = [Image.new("RGB", (4, 4), color) for color in ("red", "blue", "green", "white")]
		frames[0].save(path, save_all=True, append_images=frames[1:], duration=500, loop=0)
		self.takeover = VrijmiboTakeover({"file": str(path)})

	def tearDown(self):
		self.folder.cleanup()

	def test_only_on_fridays(self):
		self.assertIsNone(self.takeover.slide(at(THURSDAY, "12:00:00")))
		self.assertIsNotNone(self.takeover.slide(at(FRIDAY, "12:00:00")))

	def test_once_every_15_minutes(self):
		shown = [self.takeover.slide(at(FRIDAY, t)) is not None for t in ("12:00:00", "12:05:00", "12:14:59", "12:15:00", "12:16:00")]
		self.assertEqual(shown, [True, False, False, True, False])

	def test_plays_gif_once(self):
		self.assertEqual(self.takeover.slide(at(FRIDAY, "12:00:00")).seconds, 2.0)

	def test_bieruur_wins_over_vrijmibo(self):
		scheduler = Scheduler([FixedProvider("a", 1)], [BieruurTakeover(BieruurSettings()), self.takeover])
		self.assertEqual(scheduler.next_slide(at(FRIDAY, "16:00:00")).template, "bieruur.html")
		# The vrijmibo slot that bieruur pushed aside still gets its turn afterwards.
		self.assertIn("vrijmibo.gif", scheduler.next_slide(at(FRIDAY, "16:02:00")).data["url"])

	def test_vrijmibo_is_cut_short_when_bieruur_starts(self):
		scheduler = Scheduler([], [BieruurTakeover(BieruurSettings()), self.takeover])
		self.assertEqual(scheduler.next_slide(at(FRIDAY, "15:57:59")).seconds, 1.0)

if __name__ == "__main__":
	unittest.main()
