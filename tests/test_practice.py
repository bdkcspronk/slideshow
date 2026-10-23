"""The practice sessions slide: picked from the activities, two weeks ahead."""

import unittest
from datetime import date, datetime, timedelta

from francken_tv.providers.activities import Activity, ActivitiesProvider
from francken_tv.providers.practice import TICKETS_HEIGHT, PracticeSessionsProvider

NOW = datetime(2026, 10, 23, 14, 30)


def activity(day, title, time="13:00", location=None):
	return Activity(day=day, title=title, time=time, when="", location=location)


class PracticeTest(unittest.TestCase):
	def provider(self, *activities):
		source = ActivitiesProvider({}, 15)
		source.activities = list(activities)
		return PracticeSessionsProvider(source, {}, 15)

	def test_sessions_in_the_next_two_weeks(self):
		provider = self.provider(
			activity(date(2026, 10, 23), "Mechanics and Relativity Practice Session", "13:00"),   # started 1.5 hours ago: still on
			activity(date(2026, 10, 23), "Statistics practice session", "11:00"),                  # over
			activity(date(2026, 10, 26), "Calculus 1 practice session", "11:00"),
			activity(date(2026, 10, 27), "Borrel"),                                                # not a practice session
			activity(date(2026, 11, 2), "Linear Algebra - Practice Session", "15:00", "5161.0105"),
			activity(date(2026, 11, 7), "Thermal Physics Practice Session"),                       # more than two weeks
		)
		[slide] = provider.slides(NOW)
		sessions = slide.data["sessions"]
		self.assertEqual([(s["course"], s["day"], s["time"], s["room"], s["today"]) for s in sessions], [
			("Mechanics and Relativity", date(2026, 10, 23), "13:00", "Room TBA", True),
			("Calculus 1", date(2026, 10, 26), "11:00", "Room TBA", False),
			("Linear Algebra", date(2026, 11, 2), "15:00", "5161.0105", False),
		])
		self.assertEqual(sessions[0]["size"], sessions[1]["size"])   # both fit at the full size

	def test_a_long_course_name_gets_smaller(self):
		provider = self.provider(activity(date(2026, 10, 26), "Calculus 1 practice session"),
			activity(date(2026, 10, 27), "Introduction to Electrodynamics and Special Relativity practice session"))
		short, long = provider.slides(NOW)[0].data["sessions"]
		self.assertLess(long["size"], short["size"])

	def test_no_sessions_no_slide(self):
		self.assertEqual(self.provider(activity(date(2026, 10, 24), "Borrel")).slides(NOW), [])

	def test_many_sessions_move_closer_together(self):
		provider = self.provider(*[activity(date(2026, 10, 24) + timedelta(days=i), f"Course {i} practice session") for i in range(9)])
		data = provider.slides(NOW)[0].data
		self.assertEqual(len(data["sessions"]), 8)   # at most 8
		self.assertLessEqual(8 * data["ticket_height"] + 7 * data["gap"], TICKETS_HEIGHT)   # all on the screen


if __name__ == "__main__":
	unittest.main()
