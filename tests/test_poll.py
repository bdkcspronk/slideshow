"""The weekly dilemma."""

import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from francken_tv.providers.poll import PollProvider, count_form_votes, form_answer, parse_dilemma, parse_timestamp

MONDAY = datetime(2026, 10, 19, 12, 0)


class PollTest(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.path = Path(self.folder.name) / "dilemmas.txt"
		self.path.write_text("# comment\nTea or coffee? | Tea | Coffee\nnot a dilemma\nCats or dogs? | Cats | Dogs\n", encoding="utf-8")
		self.state = Path(self.folder.name) / "poll.json"
		self.provider = PollProvider({"file": str(self.path), "form_url": "https://forms.gle/x"}, 8, self.state)

	def tearDown(self):
		self.folder.cleanup()

	def vote(self, choice, now=MONDAY):
		self.clock = getattr(self, "clock", 100.0) + 10   # people voting one after another, not quick taps
		with mock.patch("francken_tv.providers.poll.time.monotonic", return_value=self.clock):
			slide, _ = self.provider.action("vote", [choice], now)
		return slide.data

	def test_a_new_dilemma_every_week_in_order(self):
		questions = [self.provider.slides(MONDAY + timedelta(weeks=week))[0].data["question"] for week in range(3)]
		self.assertEqual(questions, ["Tea or coffee?", "Cats or dogs?", "Tea or coffee?"])   # the line that isn't a dilemma is skipped

	def test_votes_on_the_tv_count_and_survive_a_restart(self):
		self.vote("a")
		data = self.vote("b")
		data = self.vote("a")
		self.assertEqual([(o["votes"], o["percent"]) for o in data["options"]], [(2, 67), (1, 33)])
		self.assertEqual((data["total"], data["voted"]), (3, "a"))
		again = PollProvider({"file": str(self.path)}, 8, self.state)
		self.assertEqual(again.slides(MONDAY + timedelta(days=3))[0].data["total"], 3)
		self.assertEqual(again.slides(MONDAY + timedelta(weeks=1))[0].data["total"], 0)   # a new week starts at zero

	def test_last_weeks_outcome(self):
		self.assertIsNone(self.provider.slides(MONDAY)[0].data["last_week"])   # no history yet
		self.vote("b")
		self.vote("b")
		self.vote("a")
		next_week = PollProvider({"file": str(self.path)}, 8, self.state)   # after a restart, too
		data = next_week.slides(MONDAY + timedelta(weeks=1))[0].data
		self.assertEqual(data["question"], "Cats or dogs?")
		last = data["last_week"]
		self.assertEqual((last["question"], last["total"], last["winner"], last["percent"]), ("Tea or coffee?", 3, "Coffee", 67))
		self.assertEqual([(o["text"], o["percent"], o["won"]) for o in last["options"]], [("Tea", 33, False), ("Coffee", 67, True)])   # the bars

	def test_last_week_keeps_its_own_dilemma_and_late_form_votes_count(self):
		self.vote("a")
		self.path.write_text("Tea or coffee!? | Tea | Coffee\nCats or dogs? | Cats | Dogs\n", encoding="utf-8")   # edited later
		sheet = "Timestamp,Answer\n25-10-2026 23:58:00,coffee\n25-10-2026 23:59:00,Coffee\n26-10-2026 09:00:00,Dogs\n"
		response = mock.Mock(content=sheet.encode(), raise_for_status=lambda: None)
		with mock.patch("francken_tv.providers.poll.requests.get", return_value=response):
			self.provider.refresh(MONDAY + timedelta(weeks=1))
		data = self.provider.slides(MONDAY + timedelta(weeks=1))[0].data
		self.assertEqual([o["votes"] for o in data["options"]], [0, 1])   # this week: Dogs
		self.assertEqual((data["last_week"]["winner"], data["last_week"]["total"]), ("Coffee", 3))
		self.assertEqual(data["last_week"]["question"], "Tea or coffee?")   # as it was that week

	def test_a_tie(self):
		self.vote("a")
		self.vote("b")
		last = self.provider.slides(MONDAY + timedelta(weeks=1))[0].data["last_week"]
		self.assertEqual((last["winner"], last["total"]), (None, 2))

	def test_quick_taps_count_once(self):
		with mock.patch("francken_tv.providers.poll.time.monotonic", side_effect=[100.0, 100.0, 101.0]):
			self.provider.action("vote", ["a"], MONDAY)
			slide, _ = self.provider.action("vote", ["a"], MONDAY)
		self.assertEqual(slide.data["total"], 1)

	def test_with_a_form_no_slide_until_its_votes_are_read(self):
		provider = PollProvider({"file": str(self.path), "sheet_id": "sheet"}, 8, self.state)
		self.assertEqual(provider.slides(MONDAY), [])   # just started
		with mock.patch("francken_tv.providers.poll.requests.get", side_effect=OSError("offline")):
			with self.assertRaises(OSError):
				provider.refresh(MONDAY)
		self.assertEqual(provider.slides(MONDAY), [])   # reading failed: still not
		response = mock.Mock(content=b"Timestamp,Answer\n", raise_for_status=lambda: None)
		with mock.patch("francken_tv.providers.poll.requests.get", return_value=response):
			provider.refresh(MONDAY)
		self.assertEqual(len(provider.slides(MONDAY)), 1)

	def test_form_votes_of_this_week_are_added(self):
		sheet = "Timestamp,Which one?\n18-10-2026 23:59:00,A\n19-10-2026 09:00:00,A: tea\n20-10-2026 10:00:00,B\n21-10-2026 10:00:00,\n26-10-2026 00:00:00,B\n"
		response = mock.Mock(content=sheet.encode(), raise_for_status=lambda: None)
		with mock.patch("francken_tv.providers.poll.requests.get", return_value=response):
			self.provider.refresh(MONDAY)
		data = self.provider.slides(MONDAY)[0].data
		self.assertEqual([o["votes"] for o in data["options"]], [1, 1])   # Sunday and next Monday don't count
		self.assertEqual(data["form_url"], "https://forms.gle/x")

	def test_form_answers_by_text_or_letter(self):
		shower = parse_dilemma("Hot or cold? | A very hot shower | A cold shower")
		self.assertEqual(form_answer("a very hot shower!", shower), "a")
		self.assertEqual(form_answer("A cold shower", shower), "b")   # starts with "A", but it's option B
		self.assertEqual(form_answer("B: cold", shower), "b")
		self.assertEqual(form_answer("A", None), "a")
		self.assertIsNone(form_answer("Always hot", None))

	def test_american_sheet_dates_are_recognised(self):
		sheet = "Timestamp,Answer\n10/19/2026 17:52:41,Very cold\n10/05/2026 10:00:00,Very hot\n"   # like the real sheet
		dilemma = parse_dilemma("Hot or cold? | Very hot | Very cold")
		self.assertEqual(count_form_votes(sheet, date(2026, 10, 19), True, dilemma), {"a": 0, "b": 1})   # day first set, but the 19 says otherwise

	def test_timestamps(self):
		self.assertEqual(parse_timestamp("19-10-2026 14:03:12"), datetime(2026, 10, 19, 14, 3))
		self.assertEqual(parse_timestamp("10/19/2026 14:03:12", day_first=False), datetime(2026, 10, 19, 14, 3))
		self.assertEqual(parse_timestamp("2026-10-19 14:03"), datetime(2026, 10, 19, 14, 3))
		self.assertIsNone(parse_timestamp("yesterday"))

	def test_dilemma_lines(self):
		self.assertEqual(parse_dilemma("Q? | A | B").b, "B")
		self.assertIsNone(parse_dilemma("Q? | A"))
		self.assertEqual(count_form_votes("", date(2026, 10, 19)), {"a": 0, "b": 0})

	def test_the_real_file_has_dilemmas(self):
		provider = PollProvider({}, 8)
		self.assertTrue(provider.slides(MONDAY))


if __name__ == "__main__":
	unittest.main()
