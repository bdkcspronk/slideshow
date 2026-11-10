"""Copy catfishing.net games played in a browser into the TV's archive calendar.

	python3 tools/import_catfishing_browser.py              show what would be imported
	python3 tools/import_catfishing_browser.py --write      import it (keeps a .bak of the old history)
	python3 tools/import_catfishing_browser.py --from FILE  read the games from FILE instead (see below)

catfishing.net keeps every day played in the browser's localStorage ("game-<day number>": the answers,
or only the score for very old games). This reads that from every Firefox profile of this user
(normal, snap and flatpak installs, and the kiosk's profile) and adds it to data/puzzles/catfishing_history.json,
so the calendar shows those days as done (with the score) or started, and a started day can be finished on the TV.
Nothing is downloaded. A day the TV already got further with is left alone, and so is today
(today's game on the TV has its own save file).

The kiosk browser runs in a private window, which keeps nothing, so games played there can't be found.
Other browsers (Chrome, ...): open catfishing.net in it, press F12, and in the Console run
	copy(JSON.stringify(Object.fromEntries(Object.entries(localStorage).filter(([k]) => /^game-\\d+$|^state$/.test(k)))))
which copies the games; paste them in a file and use --from FILE.

Stop the slideshow first, or restart it afterwards (systemctl --user restart francken-tv): while it runs it
has the old history in memory and writes that back as soon as someone plays.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import sys
import tempfile
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from francken_tv.providers.catfishing import ARCHIVE_START, FIRST_DAY, POINTS   # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
HISTORY = ROOT / "data/puzzles/catfishing_history.json"
TOTAL = 10   # articles a day
# catfishing.net's answer codes -> the TV's. "Not shown" is an article the site leaves out (hidden).
RESULTS = {0: "incorrect", 1: "skipped", 2: "correct", 3: "close", 4: "skipped"}
PROFILE_FOLDERS = [".mozilla/firefox", "snap/firefox/common/.mozilla/firefox", ".var/app/org.mozilla.firefox/.mozilla/firefox"]


# -- reading Firefox's localStorage --

def snappy_decompress(data: bytes) -> bytes:
	"""Raw snappy, as Firefox compresses localStorage values with (no library needed)."""
	length, shift, i = 0, 0, 0
	while True:   # the uncompressed length, as a varint
		byte = data[i]
		i += 1
		length |= (byte & 0x7F) << shift
		shift += 7
		if byte < 0x80:
			break
	out = bytearray()
	while i < len(data):
		tag = data[i]
		i += 1
		kind = tag & 3
		if kind == 0:   # literal
			size = tag >> 2
			if size >= 60:
				extra = size - 59
				size = int.from_bytes(data[i:i + extra], "little")
				i += extra
			size += 1
			out += data[i:i + size]
			i += size
			continue
		if kind == 1:
			size, offset = ((tag >> 2) & 7) + 4, ((tag >> 5) << 8) | data[i]
			i += 1
		elif kind == 2:
			size, offset = (tag >> 2) + 1, int.from_bytes(data[i:i + 2], "little")
			i += 2
		else:
			size, offset = (tag >> 2) + 1, int.from_bytes(data[i:i + 4], "little")
			i += 4
		for _ in range(size):   # byte by byte: a copy may overlap what it is writing
			out.append(out[-offset])
	if len(out) != length:
		raise ValueError(f"snappy: expected {length} bytes, got {len(out)}")
	return bytes(out)


def decode_value(value: bytes | str, compressed: bool) -> str:
	if isinstance(value, str):
		return value
	if compressed:
		value = snappy_decompress(value)
	try:
		return value.decode("utf-8")
	except UnicodeDecodeError:
		return value.decode("utf-16-le")


def read_sqlite(path: Path, query: str) -> list[tuple]:
	"""Rows from a copy of the database, so a running Firefox (which locks it) is no problem."""
	with tempfile.TemporaryDirectory() as folder:
		copy = Path(folder) / path.name
		for suffix in ["", "-wal", "-shm"]:
			if Path(str(path) + suffix).exists():
				shutil.copy(str(path) + suffix, str(copy) + suffix)
		with closing(sqlite3.connect(copy)) as database:
			return database.execute(query).fetchall()


def firefox_storage(profile: Path) -> dict[str, str]:
	"""catfishing.net's localStorage in one Firefox profile."""
	items: dict[str, str] = {}
	old = profile / "webappsstore.sqlite"   # before Firefox 92 or so
	if old.exists():
		for key, value in read_sqlite(old, "SELECT key, value FROM webappsstore2 WHERE originKey LIKE 'ten.gnihsiftac.%'"):
			items[key] = value
	for database in profile.glob("storage/default/https+++*catfishing.net*/ls/data.sqlite"):
		for key, value, compression in read_sqlite(database, "SELECT key, value, compression_type FROM data"):
			items[key] = decode_value(value, compression == 1)
	return items


