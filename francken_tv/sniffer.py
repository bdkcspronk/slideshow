"""Reads the ESP32 sniffer on the serial port and stores sightings in the presence database.

Runs as its own process, next to the slideshow:
	python -m francken_tv.sniffer
	python -m francken_tv.sniffer --import Sniffer/filtered_output.jsonl   # import old logs

The firmware (firmware/src/main.cpp) prints one line per packet: MAC,RSSI,channel
The user running this needs access to the serial port: sudo usermod -aG dialout $USER
"""

from __future__ import annotations

import argparse
import logging
import time
from datetime import datetime, timedelta
from pathlib import Path

from .config import load_config, project_path
from .devices import DeviceList
from .presence_store import PresenceStore

log = logging.getLogger("francken_tv.sniffer")


def parse_line(line: str) -> tuple[str, int, int] | None:
	"""'aa:bb:cc:dd:ee:ff,-45,6' -> ('AA:BB:CC:DD:EE:FF', -45, 6); None for anything else."""
	fields = [field.strip() for field in line.split(",")]
	if len(fields) != 3:
		return None
	mac, rssi, channel = fields
	try:
		return mac.upper(), int(rssi), int(channel)
	except ValueError:
		return None


def run(settings: dict, store: PresenceStore, devices: DeviceList) -> None:
	import serial   # only needed here, so the rest of the project works without pyserial

	log_every = settings.get("log_every_seconds", 1)
	keep = timedelta(days=settings.get("keep_days", 7))
	log_unknown = settings.get("log_unknown_devices", False)
	last_logged: dict[str, float] = {}
	last_cleanup = 0.0

	with serial.Serial(settings.get("port", "/dev/ttyUSB0"), settings.get("baud", 115200), timeout=1) as port:
		# Reset the ESP32 so it starts capturing fresh (toggling DTR/RTS restarts the board).
		port.dtr = port.rts = False
		time.sleep(0.2)
		port.dtr = port.rts = True
		time.sleep(2)
		port.reset_input_buffer()
		log.info("Listening on %s", port.name)
		while True:
			if time.monotonic() - last_cleanup > 3600:
				store.delete_before(datetime.now() - keep)
				last_cleanup = time.monotonic()

			line = port.readline().decode("utf-8", errors="ignore").strip()   # waits up to 1 s
			parsed = parse_line(line)
			if parsed is None:
				continue
			mac, rssi, channel = parsed
			if time.monotonic() - last_logged.get(mac, -log_every) < log_every:
				continue
			device = devices.get(mac)
			if device is None and not log_unknown:
				continue
			last_logged[mac] = time.monotonic()
			store.add_sighting(datetime.now(), mac, device.name if device else None, rssi, channel)
			log.debug("Spotted %s (%s) RSSI %d", device.name if device else "unknown", mac, rssi)


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
	parser.add_argument("--config", type=Path, default=None)
	parser.add_argument("--import", dest="import_path", type=Path, help="import an old .jsonl log and exit")
	args = parser.parse_args()
	logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

	config = load_config(args.config) if args.config else load_config()
	store = PresenceStore(project_path(config["presence"]["database"]))
	if args.import_path:
		print(f"Imported {store.import_jsonl(args.import_path)} sightings")
		return
	devices = DeviceList(project_path(config["presence"]["devices"]))
	while True:
		try:
			run(config.get("sniffer", {}), store, devices)
		except KeyboardInterrupt:
			return
		except OSError as error:   # includes serial.SerialException: unplugged, no permission, ...
			log.warning("Serial port problem (%s); retrying in 10 seconds", error)
			time.sleep(10)
		except Exception:
			log.exception("Sniffer stopped; retrying in 10 seconds")
			time.sleep(10)


if __name__ == "__main__":
	main()
