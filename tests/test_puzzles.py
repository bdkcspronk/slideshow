import unittest
from pathlib import Path
from datetime import datetime

from francken_tv.providers.connections import ConnectionsProvider, parse_puzzle
from francken_tv.providers.puzzles import PuzzlesProvider
from francken_tv.providers.wordle import WordleProvider
from tests.test_connections import fake_puzzle, group

NOW = datetime(2026, 10, 14, 12, 0)


def make_hub(wordle_works=True):
	connections = ConnectionsProvider({}, 8)
	connections.fetch = lambda day: parse_puzzle(fake_puzzle(day.isoformat()))
	wordle = WordleProvider({}, 8)
	wordle.valid_words = set()

	def fetch_word(day):
		if not wordle_works:
			raise ConnectionError("NYT unreachable")
		return "CRANE"
	wordle.fetch = fetch_word
	return PuzzlesProvider({}, [connections, wordle], 20), connections, wordle


def statuses(hub):
	return {card["name"]: (card["state"], card["status"]) for card in hub.slides(NOW)[0].data["cards"]}


class PuzzlesHubTest(unittest.TestCase):
	def test_status_of_each_puzzle(self):
		hub, connections, wordle = make_hub()
		hub.refresh(NOW)
		self.assertEqual(statuses(hub), {"connections": ("new", "Not tried yet"), "wordle": ("new", "Not tried yet")})
		connections.action("submit", group(0), NOW)
		wordle.action("submit", ["SLATE"], NOW)
		self.assertEqual(statuses(hub), {"connections": ("playing", "1 of 4 groups found"), "wordle": ("playing", "1 of 6 guesses used")})
		wordle.action("submit", ["CRANE"], NOW)
		self.assertEqual(statuses(hub)["wordle"], ("solved", "Solved in 2 guesses"))

	def test_out_of_the_rotation_when_all_are_done(self):
		hub, connections, wordle = make_hub()
		hub.refresh(NOW)
		for number in range(4):
			connections.action("submit", group(number), NOW)   # solved
		self.assertEqual(len(hub.slides(NOW)), 1)   # Wordle still to do
		for word in ["SLATE", "PIANO", "MOUSE", "LIGHT", "BRICK", "DWARF"]:
			wordle.action("submit", [word], NOW)   # lost: done too
		self.assertEqual(hub.slides(NOW), [])
		self.assertEqual(hub.shortcut_slide(NOW).template, "puzzles.html")   # the shortcut and the menu still show it
		self.assertEqual(hub.action("back", [], NOW)[0].template, "puzzles.html")   # "All puzzles" from a finished puzzle
		tomorrow = NOW.replace(day=15)
		hub.refresh(tomorrow)
		self.assertEqual(len(hub.slides(tomorrow)), 1)   # new puzzles: back in the rotation

	def test_high_scores(self):
		from datetime import date
		from tempfile import TemporaryDirectory
		from francken_tv.providers.puzzles import HighScores
		with TemporaryDirectory() as folder:
			path = Path(folder) / "highscores.json"
			scores = HighScores(path)
			self.assertEqual(scores.text("timeguessr"), "")   # none yet
			self.assertTrue(scores.record("timeguessr", 31000, date(2026, 10, 14)))
			self.assertFalse(scores.record("timeguessr", 25000, date(2026, 10, 15)))   # lower: the old one stays
			self.assertFalse(scores.record("timeguessr", 31000, date(2026, 10, 16)))   # as high: the first one stays
			again = HighScores(path)   # after a restart
			self.assertEqual(again.text("timeguessr"), "Highscore: 31,000 \u00b7 14 Oct")
			self.assertEqual(again.best("timeguessr", date(2026, 10, 14))["new"], True)   # set by that day's game
			self.assertEqual(again.best("timeguessr", date(2026, 10, 15))["new"], False)

	def test_open_a_puzzle_and_go_back(self):
		hub, _, _ = make_hub()
		hub.refresh(NOW)
		slide, _ = hub.action("open", ["wordle"], NOW)
		self.assertEqual(slide.template, "wordle.html")
		slide, _ = hub.action("back", [], NOW)
		self.assertEqual(slide.template, "puzzles.html")

	def test_a_puzzle_that_fails_to_load_is_left_out(self):
		hub, _, _ = make_hub(wordle_works=False)
		with self.assertRaises(RuntimeError), self.assertLogs("francken_tv.providers.puzzles", "WARNING"):
			hub.refresh(NOW)   # reported on /status ...
		self.assertEqual(list(statuses(hub)), ["connections"])   # ... but Connections still works

	def test_cards_are_up_to_date_when_the_slide_is_shown(self):
		hub, connections, wordle = make_hub(wordle_works=False)
		with self.assertRaises(RuntimeError), self.assertLogs("francken_tv.providers.puzzles", "WARNING"):
			hub.refresh(NOW)
		[slide] = hub.slides(NOW)   # planned while only Connections was there (like just after midnight)
		connections.action("submit", group(0), NOW)   # then someone plays ...
		wordle.fetch = lambda day: "CRANE"   # ... and the Wordle arrives
		wordle.refresh(NOW)
		wordle.action("submit", ["CRANE"], NOW)
		cards = {card["name"]: card["state"] for card in slide.update(NOW)["cards"]}
		self.assertEqual(cards, {"connections": "playing", "wordle": "solved"})


if __name__ == "__main__":
	unittest.main()
