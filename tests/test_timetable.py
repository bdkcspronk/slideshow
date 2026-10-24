import unittest
from datetime import datetime

from francken_tv.providers.timetable import Lecture, TimetableProvider, academic_year, parse_timetable, room_label

SUNDAY_EVENING = datetime(2026, 10, 18, 19, 30)


def event(start, end, course, kind, programmes, rooms):
	return {"start": start, "end": end, "description": "hc1", "activityType": {"displayNameEn": kind},
		"courseOfferings": [{"displayNameEn": course}], "programmeOfferings": [{"id": p} for p in programmes],
		"rooms": [{"code": code, "displayNameEn": name} for code, name in rooms]}


class TimetableTest(unittest.TestCase):
	EVENTS = [
		event([2026, 10, 19, 11, 0], [2026, 10, 19, 13, 0], "Thermal Physics", "Tutorial", [2], [("5161.0289", "Collegezaal")]),
		event([2026, 10, 19, 11, 0], [2026, 10, 19, 13, 0], "Thermal Physics", "Tutorial", [2], [("5113.0202", "ALC")]),
		event([2026, 10, 19, 9, 0], [2026, 10, 19, 11, 0], "Mechanics and Relativity", "Lecture", [1, 99], [("5161.0289", "Collegezaal")]),
		event([2026, 10, 19, 13, 0], [2026, 10, 19, 15, 0], "Calculus 1", "Lecture", [1, 2], []),
	]

	def test_columns_and_merged_rooms(self):
		timetable = parse_timetable(self.EVENTS, {1: "BSc 1", 2: "BSc 2"})
		self.assertEqual([lecture.course for lecture in timetable["BSc 1"]], ["Mechanics and Relativity", "Calculus 1"])
		thermal = timetable["BSc 2"][0]
		self.assertEqual((thermal.kind, thermal.rooms), ("Tutorial", ["5161.0289", "5113.0202 ALC"]))   # two groups: one row
		self.assertEqual(timetable["BSc 2"][1].course, "Calculus 1")   # shared by both years

	def test_kinds_in_colour_groups(self):
		group = lambda kind: Lecture(None, None, "", kind, []).group
		self.assertEqual([group(kind) for kind in ["Lecture", "Tutorial", "Computer practical", "Resit digital", "Group meeting", "Something new"]],
			["lecture", "tutorial", "practical", "exam", "other", "other"])

	def test_room_label(self):
		self.assertEqual(room_label({"code": "5161.0289", "displayNameEn": "Collegezaal"}), "5161.0289")
		self.assertEqual(room_label({"code": "5115.0016", "displayNameEn": "Max Gruberzaal"}), "5115.0016 Max Gruberzaal")

	def test_academic_year(self):
		self.assertEqual(academic_year(datetime(2026, 10, 18).date()), "2026-2027")
		self.assertEqual(academic_year(datetime(2027, 3, 1).date()), "2026-2027")
		self.assertEqual(academic_year(datetime(2027, 9, 1).date()), "2027-2028")


class TimetableProviderTest(unittest.TestCase):
	def setUp(self):
		self.provider = TimetableProvider({})
		self.provider.timetable = {"BSc 1": [Lecture(datetime(2026, 10, 19, 9, 0), datetime(2026, 10, 19, 11, 0), "Mechanics", "Lecture", [])]}

	def test_the_timetable_stays_longer(self):
		[slide] = self.provider.slides(SUNDAY_EVENING)
		self.assertEqual((slide.template, slide.seconds), ("timetable.html", 25))

	def test_timetable_shows_the_next_day_in_the_evening(self):
		self.assertEqual(self.provider.timetable_data(SUNDAY_EVENING)["day"], "tomorrow")
		self.assertEqual(self.provider.timetable_data(datetime(2026, 10, 19, 10, 0))["day"], "today")
		self.assertIsNone(self.provider.timetable_data(datetime(2026, 10, 19, 19, 0)))   # nothing in the week after

	def test_lectures_that_are_over_are_left_out(self):
		self.provider.timetable["BSc 1"].append(Lecture(datetime(2026, 10, 19, 13, 0), datetime(2026, 10, 19, 15, 0), "Optics", "Lecture", []))
		courses = lambda now: [lecture.course for lecture in self.provider.timetable_data(now)["columns"]["BSc 1"]]
		self.assertEqual(courses(datetime(2026, 10, 19, 10, 59)), ["Mechanics", "Optics"])
		self.assertEqual(courses(datetime(2026, 10, 19, 11, 1)), ["Optics"])   # 9:00-11:00 is over


if __name__ == "__main__":
	unittest.main()
