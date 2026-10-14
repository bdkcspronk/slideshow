import unittest
from datetime import date, datetime

from francken_tv.providers.wordle import WordleProvider, key_states, score

NOW = datetime(2026, 10, 14, 12, 0)


class ScoreTest(unittest.TestCase):
	def test_greens_yellows_greys(self):
		self.assertEqual(score("CRANE", "TRACE"), ["present", "correct", "correct", "absent", "correct"])

	def test_repeated_letter_only_counts_as_often_as_in_the_word(self):
		# Two E's guessed, one E in the word (in the right place): the other E is grey.
		self.assertEqual(score("EERIE", "THEME")[4], "correct")
		self.assertEqual(score("SPEED", "ABIDE"), ["absent", "absent", "present", "absent", "present"])
		self.assertEqual(score("EERIE", "ABIDE"), ["absent", "absent", "absent", "present", "correct"])

	def test_keyboard_shows_the_best_result(self):
		states = key_states(["TRACE", "CRANE"], "CRANE")
		self.assertEqual((states["C"], states["T"], states["N"]), ("correct", "absent", "correct"))


class WordleGameTest(unittest.TestCase):
	def setUp(self):
		self.provider = WordleProvider({}, 8)
		self.provider.valid_words = {"CRANE", "SLATE", "TRACE", "ABOUT", "PLANE", "GRAPE", "BRAKE"}
		self.provider.fetch = lambda day: {date(2026, 10, 14): "CRANE", date(2026, 10, 13): "ABOUT"}[day]
		self.provider.refresh(NOW)

	def submit(self, word):
		slide, message = self.provider.action("submit", [word], NOW)
		return slide.data, message

	def test_guess_fills_a_row_and_reveals_it(self):
		data, message = self.submit("slate")
		self.assertIsNone(message)
		self.assertEqual(data["new_row"], 0)
		self.assertEqual(data["rows"][0]["cells"][2], ("A", "correct"))
		self.assertTrue(data["rows"][1]["input"])   # the next row is where you type
		self.assertEqual(data["yesterday"], "ABOUT")

	def test_invalid_guesses_shake_and_keep_the_letters(self):
		data, message = self.submit("CRAN")
		self.assertEqual((message, data["shake"]), ("Not enough letters", True))
		data, message = self.submit("XXXXX")
		self.assertEqual(message, "Not in word list")
		self.assertEqual("".join(letter for letter, _ in data["rows"][0]["cells"]), "XXXXX")
		self.assertTrue(data["rows"][0]["input"])   # nothing was used up

	def test_winning(self):
		self.submit("SLATE")
		data, message = self.submit("CRANE")
		self.assertEqual((message, data["won"], data["finished"]), ("Magnificent", True, True))

	def test_losing_shows_the_word(self):
		for word in ["SLATE", "TRACE", "ABOUT", "PLANE", "GRAPE"]:
			self.submit(word)
		data, message = self.submit("BRAKE")
		self.assertEqual((message, data["finished"], data["won"]), ("CRANE", True, False))

	def test_keys_change_colour_after_the_flip(self):
		data, _ = self.submit("SLATE")
		keys = {letter: (state, was) for row in data["keyboard"] for letter, state, was in row}
		self.assertEqual(keys["A"], ("correct", ""))   # was blank, turns green after the flip
		data = self.provider.slides(NOW)[0].data          # later, without a new guess: no delay
		keys = {letter: (state, was) for row in data["keyboard"] for letter, state, was in row}
		self.assertEqual(keys["A"], ("correct", "correct"))

	def test_new_day_new_game(self):
		self.submit("SLATE")
		tomorrow = datetime(2026, 10, 15, 9, 0)
		self.provider.fetch = lambda day: "PLANE"
		self.provider.refresh(tomorrow)
		data = self.provider.slides(tomorrow)[0].data
		self.assertTrue(data["rows"][0]["input"])


if __name__ == "__main__":
	unittest.main()
