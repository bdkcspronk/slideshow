import unittest
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


if __name__ == "__main__":
	unittest.main()
