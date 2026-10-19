import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from unittest import mock

import requests

from francken_tv.providers.info import (Departure, Headline, InfoProvider, Lecture, Weather, academic_year, ago,
	article_paragraphs, html_paragraphs, larger_image, parse_departures, parse_feed, parse_rain, parse_timetable, parse_weather,
	rain_summary, room_label)

FIXTURES = Path(__file__).parent / "fixtures"
SUNDAY_EVENING = datetime(2026, 10, 18, 19, 30)

RSS = """<?xml version="1.0"?><rss><channel>
<item><title><![CDATA[Older news]]></title><pubDate>Sun, 18 Oct 2026 12:07:31 GMT</pubDate></item>
<item><title>Newest news</title><link>https://example.org/new</link><pubDate>Sun, 18 Oct 2026 19:15:00 +0200</pubDate>
<description><![CDATA[<p>First.</p><h2>A heading</h2><p>Second.</p>]]></description>
<enclosure type="image/webp" url="https://images.cdn.nos.nl/a-1024x576.webp"/></item>
<item><title>BBC style</title><pubDate>Sun, 18 Oct 2026 10:00:00 GMT</pubDate>
<media:thumbnail xmlns:media="http://search.yahoo.com/mrss/" width="240" url="https://ichef.bbci.co.uk/ace/standard/240/x.jpg"/></item>
<item><title></title></item>
<item><title>An ad</title><category><![CDATA[Commerciële content]]></category><pubDate>Sun, 18 Oct 2026 19:20:00 +0200</pubDate></item>
<item><title>Another ad</title><link>https://www.dvhn.nl/commerciele-content/x/1.html</link></item>
</channel></rss>"""


class NewsTest(unittest.TestCase):
	def test_newest_first(self):
		headlines = parse_feed(RSS)
		self.assertEqual([headline.title for headline in headlines], ["Newest news", "Older news", "BBC style"])
		self.assertEqual(ago(headlines[0].time, SUNDAY_EVENING), "15 min ago")

	def test_link_and_text_from_the_feed(self):
		newest = parse_feed(RSS)[0]
		self.assertEqual((newest.link, newest.paragraphs), ("https://example.org/new", ["First.", "A heading", "Second."]))
		self.assertEqual(html_paragraphs("Only a summary, no tags."), ["Only a summary, no tags."])

	def test_pictures(self):
		headlines = {headline.title: headline for headline in parse_feed(RSS)}
		self.assertEqual(headlines["Newest news"].image_url, "https://images.cdn.nos.nl/a-1024x576.webp")
		self.assertEqual(headlines["BBC style"].image_url, "https://ichef.bbci.co.uk/ace/standard/976/x.jpg")   # larger than the feed's
		self.assertEqual(headlines["Older news"].image_url, "")
		self.assertEqual(larger_image("https://images.nu.nl/m/abc_sqr256/444/0/1/1/x.jpg"), "https://images.nu.nl/m/abc_wd1280/444/0/1/1/x.jpg")

	def test_article_page(self):
		long = "A sentence that is long enough to count as article text, not a menu item."
		page = f"<html><nav><p>{long} (menu)</p></nav><article><p>{long}</p><figure><p>{long} (caption)</p></figure>" \
			f"<p>Short.</p><p>{long} Two.</p></article></html>"
		self.assertEqual(article_paragraphs(page), [long, long + " Two."])
		self.assertEqual(article_paragraphs("<html><div class='consent'><p>Accept cookies</p></div></html>"), [])

	def test_ago(self):
		self.assertEqual(ago(datetime(2026, 10, 18, 19, 29), SUNDAY_EVENING), "just now")
		self.assertEqual(ago(datetime(2026, 10, 18, 16, 0), SUNDAY_EVENING), "3 hours ago")
		self.assertEqual(ago(datetime(2026, 10, 17, 12, 0), SUNDAY_EVENING), "yesterday")


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

	def test_rain(self):
		rain = parse_rain("000|19:10\n077|19:15\n109|19:20\n\n")
		self.assertEqual(rain, [("19:10", 0.0), ("19:15", 0.1), ("19:20", 1.0)])

	def test_rain_summary(self):
		dry, wet = 0.0, 1.5
		self.assertEqual(rain_summary([("14:00", dry), ("14:05", dry)]), "Dry for the next 2 hours")
		self.assertEqual(rain_summary([("14:00", dry), ("14:05", wet), ("14:10", 0.5)]), "Rain from 14:05")
		self.assertEqual(rain_summary([("14:00", 0.3), ("14:05", dry)]), "Light rain now, dry from 14:05")
		self.assertEqual(rain_summary([("14:00", 5.0), ("14:05", wet)]), "Heavy rain for the next 2 hours")
		self.assertEqual(rain_summary([]), "Dry for the next 2 hours")


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


