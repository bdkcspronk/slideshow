import json
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.activity_chart import chart_view, merge_into_blocks, parse_style, prepare, time_in_room
from francken_tv.devices import DeviceList
from francken_tv.presence_store import PresenceStore, Sighting
from francken_tv.providers.presence import Greeter, PresenceChartProvider, greeting_day
from francken_tv.sniffer import parse_line

DAY = datetime(2026, 10, 14)
ALICE = "AA:AA:AA:AA:AA:01"
BOB = "BB:BB:BB:BB:BB:02"
DEVICES = [
	{"ssid": "Alice", "mac": ALICE, "style": "striped", "color": [["#36e0c1", "#18f566"], ["#1c03fc", "#e036b9"]]},
	{"ssid": "Bob", "mac": BOB.lower(), "phonetic": "Bobby", "custom_greeting": "Ahoy", "style": ["beer", "glow"]},
]


def at(hhmm: str) -> datetime:
	return datetime.combine(DAY.date(), time.fromisoformat(hhmm))


class FakeAnnouncer:
	def __init__(self):
		self.said = []

	def greet(self, text):
		self.said.append(text)


class PresenceTestCase(unittest.TestCase):
	def setUp(self):
		self.folder = TemporaryDirectory()
		self.dir = Path(self.folder.name)
		self.store = PresenceStore(self.dir / "presence.sqlite3")
		(self.dir / "devices.json").write_text(json.dumps(DEVICES))
		self.devices = DeviceList(self.dir / "devices.json")

	def tearDown(self):
		self.folder.cleanup()


class StoreTest(PresenceTestCase):
	def test_only_known_devices_in_time_range(self):
		self.store.add_sighting(at("09:00"), ALICE, "Alice", -40, 1)
		self.store.add_sighting(at("09:01"), "CC:CC:CC:CC:CC:03", None, -70, 6)
		self.store.add_sighting(at("11:00"), BOB, "Bob", -50, 1)
		names = [s.name for s in self.store.known_sightings(at("08:00"), at("10:00"))]
		self.assertEqual(names, ["Alice"])

	def test_import_old_jsonl(self):
		old = self.dir / "filtered_output.jsonl"
		old.write_text(
			json.dumps({"timestamp": "2026-10-14 09:00:00", "name": "Alice", "mac": ALICE.lower(), "rssi": -40, "channel": 1}) + "\n"
			+ json.dumps({"timestamp": "2026-10-14 09:00:05", "name": "Unknown Device", "mac": BOB, "rssi": -80, "channel": 1}) + "\n"
		)
		self.assertEqual(self.store.import_jsonl(old), 2)
		self.assertEqual([(s.name, s.mac) for s in self.store.known_sightings(at("00:00"), at("23:59"))], [("Alice", ALICE)])

	def test_delete_old_sightings(self):
		self.store.add_sighting(at("09:00") - timedelta(days=8), ALICE, "Alice", -40, 1)
		self.store.add_sighting(at("09:00"), ALICE, "Alice", -40, 1)
		self.store.delete_before(at("09:00") - timedelta(days=7))
		self.assertEqual(len(self.store.known_sightings(at("00:00") - timedelta(days=30), at("23:59"))), 1)


class DeviceListTest(PresenceTestCase):
	def test_reload_picks_up_changes(self):
		self.assertEqual(self.devices.get(ALICE).name, "Alice")
		(self.dir / "devices.json").write_text(json.dumps([{"ssid": "Alicia", "mac": ALICE}]))
		self.assertEqual(self.devices.reload()[ALICE].name, "Alicia")


