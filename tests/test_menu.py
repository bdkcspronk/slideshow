import unittest
from datetime import datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from francken_tv import menu
from francken_tv.app import App
from francken_tv.providers.puzzles import PuzzlesProvider
from francken_tv.scheduler import Scheduler
from francken_tv.settings import Settings, load_settings, save_settings
from francken_tv.slides import Provider, Slide
from francken_tv.system_volume import SystemVolume

NOW = datetime(2026, 10, 16, 12, 0)


class Posters(Provider):
	name = "images"

	def slides(self, now):
		return [Slide("image.html", 8), Slide("image.html", 8)]


class Chart(Provider):
	name = "presence"

	def slides(self, now):
		return [Slide("presence.html", 10)]


class Puzzle(Provider):
	name = "wordle"
	title = "Wordle"
	refresh_seconds = 60

	def __init__(self, state_path):
		self.state_path = state_path
		self.game = "today's game"


class SettingsTest(unittest.TestCase):
	def test_changes_are_checked(self):
		self.assertFalse(Settings().permanent_pause)   # a pause ends by itself unless this is switched on
		self.assertTrue(Settings().changed({"permanent_pause": True}).permanent_pause)
		settings = Settings().changed({"muted": True, "volume": 140, "speed": 1.5})
		self.assertEqual((settings.muted, settings.volume, settings.speed), (True, 100, 1.5))
		for wrong in [{"muted": "yes"}, {"speed": 3}, {"volume": True}, {"hidden": "quote"}, {"colour": "red"}]:
			with self.assertRaises(ValueError):
				Settings().changed(wrong)

	def test_saved_settings_win_over_the_config(self):
		with TemporaryDirectory() as folder:
			path = Path(folder) / "settings.json"
			defaults = Settings(quotes_aloud=True, volume=70)
			self.assertEqual(load_settings(path, defaults), defaults)   # nothing saved yet
			save_settings(path, Settings(volume=30, hidden=["quote"]))
			loaded = load_settings(path, defaults)
			self.assertEqual((loaded.volume, loaded.hidden, loaded.quotes_aloud), (30, ["quote"], False))
			path.write_text("{not json")
			self.assertEqual(load_settings(path, defaults), defaults)


class SchedulerSettingsTest(unittest.TestCase):
	def test_speed_shortens_the_slides(self):
		scheduler = Scheduler([Posters()], [])
		scheduler.speed = 2.0
		self.assertEqual(scheduler.next_slide(NOW).seconds, 4)

	def test_a_hidden_slide_type_leaves_the_round_at_once(self):
		scheduler = Scheduler([Posters(), Chart()], [])
		scheduler.next_slide(NOW)   # a round with the chart in it is planned
		scheduler.hide({"presence"})
		templates = {scheduler.next_slide(NOW).template for _ in range(6)}
		self.assertEqual(templates, {"image.html"})


class MenuTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.state = Path(self.folder.name) / "wordle.json"
		self.state.write_text('{"day": "2026-10-16", "guesses": ["CRANE"]}')
		self.puzzle = Puzzle(self.state)
		changed = []
		self.app = SimpleNamespace(
			clock=SimpleNamespace(now=lambda: NOW),
			providers={"puzzles": PuzzlesProvider({}, [self.puzzle], 20), "presence": Chart()},
			shortcuts={"3": "presence"},
			settings=Settings(),
			scheduler=SimpleNamespace(providers=[Chart()]),
			power_commands={"shutdown": ["true"]},
			change_settings=changed.append,
			read_sound=lambda: None,
			devices=SimpleNamespace(reload=lambda: [1, 2]),
		)
		self.changed = changed

	def tearDown(self):
		self.folder.cleanup()

	def test_starting_a_puzzle_over_forgets_the_saved_game(self):
		self.assertEqual(menu.command(self.app, "reset_puzzle", "wordle"), "Started over: Wordle")
		self.assertIsNone(self.puzzle.game)
		self.assertFalse(self.state.exists())
		with self.assertRaises(ValueError):
			menu.command(self.app, "reset_puzzle", "chess")

	def test_settings_and_other_commands(self):
		self.assertIsNone(menu.command(self.app, "settings", {"muted": True}))
		self.assertEqual(self.changed, [{"muted": True}])
		self.assertEqual(menu.command(self.app, "reload_devices", None), "Reloaded 2 devices")
		for name, value in [("settings", "muted"), ("dance", None)]:
			with self.assertRaises(ValueError):
				menu.command(self.app, name, value)

	def test_the_previews_are_the_shortcuts(self):
		self.app.providers["puzzles"].cards = lambda now: []
		data = menu.menu_data(self.app)
		self.assertEqual(data["previews"], [{"key": "3", "name": "presence", "title": "presence", "available": True,
			"empty": "Nothing to show right now"}])
		self.assertEqual(data["power"], ["shutdown"])


class SystemVolumeTest(unittest.TestCase):
	def volume(self, tool, outputs):
		volume = SystemVolume.__new__(SystemVolume)
		volume.wpctl, volume.pactl = ("wpctl", None) if tool == "wpctl" else (None, "pactl")
		volume.output = lambda command: outputs[command[1]]
		volume.commands = []
		volume.run = volume.commands.append
		return volume

	def test_reading_the_output(self):
		self.assertEqual(self.volume("wpctl", {"get-volume": "Volume: 0.40\n"}).get(), (40, False))
		self.assertEqual(self.volume("wpctl", {"get-volume": "Volume: 0.75 [MUTED]\n"}).get(), (75, True))
		pactl = self.volume("pactl", {"get-sink-volume": "Volume: front-left: 26214 /  40% / -23.88 dB,   front-right: ...",
			"get-sink-mute": "Mute: yes"})
		self.assertEqual(pactl.get(), (40, True))

	def test_only_volume_and_mute_change_the_output(self):
		volume = self.volume("wpctl", {})
		announcer = SimpleNamespace(mute=lambda muted: None)
		app = App(clock=None, announcer=announcer, devices=None, providers={}, takeovers={}, jobs=[],
			scheduler=Scheduler([], []), runner=None, screen_size=(1920, 1080), system_volume=volume)
		app.change_settings({"speed": 2.0})
		self.assertEqual(volume.commands, [])
		app.change_settings({"volume": 60, "muted": True})
		self.assertEqual(volume.commands, [["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "0.60"],
			["wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"]])


if __name__ == "__main__":
	unittest.main()
