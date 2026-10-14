import unittest
from datetime import date, datetime
from pathlib import Path

from francken_tv.providers.activities import ActivitiesProvider, parse_activities

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

	def test_no_slide_without_activities(self):
		self.assertEqual(ActivitiesProvider({}, 8).slides(datetime(2026, 10, 17)), [])


if __name__ == "__main__":
	unittest.main()
