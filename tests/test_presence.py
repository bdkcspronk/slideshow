import json
import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from francken_tv.activity_chart import merge_into_blocks, parse_style, prepare, render_chart
from francken_tv.devices import DeviceList
from francken_tv.presence_store import PresenceStore, Sighting
from francken_tv.providers.presence import Greeter, greeting_day
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

	def test_rows_ordered_by_arrival(self):
		sightings = [Sighting(at("10:00"), BOB, "Bob"), Sighting(at("09:00"), ALICE, "Alice")]
		self.assertEqual(prepare(sightings, self.devices.by_mac()).names, ["Alice", "Bob"])

	def test_renders_png(self):
		sightings = [Sighting(at(t), mac, name) for t, mac, name in [
			("09:00", ALICE, "Alice"), ("09:05", ALICE, "Alice"), ("10:00", BOB, "Bob"), ("10:30", "DD:00:00:00:00:04", "Dave"),
		]]
		output = self.dir / "chart.png"
		self.assertTrue(render_chart(sightings, self.devices.by_mac(), at("11:00"), output))
		self.assertGreater(output.stat().st_size, 10_000)
		self.assertFalse(render_chart([], {}, at("11:00"), self.dir / "empty.png"))


class SnifferTest(unittest.TestCase):
	def test_parse_line(self):
		self.assertEqual(parse_line("aa:bb:cc:dd:ee:ff,-45,6"), ("AA:BB:CC:DD:EE:FF", -45, 6))
		self.assertIsNone(parse_line("Booting ESP32..."))
		self.assertIsNone(parse_line("aa:bb,-4x,6"))


if __name__ == "__main__":
	unittest.main()
