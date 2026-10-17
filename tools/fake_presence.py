"""Dummy people and sightings, to see the activity chart and leaderboard without a sniffer.

	python3 tools/fake_presence.py            add them: this week (since Monday) up to now
	python3 tools/fake_presence.py --remove   take them out again

The fake people get MAC addresses 02:00:00:00:00:xx, which no real phone sends, so real sightings and
real entries in config/devices.json are left alone. They're marked as greeted today, so the TV doesn't
greet them out loud. Run it again on another day for a fresh chart (it replaces the old fake sightings).
"""

from __future__ import annotations

import json
import random
import sys
from contextlib import closing
from datetime import datetime, time, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from francken_tv.presence_store import TIMESTAMP_FORMAT, PresenceStore   # noqa: E402
from francken_tv.providers.presence import greeting_day   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEVICES = ROOT / "config/devices.json"
DATABASE = ROOT / "data/presence.sqlite3"
FAKE_MAC = "02:00:00:00:00:"

# One of each chart style (see activity_chart.py).
PEOPLE = [
	{"ssid": "Alice", "color": ["#36e0c1", "#18f566"], "style": "striped"},
	{"ssid": "Bob", "color": "#fcd303", "style": "beer"},
	{"ssid": "Charlie", "style": "nyan cat"},
	{"ssid": "Dana", "color": "#ff5fa2", "style": ["round corners", "glow"]},
	{"ssid": "Eve", "style": "rainbow"},
	{"ssid": "Frank", "color": "#5fa8ff", "style": "board"},
	{"ssid": "Grace", "color": "#b388ff", "style": "square corners"},
]


def is_fake(entry: dict) -> bool:
	return entry.get("mac", "").upper().startswith(FAKE_MAC)


def real_devices() -> list[dict]:
	if not DEVICES.exists():
		return []
	entries = json.loads(DEVICES.read_text(encoding="utf-8"))
	return [entry for entry in ([entries] if isinstance(entries, dict) else entries) if not is_fake(entry)]


def write_devices(entries: list[dict]) -> None:
	DEVICES.write_text(json.dumps(entries, indent="\t") + "\n", encoding="utf-8")


def visits(rng: random.Random, day_start: datetime) -> list[tuple[datetime, datetime]]:
	"""1-3 stretches in the room between 09:00 and 19:00."""
	result, at = [], day_start.replace(hour=9) + timedelta(minutes=rng.randrange(0, 180))
	for _ in range(rng.randint(1, 3)):
		end = at + timedelta(minutes=rng.randrange(20, 180))
		if end > day_start.replace(hour=19):
			break
		result.append((at, end))
		at = end + timedelta(minutes=rng.randrange(30, 120))
	return result


def add(now: datetime) -> None:
	people = [{**person, "mac": f"{FAKE_MAC}{index:02X}"} for index, person in enumerate(PEOPLE, start=1)]
	write_devices(real_devices() + people)
	store = PresenceStore(DATABASE)
	remove_sightings(store)
	today = greeting_day(now, time(4))
	rows = []
	for days_ago in range(today.weekday() + 1):   # Monday up to today
		day = today - timedelta(days=days_ago)
		day_start = datetime.combine(day, time(4))
		for person in people:
			rng = random.Random(f"{day}{person['ssid']}")
			if rng.random() < 0.25:
				continue   # not in today
			for start, end in visits(rng, day_start):
				end = min(end, now)
				minute = start
				while minute < end:
					rows.append((minute.strftime(TIMESTAMP_FORMAT), person["mac"], person["ssid"], -60, 6))
					minute += timedelta(minutes=1)
	# Someone is in the room right now (the chart shows that bar as the latest).
	for minute in range(45, -1, -1):
		rows.append(((now - timedelta(minutes=minute)).strftime(TIMESTAMP_FORMAT), people[0]["mac"], people[0]["ssid"], -60, 6))
	with closing(store.connect()) as connection, connection:
		connection.executemany("INSERT INTO sightings VALUES (?, ?, ?, ?, ?)", rows)
	for person in people:
		store.mark_greeted(today, person["ssid"])   # no spoken "Welcome Alice!"
	print(f"Added {len(people)} fake people to {DEVICES.relative_to(ROOT)} and {len(rows)} sightings since Monday.")


def remove_sightings(store: PresenceStore) -> int:
	with closing(store.connect()) as connection, connection:
		return connection.execute("DELETE FROM sightings WHERE mac LIKE ?", (FAKE_MAC + "%",)).rowcount


def remove() -> None:
	entries = real_devices()
	if entries:
		write_devices(entries)
	else:
		DEVICES.unlink(missing_ok=True)
	count = remove_sightings(PresenceStore(DATABASE))
	print(f"Removed the fake people and {count} fake sightings.")


if __name__ == "__main__":
	remove() if "--remove" in sys.argv[1:] else add(datetime.now().replace(microsecond=0))
