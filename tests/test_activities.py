import unittest
from datetime import date, datetime
from pathlib import Path

from francken_tv.providers.activities import ActivitiesProvider, end_day, parse_activities

FIXTURE = Path(__file__).parent / "fixtures" / "activities.html"


class ParseActivitiesTest(unittest.TestCase):
	def setUp(self):
		self.activities = parse_activities(FIXTURE.read_text(encoding="utf-8"))

	def test_finds_activities_in_date_order(self):
		self.assertGreater(len(self.activities), 10)
		self.assertEqual([a.day for a in self.activities], sorted(a.day for a in self.activities))

	def test_reads_title_time_and_location(self):
		first = self.activities[0]
		self.assertEqual((first.day, first.title, first.time, first.location), (date(2026, 10, 14), "I-GMA", "17:00", "Francken room"))

	def test_activity_without_location(self):
		cleaning = next(a for a in self.activities if a.title == "Spring cleaning!")
		self.assertIsNone(cleaning.location)
		self.assertEqual(cleaning.time, "12:00")


class ActivitiesProviderTest(unittest.TestCase):
	def test_shows_only_upcoming_activities(self):
		provider = ActivitiesProvider({"max_events": 3}, 8)
		provider.activities = parse_activities(FIXTURE.read_text(encoding="utf-8"))
		[slide] = provider.slides(datetime(2026, 10, 17, 12, 0))
		self.assertEqual(len(slide.data["activities"]), 3)
		self.assertTrue(all(a.day >= date(2026, 10, 17) for a in slide.data["activities"]))

	def test_todays_activities_go_across_both_columns(self):
		provider = ActivitiesProvider({"max_events": 10}, 8)
		provider.activities = parse_activities(FIXTURE.read_text(encoding="utf-8"))
		[slide] = provider.slides(datetime(2026, 10, 27, 8, 0))   # two practice sessions that day
		self.assertEqual([a.title for a in slide.data["current"]], ["Quantum Mechanics Practice Session", "Solid State Physics Practice Session"])
		self.assertEqual(len(slide.data["activities"]), 6)   # two wide cards take the room of four
		self.assertTrue(all(a.day > date(2026, 10, 27) for a in slide.data["activities"]))

	def test_an_activity_of_several_days_is_shown_while_it_goes_on(self):
		weekend = next(a for a in parse_activities(FIXTURE.read_text(encoding="utf-8")) if a.title == "Members weekend")
		self.assertEqual((weekend.day, weekend.end), (date(2026, 11, 27), date(2026, 11, 30)))   # "27 - 30 November at 01:00"
		provider = ActivitiesProvider({}, 8)
		provider.activities = [weekend]
		[slide] = provider.slides(datetime(2026, 11, 29, 12, 0))   # day 3 of 4
		self.assertEqual(slide.data["current"], [weekend])
		self.assertEqual(provider.slides(datetime(2026, 12, 1, 12, 0)), [])   # over

	def test_end_days(self):
		self.assertEqual(end_day(date(2026, 11, 30), "30 November - 2 December at 18:00"), date(2026, 12, 2))
		self.assertEqual(end_day(date(2026, 12, 30), "30 December - 2 January"), date(2027, 1, 2))
		self.assertIsNone(end_day(date(2026, 10, 14), "14 October at 17:00"))

	def test_no_slide_without_activities(self):
		self.assertEqual(ActivitiesProvider({}, 8).slides(datetime(2026, 10, 17)), [])


if __name__ == "__main__":
	unittest.main()
