"""The presence database (SQLite): who was seen when, and who has been greeted today.

The sniffer writes to it; the slideshow reads from it. SQLite handles the two
processes using the same file at the same time.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sightings (
	time    TEXT NOT NULL,   -- "YYYY-MM-DD HH:MM:SS", local time
	mac     TEXT NOT NULL,
	name    TEXT,            -- NULL for unknown devices
	rssi    INTEGER,
	channel INTEGER
);
CREATE INDEX IF NOT EXISTS sightings_time ON sightings (time);
CREATE TABLE IF NOT EXISTS greeted (
	day  TEXT NOT NULL,
	name TEXT NOT NULL,
	PRIMARY KEY (day, name)
);
"""


@dataclass
class Sighting:
	time: datetime
	mac: str
	name: str


class PresenceStore:
	def __init__(self, path: Path) -> None:
		self.path = path
		path.parent.mkdir(parents=True, exist_ok=True)
		with closing(self.connect()) as connection, connection:
			connection.execute("PRAGMA journal_mode=WAL")
			connection.executescript(SCHEMA)

	def connect(self) -> sqlite3.Connection:
		return sqlite3.connect(self.path, timeout=10)

	def add_sighting(self, time: datetime, mac: str, name: str | None, rssi: int, channel: int) -> None:
		with closing(self.connect()) as connection, connection:
			connection.execute(
				"INSERT INTO sightings VALUES (?, ?, ?, ?, ?)",
				(time.strftime(TIMESTAMP_FORMAT), mac, name, rssi, channel),
			)

	def known_sightings(self, start: datetime, end: datetime) -> list[Sighting]:
		"""Sightings of known devices between start and end, oldest first."""
		with closing(self.connect()) as connection:
			rows = connection.execute(
				"SELECT time, mac, name FROM sightings WHERE time >= ? AND time < ? AND name IS NOT NULL ORDER BY time",
				(start.strftime(TIMESTAMP_FORMAT), end.strftime(TIMESTAMP_FORMAT)),
			).fetchall()
		return [Sighting(datetime.strptime(time, TIMESTAMP_FORMAT), mac, name) for time, mac, name in rows]

	def delete_before(self, time: datetime) -> None:
		with closing(self.connect()) as connection, connection:
			connection.execute("DELETE FROM sightings WHERE time < ?", (time.strftime(TIMESTAMP_FORMAT),))
			connection.execute("DELETE FROM greeted WHERE day < ?", (time.date().isoformat(),))

	def was_greeted(self, day: date, name: str) -> bool:
		with closing(self.connect()) as connection:
			row = connection.execute("SELECT 1 FROM greeted WHERE day = ? AND name = ?", (day.isoformat(), name)).fetchone()
		return row is not None

	def mark_greeted(self, day: date, name: str) -> None:
		with closing(self.connect()) as connection, connection:
			connection.execute("INSERT OR IGNORE INTO greeted VALUES (?, ?)", (day.isoformat(), name))

	def import_jsonl(self, path: Path) -> int:
		"""Import the old Sniffer/filtered_output.jsonl format. Returns the number of rows."""
		rows = []
		with open(path, encoding="utf-8") as file:
			for line in file:
				if not line.strip():
					continue
				entry = json.loads(line)
				name = entry.get("name")
				rows.append((
					entry["timestamp"], entry["mac"].upper(),
					None if name in (None, "Unknown Device") else name,
					entry.get("rssi"), entry.get("channel"),
				))
		with closing(self.connect()) as connection, connection:
			connection.executemany("INSERT INTO sightings VALUES (?, ?, ?, ?, ?)", rows)
		return len(rows)
