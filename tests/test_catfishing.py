import json
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from francken_tv.providers.catfishing import CatfishingProvider, normalise, parse_game

NOW = datetime(2026, 10, 14, 12, 0)


def fake_game() -> dict:
	"""Same shape as the catfishing.net JSON, with made-up articles."""
	articles = [
		{"title": "The Beatles", "categories": ["English rock music groups"], "names": ["Beatles", "Fab Four"], "namesVeto": ["Paul"]},
		{"title": "Café de Flore", "categories": ["Coffeehouses in Paris"], "names": []},
		{"title": "1990 FIFA World Cup", "categories": ["FIFA World Cup tournaments"], "names": ["Italia 90"]},
	] + [{"title": f"Article {i}", "categories": ["Things"], "names": []} for i in range(3, 10)]
	previews = [{"extract": "An English rock band.", "thumbnail": {"url": "https://upload.wikimedia.org/x.jpg", "artist": "Someone", "licenseShortName": "CC BY-SA 4.0"}}] + [None] * 9
	return {"articles": articles, "previews": previews}


class MatchingTest(unittest.TestCase):
	def setUp(self):
		self.beatles, self.cafe, self.world_cup = parse_game(fake_game())[:3]

	def test_normalise_like_the_site(self):
		self.assertEqual(normalise("The Beatles (band)"), "beatles")
		self.assertEqual(normalise("Café de Flore"), "cafe de flore")
		self.assertEqual(normalise("Rock & Roll!"), "rock and roll")

	def test_correct_names(self):
		self.assertEqual(self.beatles.check("the beatles"), ("correct", "The Beatles"))
		self.assertEqual(self.beatles.check("FAB FOUR"), ("correct", "Fab Four"))
		self.assertEqual(self.cafe.check("cafe de flore"), ("correct", "Café de Flore"))

	def test_typos_ask_did_you_mean(self):
		self.assertEqual(self.beatles.check("beetles"), ("did_you_mean", "The Beatles"))
		self.assertEqual(self.cafe.check("cafe de flor"), ("did_you_mean", "Café de Flore"))

	def test_numbers_must_match(self):
		self.assertEqual(self.world_cup.check("1994 FIFA World Cup"), ("incorrect", None))
		self.assertEqual(self.world_cup.check("1990 FIFA Wrld Cup"), ("did_you_mean", "1990 FIFA World Cup"))

	def test_vetoed_and_short_guesses_are_wrong(self):
		self.assertEqual(self.beatles.check("Paul"), ("incorrect", None))
		self.assertEqual(self.beatles.check("bea"), ("incorrect", None))


class CatfishingGameTest(unittest.TestCase):
	def setUp(self):
		self.provider = CatfishingProvider({}, 8)
		self.provider.fetch = lambda day: parse_game(fake_game())
		self.provider.refresh(NOW)

	def act(self, name, *values):
		slide, message = self.provider.action(name, list(values), NOW)
		return slide.data, message

	def test_day_numbering(self):
		self.assertEqual(CatfishingProvider.day_number(date(2024, 6, 23)), 0)
		self.assertEqual(CatfishingProvider.day_number(date(2026, 10, 14)), 843)

	def test_correct_answer_then_next(self):
		data, _ = self.act("submit", "beatles")
		self.assertEqual((data["last"].result, data["game"].score), ("correct", 2))
		self.assertEqual(data["article"].title, "The Beatles")   # the answer is shown...
		data, _ = self.act("next")
		self.assertEqual(data["article"].title, "Café de Flore")   # ... until Next
		self.assertEqual(data["number"], 2)

	def test_did_you_mean_yes_and_no(self):
		data, _ = self.act("submit", "beetles")
		self.assertEqual(data["game"].did_you_mean, "The Beatles")
		data, _ = self.act("did_you_mean", "no")
		self.assertEqual((data["typed"], data["game"].answers), ("beetles", []))   # back to typing
		self.act("submit", "beetles")
		data, _ = self.act("did_you_mean", "yes")
		self.assertEqual(data["last"].result, "correct")

	def test_old_did_you_mean_click_is_ignored(self):
		# E.g. "Yes" on an old copy of the slide after skipping back: nothing is pending, nothing happens.
		data, _ = self.act("did_you_mean", "yes")
		self.assertEqual(data["game"].answers, [])

	def test_wrong_answer_can_be_marked_close_enough(self):
		self.act("submit", "The Rolling Stones")
		data, _ = self.act("close")
		self.assertEqual((data["last"].result, data["game"].score), ("close", 1))
		data, _ = self.act("close")
		self.assertEqual(data["game"].score, 0)   # undo

	def test_whole_game_and_status(self):
		self.assertEqual(self.provider.status(NOW).text, "Not tried yet")
		self.act("submit", "beatles")
		self.act("next")
		self.assertEqual(self.provider.status(NOW).text, "1 of 10 answered · 2 points")
		for _ in range(9):
			self.act("skip")
			data, _ = self.act("next")
		self.assertTrue(data["game"].done)
		self.assertEqual(len(data["summary"]), 10)
		self.assertEqual(self.provider.status(NOW).text, "Done: 2 of 20 points")

	def test_empty_guess_is_not_an_answer(self):
		data, message = self.act("submit", "   ")
		self.assertEqual((message, data["game"].answers), ("Type a guess, or skip", []))


