"""config/devices.json: which phones belong to whom.

Same format as the old Sniffer/filter.json, a list of entries like
	{"ssid": "Bradley", "mac": "AA:BB:...", "phonetic": "Bradly", "custom_greeting": "Hey",
	 "style": "striped", "color": ["#36e0c1", "#18f566"]}
Only "ssid" (the name) and "mac" are required. The chart options are explained in activity_chart.py.
The file is re-read automatically when it changes.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)


@dataclass
class Device:
	mac: str
	name: str
	phonetic: str          # how the announcer should pronounce the name
	greeting: str | None   # replaces "Welcome"
	options: dict = field(default_factory=dict)   # the full entry, for chart styles


class DeviceList:
	def __init__(self, path: Path) -> None:
		self.path = path
		self.loaded_mtime: float | None = None
		self.devices: dict[str, Device] = {}

	def by_mac(self) -> dict[str, Device]:
		self.reload_if_changed()
		return self.devices

	def get(self, mac: str) -> Device | None:
		return self.by_mac().get(mac.upper())

	def reload(self) -> dict[str, Device]:
		"""Read the file again even if it looks unchanged."""
		self.loaded_mtime = None
		return self.by_mac()

	def reload_if_changed(self) -> None:
		try:
			mtime = self.path.stat().st_mtime
		except FileNotFoundError:
			if self.loaded_mtime != -1:
				log.warning("Device list %s not found", self.path)
			self.devices, self.loaded_mtime = {}, -1
			return
		if mtime == self.loaded_mtime:
			return
		try:
			entries = json.loads(self.path.read_text(encoding="utf-8"))
		except (OSError, json.JSONDecodeError) as error:
			log.error("Could not read %s, keeping the previous version: %s", self.path, error)
			return
		if isinstance(entries, dict):
			entries = [entries]
		self.devices = {
			entry["mac"].upper(): Device(
				mac=entry["mac"].upper(),
				name=entry["ssid"],
				phonetic=entry.get("phonetic") or entry["ssid"],
				greeting=entry.get("custom_greeting"),
				options=entry,
			)
			for entry in entries
			if "mac" in entry and "ssid" in entry
		}
		self.loaded_mtime = mtime
		log.info("Loaded %d devices from %s", len(self.devices), self.path)
