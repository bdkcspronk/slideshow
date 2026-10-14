"""Puzzle progress survives a restart of the slideshow (a new provider reading the same file)."""

import unittest
from datetime import date, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.providers.catfishing import CatfishingProvider, parse_game
from francken_tv.providers.connections import ConnectionsProvider, parse_puzzle
from francken_tv.providers.wordle import WordleProvider
from tests.test_catfishing import fake_game
from tests.test_connections import fake_puzzle, group

NOW = datetime(2026, 10, 14, 12, 0)
TOMORROW = datetime(2026, 10, 15, 12, 0)


def connections(path):
	provider = ConnectionsProvider({}, 8, path)
	provider.fetch = lambda day: parse_puzzle(fake_puzzle(day.isoformat()))
	return provider


def wordle(path):
	provider = WordleProvider({}, 8, path)
	provider.valid_words = set()
	provider.fetch = lambda day: "CRANE"
	return provider


def catfishing(path):
	provider = CatfishingProvider({}, 8, path)
	provider.fetch = lambda day: parse_game(fake_game())
	return provider


class SavedGamesTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.dir = Path(self.folder.name)

	def tearDown(self):
		self.folder.cleanup()

	def restart(self, make, name, when=NOW):
		provider = make(self.dir / f"{name}.json")
		provider.refresh(when)
		return provider

	def test_connections_progress_is_restored(self):
		before = self.restart(connections, "connections")
		before.action("submit", group(2), NOW)
		before.action("submit", group(0)[:2] + group(1)[:2], NOW)   # a mistake
		after = self.restart(connections, "connections")
		data = after.slides(NOW)[0].data
		self.assertEqual(([level for level, _, _ in data["groups"]], data["mistakes_left"]), ([2], 3))
		self.assertEqual(data["words"], before.slides(NOW)[0].data["words"])
		self.assertEqual(after.status(NOW).text, "1 of 4 groups found")

	def test_wordle_progress_is_restored(self):
		self.restart(wordle, "wordle").action("submit", ["SLATE"], NOW)
		after = self.restart(wordle, "wordle")
		self.assertEqual(after.status(NOW).text, "1 of 6 guesses used")
		self.assertEqual("".join(letter for letter, _ in after.slides(NOW)[0].data["rows"][0]["cells"]), "SLATE")

	def test_catfishing_progress_is_restored(self):
		before = self.restart(catfishing, "catfishing")
		before.action("submit", ["beatles"], NOW)
		after = self.restart(catfishing, "catfishing")
		game = after.todays_game(NOW)
		self.assertEqual((game.score, game.showing_answer), (2, True))   # still showing the answer
		self.assertEqual(after.status(NOW).text, "1 of 10 answered · 2 points")

	def test_yesterdays_game_is_not_restored(self):
		self.restart(wordle, "wordle").action("submit", ["SLATE"], NOW)
		self.assertEqual(self.restart(wordle, "wordle", TOMORROW).status(TOMORROW).text, "Not tried yet")

	def test_unreadable_file_starts_a_new_game(self):
		(self.dir / "wordle.json").write_text("{not json")
		with self.assertLogs("francken_tv.providers.puzzles", "WARNING"):
			self.assertEqual(self.restart(wordle, "wordle").status(NOW).text, "Not tried yet")


if __name__ == "__main__":
	unittest.main()