class CatfishingArchiveTest(unittest.TestCase):
	"""Earlier days from catfishing.net's archive, and the history of every day played."""

	def setUp(self):
		self.folder = tempfile.TemporaryDirectory()
		self.addCleanup(self.folder.cleanup)
		folder = Path(self.folder.name)
		self.state, self.history = folder / "catfishing.json", folder / "catfishing_history.json"
		self.provider = self.new_provider()

	def new_provider(self):
		provider = CatfishingProvider({}, 8, self.state, self.history)
		provider.fetch = lambda day: parse_game(fake_game())
		provider.refresh(NOW)
		return provider

	def act(self, name, *values):
		return self.provider.action(name, list(values), NOW)[0]

	def test_play_an_earlier_day_and_finish_it_later(self):
		slide = self.act("open_day", "2026-09-14")
		self.assertEqual((slide.data["today"], slide.data["day_label"]), (False, "14 Sep 2026"))
		self.act("submit", "beatles")
		self.act("next")
		self.assertEqual(self.provider.status(NOW).text, "Not tried yet")   # today's game is untouched
		later = self.new_provider()   # e.g. after a restart
		self.provider = later
		slide = self.act("open_day", "2026-09-14")
		self.assertEqual(len(slide.data["game"].answers), 1)   # carries on where it was left
		self.assertEqual(self.act("today").data["today"], True)

	def test_calendar_shows_done_and_started_days(self):
		self.act("open_day", "2026-10-01")
		for _ in range(10):
			self.act("skip")
			self.act("next")
		self.act("open_day", "2026-10-02")
		self.act("skip")
		slide = self.act("archive", "2026-10")
		days = {day["date"]: day for week in slide.data["weeks"] for day in week if day["in_month"]}
		self.assertEqual((days[date(2026, 10, 1)]["state"], days[date(2026, 10, 1)]["text"]), ("done", "0/20"))
		self.assertEqual((days[date(2026, 10, 2)]["state"], days[date(2026, 10, 2)]["text"]), ("playing", "1/10"))
		self.assertEqual(days[date(2026, 10, 3)]["state"], "new")
		self.assertTrue(days[date(2026, 10, 14)]["today"])
		self.assertFalse(days[date(2026, 10, 15)]["playable"])   # the future
		self.assertEqual((slide.data["done"], slide.data["started"], slide.data["next"]), (1, 1, None))

	def test_archive_limits(self):
		self.assertIsNone(self.act("archive", "2024-07").data["previous"])   # the archive starts in July 2024
		self.assertEqual(self.act("archive", "2020-01").data["month"], date(2024, 7, 1))
		self.assertTrue(self.act("open_day", "2024-06-30").data["today"])   # before the archive: today's game instead

	def test_starting_today_over_forgets_it_in_the_history(self):
		self.act("skip")
		self.assertIn("2026-10-14", json.loads(self.history.read_text()))
		self.state.unlink()   # what "start over" in the menu does
		self.provider.game = None
		self.provider.todays_game(NOW)
		self.assertNotIn("2026-10-14", json.loads(self.history.read_text()))


if __name__ == "__main__":
	unittest.main()
