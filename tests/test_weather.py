import re
import unittest
from datetime import datetime

from francken_tv.providers.weather import Weather, WeatherProvider, parse_rain, parse_weather, rain_summary

SUNDAY_EVENING = datetime(2026, 10, 18, 19, 30)


class WeatherTest(unittest.TestCase):
	def test_parse(self):
		weather = parse_weather({
			"current": {"temperature_2m": 11.5, "apparent_temperature": 9.2, "weather_code": 0, "wind_speed_10m": 16.6,
				"wind_direction_10m": 85, "is_day": 0},
			"daily": {"time": ["2026-10-18", "2026-10-19"], "temperature_2m_max": [14.2, 12.0], "temperature_2m_min": [6.8, 5.1],
				"weather_code": [61, 0], "precipitation_probability_max": [40, None]},
		})
		self.assertEqual((weather.text, weather.icon, weather.wind_from), ("Clear sky", "🌙", "E"))   # clear at night: a moon
		today, tomorrow = weather.days
		self.assertEqual((today.icon, today.high, today.low, today.rain_chance), ("🌦️", 14.2, 6.8, 40))
		self.assertEqual((tomorrow.icon, tomorrow.rain_chance), ("☀️", 0))   # the days always get the daytime icon
		self.assertEqual((weather.scene, weather.is_day), ("clear", False))   # the sky behind the slide: clear, at night

	def test_scenes(self):
		scene = lambda code: Weather(10, 8, "", "", 5, "N", code=code).scene
		self.assertEqual([scene(code) for code in (1, 2, 3, 48, 55, 61, 82, 85, 96, 1234)],
			["clear", "partly", "cloudy", "fog", "drizzle", "rain", "heavy-rain", "snow", "storm", "cloudy"])

	def test_rain(self):
		rain = parse_rain("000|19:10\n077|19:15\n109|19:20\n\n")
		self.assertEqual(rain, [("19:10", 0.0), ("19:15", 0.1), ("19:20", 1.0)])

	def test_rain_summary(self):
		dry, wet = 0.0, 1.5
		self.assertEqual(rain_summary([("14:00", dry), ("14:05", dry)]), "Dry for the next 2 hours")
		self.assertEqual(rain_summary([("14:00", dry), ("14:05", wet), ("14:10", 0.5)]), "Rain from 14:05")
		self.assertEqual(rain_summary([("14:00", 0.3)] + [(f"14:{m:02d}", dry) for m in range(5, 40, 5)]), "Light rain now, dry from 14:05")
		# A dry ten minutes between two showers isn't "dry from": that's when it stays dry for half an hour.
		showers = [0.5, 0.5, dry, dry, 1.0, 1.0, dry, dry, dry, dry, dry, dry, dry]
		self.assertEqual(rain_summary([(f"14:{5 * i:02d}", mm) for i, mm in enumerate(showers)]), "Rain now, dry from 14:30")
		self.assertEqual(rain_summary([(f"14:{5 * i:02d}", mm) for i, mm in enumerate([0.5, dry, 0.5, dry])]), "Light rain for the next 2 hours")   # never dry for long
		self.assertEqual(rain_summary([("14:00", 5.0), ("14:05", wet)]), "Heavy rain for the next 2 hours")
		self.assertEqual(rain_summary([]), "Dry for the next 2 hours")