class GreeterTest(PresenceTestCase):
	def test_greets_each_person_once_per_day_with_custom_greeting(self):
		announcer = FakeAnnouncer()
		greeter = Greeter({}, self.store, self.devices, announcer)
		self.store.add_sighting(at("09:00"), ALICE, "Alice", -40, 1)
		self.store.add_sighting(at("09:00"), BOB, "Bob", -40, 1)
		greeter.tick(at("09:00") + timedelta(seconds=1))
		self.store.add_sighting(at("09:30"), ALICE, "Alice", -40, 1)
		greeter.tick(at("09:30") + timedelta(seconds=1))
		self.assertEqual(announcer.said, ["Welcome Alice!", "Ahoy Bobby!"])

	def test_does_not_greet_people_seen_long_ago(self):
		announcer = FakeAnnouncer()
		self.store.add_sighting(at("09:00"), ALICE, "Alice", -40, 1)
		Greeter({}, self.store, self.devices, announcer).tick(at("12:00"))
		self.assertEqual(announcer.said, [])

	def test_day_starts_at_four(self):
		self.assertEqual(greeting_day(datetime(2026, 10, 15, 2, 0), time(4, 0)), date(2026, 10, 14))
		self.assertEqual(greeting_day(datetime(2026, 10, 15, 5, 0), time(4, 0)), date(2026, 10, 15))


class ChartTest(PresenceTestCase):
	def test_blocks_bridge_gaps_up_to_ten_minutes(self):
		buckets = [at("09:00"), at("09:05"), at("09:15"), at("09:40")]
		self.assertEqual(merge_into_blocks(buckets), [(at("09:00"), at("09:20")), (at("09:40"), at("09:45"))])

	def test_style_parsing(self):
		alice = parse_style(DEVICES[0])
		self.assertEqual((alice.shape, alice.color, alice.stripe_color), ("striped", ["#36e0c1", "#18f566"], ["#1c03fc", "#e036b9"]))
		bob = parse_style(DEVICES[1])
		self.assertEqual((bob.shape, bob.glow), ("beer", True))
		rider = parse_style({"style": ["motorcycle", "striped"]})
		self.assertEqual((rider.shape, rider.motorcycle, alice.motorcycle), ("striped", True, False))
		self.assertEqual(parse_style({"style": "portugal"}).shape, "portugal")

	def test_rows_ordered_by_arrival(self):
		sightings = [Sighting(at("10:00"), BOB, "Bob"), Sighting(at("09:00"), ALICE, "Alice")]
		self.assertEqual(prepare(sightings, self.devices.by_mac()).names, ["Alice", "Bob"])

	def test_chart_view_positions_and_styles(self):
		sightings = [Sighting(at(t), mac, name) for t, mac, name in [
			("09:00", ALICE, "Alice"), ("09:05", ALICE, "Alice"), ("10:00", BOB, "Bob"), ("10:30", "DD:00:00:00:00:04", "Dave"),
		]]
		view = chart_view(sightings, self.devices.by_mac(), at("11:00"))
		self.assertEqual(view["names"], ["Alice", "Bob", "Dave"])
		alice, bob, dave = view["bars"]
		self.assertEqual(alice["left"], 28.571)                     # 09:00 on a 08:00-11:30 axis: 60 of 210 minutes
		self.assertEqual((alice["shape"], bob["shape"]), ("striped", "beer"))
		self.assertTrue(alice["stripes"].startswith("linear-gradient"))
		self.assertEqual(alice["paint"], "#18f566")                # a motorcycle takes the middle of a gradient
		self.assertTrue(bob["glow"] and bob["bubbles"])
		self.assertTrue(dave["background"].startswith("#"))        # no device entry: a generated colour
		self.assertLess(alice["delay"], bob["delay"])                 # earlier bars start growing first
		self.assertEqual([tick["label"] for tick in view["ticks"]], ["08:00", "09:00", "10:00", "11:00"])   # first arrival 09:00

	def test_one_portuguese_flag_across_a_persons_bars(self):
		(self.dir / "devices.json").write_text(json.dumps(DEVICES + [{"ssid": "Rui", "mac": "CC:00:00:00:00:03", "style": "portugal"}]))
		devices = DeviceList(self.dir / "devices.json")
		sightings = [Sighting(at(t), "CC:00:00:00:00:03", "Rui") for t in ("09:00", "09:05", "10:00", "10:10", "10:20", "10:25")]
		first, last = chart_view(sightings, devices.by_mac(), at("11:00"))["bars"]
		self.assertEqual((first["shape"], first["gradient_position"], last["gradient_position"]), ("portugal", 0, 100))
		self.assertEqual(first["gradient_size"], round(90 / 10 * 100, 2))   # the flag: 09:00-10:30, this bar 09:00-09:10
		self.assertEqual((first["flag_offset"], first["emblem_left"]), (0, None))
		back = first["flag_back"]   # the whole flag behind the bars, for the gap
		self.assertEqual((back["left"], back["width"], back["gradient_size"]), (first["left"], round(last["left"] + last["width"] - first["left"], 3), 100))
		self.assertNotIn("flag_back", last)
		self.assertEqual(last["emblem_left"], round(first["left"] + 0.4 * (last["left"] + last["width"] - first["left"]), 3))

	def test_chart_starts_an_hour_before_the_first_arrival(self):
		sightings = [Sighting(at("12:40"), ALICE, "Alice"), Sighting(at("13:10"), BOB, "Bob")]
		view = chart_view(sightings, self.devices.by_mac(), at("14:00"))
		self.assertEqual([tick["label"] for tick in view["ticks"]], ["12:00", "13:00", "14:00"])
		self.assertEqual(view["grid"][0]["left"], 0)        # the chart starts at 11:30 (12:40 minus an hour, on a quarter)
		self.assertEqual(view["bars"][0]["left"], 38.889)   # 12:40 is 70 of 180 minutes into 11:30-14:30
		self.assertIsNone(chart_view([], {}, at("11:00")))

	def test_chart_keeps_the_day_after_midnight(self):
		for sighting in (at("20:00"), at("23:50"), at("23:55") + timedelta(minutes=10)):   # the last one at 00:05
			self.store.add_sighting(sighting, ALICE, "Alice", -50, 1)
		self.store.add_sighting(at("03:00"), BOB, "Bob", -50, 1)   # last night: not part of today
		provider = PresenceChartProvider({}, self.store, self.devices, self.dir / "no-cat.png", 8)
		[slide] = provider.slides(at("00:30") + timedelta(days=1))
		self.assertEqual(slide.data["names"], ["Alice"])
		self.assertEqual(slide.data["ticks"][0]["label"], "19:00")   # an hour before the first arrival at 20:00
		self.assertEqual(provider.slides(at("04:30") + timedelta(days=1)), [])   # a new day: nobody yet

	def test_time_in_room(self):
		sightings = [Sighting(at(t), ALICE, "Alice") for t in ("09:00", "09:05", "09:10", "13:00")]
		total, days = time_in_room(sightings)["Alice"]
		self.assertEqual((total, len(days)), (timedelta(minutes=20), 1))   # 09:00-09:15 and 13:00-13:05