def firefox_profiles() -> list[Path]:
	profiles = [ROOT / "data/kiosk-firefox-profile"]
	for folder in PROFILE_FOLDERS:
		profiles += [p for p in (Path.home() / folder).glob("*") if (p / "prefs.js").exists()]
	return [p for p in profiles if p.is_dir()]


# -- catfishing.net's saved games -> the TV's history --

def answer(saved: dict | list) -> list[str]:
	if isinstance(saved, list):   # older format: [code, guess]
		saved = {"r": saved[0], "g": saved[1] if len(saved) > 1 else ""}
	return [RESULTS[saved["r"]], saved.get("g") or ""]


def convert(saved: dict) -> dict | None:
	"""One "game-<day>" value -> a history entry, as CatfishingProvider.record() writes it."""
	answers = [answer(a) for a in saved.get("a") or []]
	if saved.get("s") == 1 and not answers:   # finished long ago: only the score is known, not which ones
		corrects, closes = saved["c"]
		answers = [["correct", ""]] * corrects + [["close", ""]] * closes + [["incorrect", ""]] * (TOTAL - corrects - closes)
	if not answers or len(answers) > TOTAL:
		return None
	showing_answer = saved.get("s") == 0 and saved.get("u") == 1   # the last answer still on screen
	return {"answers": answers, "showing_answer": showing_answer, "total": TOTAL,
		"score": sum(POINTS[result] for result, _ in answers)}


def games(storage: dict[str, str]) -> dict[int, dict]:
	"""{day number: history entry} from catfishing.net's localStorage."""
	found: dict[int, dict] = {}
	if "state" in storage:   # the very first format: only scores
		for outcome in json.loads(storage["state"]).get("outcomes", []):
			found[outcome["day"]] = {"s": 1, "c": [outcome["corrects"], outcome.get("closes") or 0]}
	for key, value in storage.items():
		if key.startswith("game-") and key[5:].isdigit():
			found[int(key[5:])] = json.loads(value)
	converted = {}
	for number, saved in found.items():
		try:
			entry = convert(saved)
		except (KeyError, IndexError, TypeError, ValueError) as error:
			print(f"  skipped day {number}: can't read {saved!r} ({error!r})")
			continue
		if entry:
			converted[number] = entry
	return converted


def progress(entry: dict | None) -> tuple[int, int]:
	"""For comparing: finished days first, then the number of answers."""
	if not entry or not entry.get("answers"):
		return (0, 0)
	done = len(entry["answers"]) == entry.get("total", TOTAL) and not entry.get("showing_answer")
	return (int(done), len(entry["answers"]))


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	parser.add_argument("--write", action="store_true", help="import (without it: only show what would change)")
	parser.add_argument("--from", dest="source", type=Path, help="a JSON file with the localStorage, instead of Firefox")
	parser.add_argument("--history", type=Path, default=HISTORY, help=f"the TV's history (default {HISTORY})")
	args = parser.parse_args()

	found: dict[int, dict] = {}
	sources = [(args.source, json.loads(args.source.read_text(encoding="utf-8")))] if args.source else \
		[(profile, firefox_storage(profile)) for profile in firefox_profiles()]
	for source, storage in sources:
		days = games(storage)
		print(f"{source}: {len(days)} days")
		for number, entry in days.items():   # the same day in two browsers: the one that got furthest
			if progress(entry) > progress(found.get(number)):
				found[number] = entry
	if not args.source and not sources:
		print("No Firefox profiles found. Use --from FILE (see the top of this script).")

	history = json.loads(args.history.read_text(encoding="utf-8")) if args.history.exists() else {}
	today = date.today()
	added = []
	for number, entry in sorted(found.items()):
		day = FIRST_DAY + timedelta(days=number)
		if not ARCHIVE_START <= day < today:
			continue   # not in the TV's calendar, or today's game (which has its own save file)
		if progress(entry) > progress(history.get(day.isoformat())):
			history[day.isoformat()] = entry
			state = "done" if progress(entry)[0] else f"started, {len(entry['answers'])}/{TOTAL}"
			added.append(f"  {day:%a %-d %b %Y} (day {number}): {state}, {entry['score']} points")
	print(f"\n{len(added)} days to import:" if added else "\nNothing new to import.")
	print("\n".join(added))
	if not added:
		return
	if not args.write:
		print("\nNothing written yet: run again with --write to import these.")
		return
	args.history.parent.mkdir(parents=True, exist_ok=True)
	if args.history.exists():
		shutil.copy(args.history, args.history.with_suffix(".json.bak"))
	temporary = args.history.with_suffix(".tmp")
	temporary.write_text(json.dumps(history, indent=1, sort_keys=True), encoding="utf-8")
	temporary.replace(args.history)
	print(f"\nWritten to {args.history}. Restart the slideshow so it sees them: systemctl --user restart francken-tv")


if __name__ == "__main__":
	main()