class WeatherProviderTest(unittest.TestCase):
	def setUp(self):
		self.provider = WeatherProvider({}, 15)
		self.provider.weather = Weather(11.5, 9.2, "Overcast", "☁️", 16.6, "E")

	def test_rain_bars_have_an_intensity(self):
		self.provider.weather.rain = [("19:30", 0.0), ("19:35", 0.4), ("19:40", 2.5), ("19:45", 6.0)]
		self.assertEqual([bar["level"] for bar in self.provider.weather_data(SUNDAY_EVENING)["rain"]], ["dry", "light", "medium", "heavy"])
		self.assertEqual([line["label"] for line in self.provider.weather_data(SUNDAY_EVENING)["rain_lines"]], ["Light", "Medium", "Heavy"])
		self.provider.weather.rain = [("19:30", 0.0), ("19:35", 0.4)]   # only light rain: no line for heavy above the chart
		self.assertEqual([line["label"] for line in self.provider.weather_data(SUNDAY_EVENING)["rain_lines"]], ["Light", "Medium"])
		self.provider.weather.rain = [("19:30", 0.0)]   # dry: no lines
		self.assertEqual(self.provider.weather_data(SUNDAY_EVENING)["rain_lines"], [])

	def test_the_rain_chart_is_a_filled_line(self):
		self.provider.weather.rain = [(f"19:{30 + 5 * i}", mm) for i, mm in enumerate([0.0, 0.5, 2.0, 6.0, 1.0, 0.0])]
		chart = self.provider.weather_data(SUNDAY_EVENING)["chart"]
		self.assertTrue(chart["line"].startswith("M0.00,100.00 C"))   # a smooth curve from the bottom left...
		self.assertTrue(chart["area"].endswith("L100,100 L0,100 Z"))   # ...and the shaded area under it
		numbers = [float(n) for n in re.findall(r"-?\d+\.\d+", chart["line"])]
		self.assertTrue(all(0 <= n <= 100 for n in numbers))   # never below the bottom or above the top
		self.assertEqual([t["time"] for t in chart["times"]], ["19:30"])   # every half hour

	def test_only_the_next_two_hours_from_now(self):
		self.provider.weather.rain = [(f"{19 + (i * 5 + 10) // 60}:{(i * 5 + 10) % 60:02d}", 0.0) for i in range(24)]   # 19:10 to 21:05
		times = [bar["time"] for bar in self.provider.weather_data(SUNDAY_EVENING)["rain"]]   # shown at 19:30
		self.assertEqual((times[0], times[-1]), ("19:30", "21:05"))   # fetched a while ago: what's past is left out
		self.provider.weather.rain = [("23:50", 0.0), ("23:55", 2.0), ("0:00", 2.0), ("0:05", 0.0)]   # across midnight
		late = datetime(2026, 10, 18, 23, 58)
		self.assertEqual([t for t, _ in self.provider.upcoming_rain(late)], ["23:55", "0:00", "0:05"])
		self.assertTrue(self.provider.rain_coming(late))
		self.assertFalse(self.provider.rain_coming(datetime(2026, 10, 19, 0, 7)))   # the rain is over

	def test_a_rain_warning_after_bieruur(self):
		self.provider.weather.rain = [("19:30", 0.0), ("19:35", 0.0)]   # dry
		self.assertEqual(self.provider.outside_daytime_slides(SUNDAY_EVENING), [])
		self.provider.weather.rain = [("19:30", 0.0), ("20:45", 1.2)]   # rain in an hour and a quarter
		[slide] = self.provider.outside_daytime_slides(SUNDAY_EVENING)
		self.assertEqual((slide.template, slide.data["summary"], slide.data["heaviest"]), ("rain.html", "Rain from 20:45", "rain"))
		self.assertEqual(slide.data["scene"], "rain")   # the sky behind it: as heavy as the rain that's coming
		self.provider.weather.rain = [("19:30", 0.0), ("20:45", 6.0)]
		self.assertEqual(self.provider.rain_data(SUNDAY_EVENING)["scene"], "heavy-rain")
		self.provider.weather.code = 95   # a thunderstorm now
		self.assertEqual(self.provider.rain_data(SUNDAY_EVENING)["scene"], "storm")
		self.assertEqual(self.provider.slides(SUNDAY_EVENING)[0].template, "weather.html")   # in the daytime: unchanged

	def test_nothing_fetched_yet(self):
		self.assertEqual(WeatherProvider({}, 15).slides(SUNDAY_EVENING), [])


if __name__ == "__main__":
	unittest.main()
