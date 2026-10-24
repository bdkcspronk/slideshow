import json
import re
import unittest
from datetime import datetime
from pathlib import Path

from francken_tv.providers.buses import BusesProvider, Departure, parse_departures

FIXTURES = Path(__file__).parent / "fixtures"
SUNDAY_EVENING = datetime(2026, 10, 18, 19, 30)


class BusesTest(unittest.TestCase):
	def test_departures_from_ovapi(self):
		departures = parse_departures(json.loads((FIXTURES / "ovapi_zernikeplein.json").read_text()))
		self.assertEqual(len(departures), 6)
		self.assertEqual(departures, sorted(departures, key=lambda departure: departure.expected))
		self.assertEqual({departure.destination for departure in departures}, {"Hoofdstation", "P+R Reitdiep"})
		self.assertEqual(departures[0].line, "1")

	def test_delay(self):
		late = Departure("1", "Hoofdstation", datetime(2026, 10, 19, 9, 0), datetime(2026, 10, 19, 9, 2, 40))
		early = Departure("1", "Hoofdstation", datetime(2026, 10, 19, 9, 0), datetime(2026, 10, 19, 8, 59))
		self.assertEqual((late.delay, early.delay), (3, 0))


class BusesProviderTest(unittest.TestCase):
	def setUp(self):
		self.provider = BusesProvider({}, 15)
		self.provider.departures = [Departure("1", "Hoofdstation", datetime(2026, 10, 18, 19, 38), datetime(2026, 10, 18, 19, 39))]

	def test_buses_in_their_line_colours(self):
		self.provider.departures.append(Departure("171", "Veendam", datetime(2026, 10, 18, 19, 40), datetime(2026, 10, 18, 19, 40)))
		rows = self.provider.buses_data(SUNDAY_EVENING)["departures"]
		self.assertEqual([row["colors"] for row in rows], [["#00be46", "#000000"], None])   # a regional line: the slide's blue

	def test_only_buses_that_can_still_be_caught_and_a_last_call(self):
		at = lambda minute, second=0: datetime(2026, 10, 18, 19, minute, second)
		self.provider.departures = [Departure("2", "Europapark", at(40), at(40)), Departure("15", "Hoofdstation", at(41), at(41)),
			Departure("1", "Hoofdstation", at(45), at(45))]
		rows = self.provider.buses_data(at(38, 30))["departures"]   # 1.5 minutes before the 2: too late (2 minutes' walk)
		self.assertEqual([(row["departure"].line, row["minutes"], row["last_call"]) for row in rows], [("15", 2, True), ("1", 6, False)])
		self.assertIsNone(self.provider.buses_data(at(43, 30)))   # none left that can be caught

	def test_the_bus_poster_shows_the_next_bus_that_is_not_cancelled(self):
		from jinja2 import Environment, FileSystemLoader, select_autoescape
		self.provider.departures.insert(0, Departure("15", "Hoofdstation", datetime(2026, 10, 18, 19, 35), datetime(2026, 10, 18, 19, 35), cancelled=True))
		data = self.provider.buses_data(SUNDAY_EVENING)
		html = Environment(loader=FileSystemLoader(Path(__file__).parent.parent / "francken_tv" / "templates"), autoescape=select_autoescape()).get_template(
			"slides/buses.html").render(**data)
		next_bus = re.search(r'class="bus-next">(.*?)</div>\s*</div>', html, re.S).group(1)
		self.assertIn(">1</span>", next_bus)   # not the cancelled 15
		self.assertIn("in 9 min", next_bus)
		self.assertIn("<em>Cancelled</em>", html)

	def test_bus_minutes_are_worked_out_when_shown(self):
		[slide] = self.provider.slides(SUNDAY_EVENING)
		self.assertEqual(slide.data["departures"][0]["minutes"], 9)
		self.assertEqual(slide.update(datetime(2026, 10, 18, 19, 35))["departures"][0]["minutes"], 4)

	def test_no_buses_to_catch(self):
		self.provider.departures = []
		self.assertEqual(self.provider.slides(SUNDAY_EVENING), [])


if __name__ == "__main__":
	unittest.main()