class LeaderboardTest(PresenceTestCase):
	def test_ranking_this_week(self):
		from francken_tv.providers.presence import LeaderboardProvider
		for minute in range(0, 60, 5):
			self.store.add_sighting(at("09:00") + timedelta(minutes=minute), BOB, "Bob", -50, 1)
		self.store.add_sighting(at("10:00"), ALICE, "Alice", -50, 1)
		self.store.add_sighting(at("10:00") - timedelta(days=7), ALICE, "Alice", -50, 1)   # last week: not counted
		[slide] = LeaderboardProvider({}, self.store, self.devices, 8).slides(at("12:00"))
		rows = slide.data["rows"]
		self.assertEqual([(r["place"], r["name"], r["time"], r["days"]) for r in rows], [(1, "Bob", "1 h 00 min", 1), (2, "Alice", "5 min", 1)])
		self.assertEqual(rows[0]["width"], 100.0)


class SnifferTest(unittest.TestCase):
	def test_parse_line(self):
		self.assertEqual(parse_line("aa:bb:cc:dd:ee:ff,-45,6"), ("AA:BB:CC:DD:EE:FF", -45, 6))
		self.assertIsNone(parse_line("Booting ESP32..."))
		self.assertIsNone(parse_line("aa:bb,-4x,6"))


if __name__ == "__main__":
	unittest.main()