class InfoProviderTest(unittest.TestCase):
	def setUp(self):
		self.provider = InfoProvider({}, 15)
		self.provider.news = {"NOS": [Headline("Nieuws", datetime(2026, 10, 18, 19, 0))]}
		self.provider.weather = Weather(11.5, 9.2, "Overcast", "☁️", 16.6, "E")
		self.provider.departures = [Departure("1", "Hoofdstation", datetime(2026, 10, 18, 19, 38), datetime(2026, 10, 18, 19, 39))]
		self.provider.timetable = {"BSc 1": [Lecture(datetime(2026, 10, 19, 9, 0), datetime(2026, 10, 19, 11, 0), "Mechanics", "Lecture", [])]}

	def test_parts_take_turns(self):
		templates = [self.provider.slides(SUNDAY_EVENING)[0].template for _ in range(5)]
		self.assertEqual(templates, ["info_news.html", "info_weather.html", "info_buses.html", "info_timetable.html", "info_news.html"])

	def test_the_timetable_stays_longer(self):
		self.provider.turn = 3
		self.assertEqual(self.provider.slides(SUNDAY_EVENING)[0].seconds, 25)
		self.assertEqual(self.provider.slides(SUNDAY_EVENING)[0].seconds, 15)   # news

	def test_empty_parts_are_skipped(self):
		self.provider.departures = []
		templates = [self.provider.slides(SUNDAY_EVENING)[0].template for _ in range(3)]
		self.assertEqual(templates, ["info_news.html", "info_weather.html", "info_timetable.html"])

	def test_bus_minutes_are_worked_out_when_shown(self):
		self.provider.turn = 2
		[slide] = self.provider.slides(SUNDAY_EVENING)
		self.assertEqual(slide.data["departures"][0]["minutes"], 9)
		self.assertEqual(slide.update(datetime(2026, 10, 18, 19, 35))["departures"][0]["minutes"], 4)

	def test_timetable_shows_the_next_day_in_the_evening(self):
		self.assertEqual(self.provider.timetable_data(SUNDAY_EVENING)["day"], "tomorrow")
		self.assertEqual(self.provider.timetable_data(datetime(2026, 10, 19, 10, 0))["day"], "today")
		self.assertIsNone(self.provider.timetable_data(datetime(2026, 10, 19, 19, 0)))   # nothing in the week after

	def test_open_an_article_and_go_back(self):
		long = "A sentence that is long enough to count as article text, not a menu item."
		self.provider.news = {
			"NOS": [Headline("Whole", None, "https://nos.example/1", ["One.", "Two.", "Three."])],
			"BBC": [Headline("Page", None, "https://bbc.example/2", ["Summary."])],
			"NU.nl": [Headline("Walled", None, "https://nu.example/3", ["Summary only."])],
		}
		with mock.patch("francken_tv.providers.info.requests.get") as get:
			slide, _ = self.provider.action("article", ["https://nos.example/1"], SUNDAY_EVENING)
			get.assert_not_called()   # the feed has the whole article
		self.assertEqual((slide.template, slide.data["paragraphs"], slide.data["whole"]), ("info_article.html", ["One.", "Two.", "Three."], True))
		page = mock.Mock(status_code=200, text=f"<article><p>{long}</p><p>{long}</p></article>")
		with mock.patch("francken_tv.providers.info.requests.get", return_value=page):
			slide, _ = self.provider.action("article", ["https://bbc.example/2"], SUNDAY_EVENING)
		self.assertEqual((len(slide.data["paragraphs"]), slide.data["whole"]), (2, True))
		wall = mock.Mock(status_code=200, text="<div>Accept our cookies</div>")
		with mock.patch("francken_tv.providers.info.requests.get", return_value=wall):
			slide, _ = self.provider.action("article", ["https://nu.example/3"], SUNDAY_EVENING)
		self.assertEqual((slide.data["paragraphs"], slide.data["whole"]), (["Summary only."], False))
		slide, _ = self.provider.action("news", [], SUNDAY_EVENING)
		self.assertEqual(slide.template, "info_news.html")
		self.assertIn("no longer", self.provider.action("article", ["https://gone.example"], SUNDAY_EVENING)[1])

	def test_pictures_are_downloaded_and_old_ones_removed(self):
		folder = Path(tempfile.mkdtemp())
		self.addCleanup(lambda: [path.unlink() for path in folder.iterdir()] and None)
		(folder / "old.jpg").write_bytes(b"gone")
		provider = InfoProvider({}, 15, folder)
		good, broken = Headline("A", None, image_url="https://img.example/a.jpg"), Headline("B", None, image_url="https://img.example/b.jpg")
		def get(url, **kwargs):
			if "b.jpg" in url:
				raise requests.ConnectionError("down")
			return mock.Mock(status_code=200, content=b"jpeg", headers={"Content-Type": "image/jpeg"}, raise_for_status=lambda: None)
		with mock.patch("francken_tv.providers.info.requests.get", side_effect=get), \
				mock.patch("francken_tv.providers.info.media_url", side_effect=lambda path: f"/files/{path.name}"):
			provider.download_images([good, broken])
		self.assertTrue(good.image.startswith("/files/") and good.image.endswith(".jpg"))
		self.assertEqual(broken.image, "")   # no picture rather than a broken one
		self.assertEqual([path.name for path in folder.iterdir()], [good.image.removeprefix("/files/")])

	def test_nothing_fetched_yet(self):
		self.assertEqual(InfoProvider({}, 15).slides(SUNDAY_EVENING), [])


if __name__ == "__main__":
	unittest.main()
