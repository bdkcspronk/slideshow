import time
import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image

from francken_tv.background import BackgroundRunner
from francken_tv.clock import Clock
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

	def test_special_slides_are_spread_between_the_images(self):
		images = FixedProvider("images", 26)
		scheduler = Scheduler([images, FixedProvider("special", 6)], [])
		names = [slide.data["name"] for slide in scheduler.build_round(at(THURSDAY, "10:00:00"))]
		positions = [i for i, name in enumerate(names) if name.startswith("special")]
		gaps = [b - a - 1 for a, b in zip([-1] + positions, positions)]
		self.assertEqual(gaps, [5, 4, 4, 5, 4, 4])   # posters between consecutive special slides
		self.assertEqual(names[-1], "special5")         # the round ends with a special slide
		self.assertEqual([n for n in names if n.startswith("special")], [f"special{i}" for i in range(6)])

	def test_daytime_only_slides_rest_from_bieruur_until_the_morning(self):
		from datetime import time
		scheduler = Scheduler([FixedProvider("images", 1), FixedProvider("info", 1), FixedProvider("books", 1)], [],
			daytime_only={"info", "books"}, daytime=(time(8, 0), time(16, 0)))
		names = lambda hhmm: [slide.data["name"] for slide in scheduler.build_round(at(THURSDAY, hhmm + ":00"))]
		self.assertEqual(names("07:59"), ["images0"])
		self.assertEqual(names("08:00"), ["images0", "info0", "books0"])
		self.assertEqual(names("15:59"), ["images0", "info0", "books0"])
		self.assertEqual(names("16:00"), ["images0"])   # bieruur
		self.assertEqual(names("23:30"), ["images0"])

	def test_outside_the_daytime_a_provider_can_still_show_something(self):
		from datetime import time
		class Info(FixedProvider):
			def outside_daytime_slides(self, now):
				return [Slide("info_weather.html", 8, {"name": "rain"})]   # e.g. rain coming
		scheduler = Scheduler([FixedProvider("images", 1), Info("info", 1)], [], daytime_only={"info"}, daytime=(time(8, 0), time(16, 0)))
		self.assertEqual([s.data["name"] for s in scheduler.build_round(at(THURSDAY, "21:00:00"))], ["images0", "rain"])
		self.assertEqual([s.data["name"] for s in scheduler.build_round(at(THURSDAY, "10:00:00"))], ["images0", "info0"])

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

	def test_beer_fills_up_during_the_day(self):
		bieruur = at(THURSDAY, "16:00:00")
		levels = [countdown_data(at(THURSDAY, t), bieruur)["beer_level"] for t in ("07:00:00", "08:00:00", "12:00:00", "15:59:59")]
		self.assertEqual(levels[:3], [0, 0, 50])      # empty until 08:00, half full at noon...
		self.assertAlmostEqual(levels[3], 100, places=1)   # ...full at bieruur

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


class BackgroundTest(unittest.TestCase):
	def test_refresh_soon_after_midnight(self):
		class Daily(Provider):
			name, refresh_seconds, refreshed = "daily", 1800, 0
			def refresh(self, now):
				self.refreshed += 1
		daily = Daily()
		runner = BackgroundRunner(Clock(datetime(2026, 10, 14, 23, 59, 0)), [daily], [])
		runner.stopped.wait = lambda seconds: runner.stopped.set()   # run the loop once
		runner.online = lambda: True
		runner.refresh_loop()
		due_in = runner.status["daily"].next_due - time.monotonic()
		self.assertEqual(daily.refreshed, 1)
		self.assertTrue(85 <= due_in <= 91, due_in)   # 00:00:30, not 00:29


	def test_a_site_that_is_down_is_logged_without_a_traceback(self):
		import requests
		class Down(Provider):
			name, refresh_seconds = "down", 60
			def refresh(self, now):
				raise requests.HTTPError("503 Server Error: Service Unavailable")
		class Bug(Provider):
			name, refresh_seconds = "bug", 60
			def refresh(self, now):
				raise KeyError("oops")
		runner = BackgroundRunner(Clock(), [Down(), Bug()], [])
		runner.stopped.wait = lambda seconds: runner.stopped.set()   # run the loop once
		runner.online = lambda: True
		with self.assertLogs("francken_tv.background") as logs:
			runner.refresh_loop()
		self.assertEqual([(record.levelname, record.exc_info is not None) for record in logs.records],
			[("WARNING", False), ("ERROR", True)])   # a bug still gets its traceback
		self.assertIn("503", runner.status["down"].last_error)   # and both show on /status


	def test_without_the_network_nothing_refreshes_and_it_is_logged_once(self):
		class Site(Provider):
			name, refresh_seconds, refreshed = "site", 3600, 0
			def refresh(self, now):
				self.refreshed += 1
		site = Site()
		runner = BackgroundRunner(Clock(), [site], [])
		runner.status["site"].next_due = time.monotonic() - 1
		network = iter([False, False, False, True])
		runner.online = lambda: next(network)
		rounds = iter(range(4))
		runner.stopped.wait = lambda seconds: next(rounds, None) is None and runner.stopped.set()
		with self.assertLogs("francken_tv.background") as logs:
			runner.refresh_loop()
		self.assertEqual(site.refreshed, 1)   # only once the network was back
		self.assertEqual([record.levelname for record in logs.records], ["WARNING", "INFO"])   # lost, back: no error per try
		self.assertIn("Lost the network", logs.records[0].getMessage())
		self.assertIsNone(runner.offline_since)


if __name__ == "__main__":
	unittest.main()
