"""Backs up what is not in git (the media, personal data, logins) to Nextcloud, encrypted; restores it.

	python -m francken_tv.backup setup      once: choose the passphrase that encrypts the backups
	python -m francken_tv.backup backup     what the weekly timer runs (deploy/francken-tv-backup.timer)
	python -m francken_tv.backup list       the backups on Nextcloud
	python -m francken_tv.backup restore    on a new TV PC: asks for the Nextcloud login and the passphrase

The files are in two parts, each its own archive (<part>-<date>.tar.gz.gpg, in [backup] folder):
"secrets" (small: logins, personal data, settings) and "media" (large: only uploaded again when
something in it changed; without media/voices/, the text-to-speech voice, which can be downloaded again). Archives are encrypted with gpg and a passphrase, so whoever can browse the
Nextcloud folder sees nothing. The passphrase is in ~/.config/slideshow/backup.passphrase on the TV
PC and, as the only other copy, with the board (docs/01-handover.md). Without it a backup is useless.

Restore never overwrites a file that exists, unless told to (--force).
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Callable

from .nextcloud import Nextcloud, load_credentials

log = logging.getLogger(__name__)

PROJECT_DIR = Path(__file__).resolve().parent.parent
HOME_CONFIG = Path("~/.config/slideshow").expanduser()
PASSPHRASE_FILE = HOME_CONFIG / "backup.passphrase"
STATE_FILE = PROJECT_DIR / "data" / "backup_state.json"
HOME_PREFIX = "home-config/"   # in the archive: the files of ~/.config/slideshow
PARTS = ["secrets", "media"]
STALE_AFTER = timedelta(days=10)   # a weekly backup that is this late counts as a problem

# Relative to the project folder. Files and folders; whatever doesn't exist is left out.
PROJECT_FILES = {
	"secrets": ["config/devices.json", "config/confidential.json", "config/extern.json", "data/poll.json",
		"data/settings.json", "data/puzzles/highscores.json", "data/spotifyd"],
	"media": ["media"],
}
# Not backed up: large and can be downloaded again (the text-to-speech voice, docs/06-tv-pc.md).
NOT_BACKED_UP = ["media/voices/"]


def part_files(part: str) -> list[tuple[Path, str]]:
	"""(file on disk, name in the archive) for every file of this part."""
	found = []
	for relative in PROJECT_FILES[part]:
		path = PROJECT_DIR / relative
		for file in ([path] if path.is_file() else sorted(path.rglob("*")) if path.is_dir() else []):
			if file.is_file() and not file.relative_to(PROJECT_DIR).as_posix().startswith(tuple(NOT_BACKED_UP)):
				found.append((file, file.relative_to(PROJECT_DIR).as_posix()))
	if part == "secrets" and HOME_CONFIG.is_dir():
		found += [(file, HOME_PREFIX + file.name) for file in sorted(HOME_CONFIG.glob("*.json"))]   # not backup.passphrase
	return found


def fingerprint(files: list[tuple[Path, str]]) -> str:
	"""Changes when a file is added, removed or changed (cheap: names, sizes and times, not contents)."""
	digest = hashlib.sha256()
	for file, name in files:
		stat = file.stat()
		digest.update(f"{name}|{stat.st_size}|{stat.st_mtime_ns}\n".encode())
	return digest.hexdigest()


class Gpg:
	"""Symmetric encryption with a passphrase, using gpg (installed on Ubuntu)."""

	def encrypt(self, source: Path, destination: Path, passphrase: str) -> None:
		self.run(["--symmetric", "--cipher-algo", "AES256", "-o", str(destination), str(source)], passphrase)

	def decrypt(self, source: Path, destination: Path, passphrase: str) -> None:
		self.run(["--decrypt", "-o", str(destination), str(source)], passphrase)

	@staticmethod
	def run(arguments: list[str], passphrase: str) -> None:
		command = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback", "--passphrase-fd", "0", *arguments]
		result = subprocess.run(command, input=passphrase.encode(), capture_output=True)
		if result.returncode != 0:
			raise RuntimeError(f"gpg failed (a wrong passphrase?): {result.stderr.decode(errors='replace').strip()[-300:]}")


def archive_name(part: str, now: datetime) -> str:
	return f"{part}-{now:%Y-%m-%d}.tar.gz.gpg"


def backups_of(nextcloud: Nextcloud, folder: str, part: str) -> list[str]:
	"""The names of this part's backups on Nextcloud, oldest first."""
	names = [entry.name for entry in nextcloud.list_folder(folder) if not entry.is_folder]
	return sorted(name for name in names if re.fullmatch(rf"{part}-\d{{4}}-\d\d-\d\d\.tar\.gz\.gpg", name))


def read_state(path: Path = STATE_FILE) -> dict:
	try:
		return json.loads(path.read_text(encoding="utf-8"))
	except (OSError, ValueError):
		return {}


def write_state(state: dict, path: Path = STATE_FILE) -> None:
	path.parent.mkdir(parents=True, exist_ok=True)
	temporary = path.with_suffix(".tmp")
	temporary.write_text(json.dumps(state, indent=1), encoding="utf-8")
	temporary.replace(path)


def run_backup(nextcloud: Nextcloud, folder: str, keep: int, passphrase: str, now: datetime,
		state_path: Path = STATE_FILE, crypto=None, files_of: Callable = part_files) -> list[str]:
	"""Uploads each part that changed since its last backup, and removes backups beyond the newest `keep`."""
	crypto = crypto or Gpg()
	state = read_state(state_path)
	messages = []
	nextcloud.make_folder(folder)
	for part in PARTS:
		files = files_of(part)
		if not files:
			messages.append(f"{part}: nothing to back up")
			continue
		current = fingerprint(files)
		if state.get(part, {}).get("fingerprint") == current:
			messages.append(f"{part}: unchanged since {state[part]['at'][:10]}")
			continue
		with tempfile.TemporaryDirectory() as work:
			plain, encrypted = Path(work) / "archive.tar.gz", Path(work) / "archive.gpg"
			with tarfile.open(plain, "w:gz") as archive:
				for file, name in files:
					archive.add(file, arcname=name, recursive=False)
			crypto.encrypt(plain, encrypted, passphrase)
			name = archive_name(part, now)
			nextcloud.upload(f"{folder}/{name}", encrypted)
			size = encrypted.stat().st_size
		state[part] = {"fingerprint": current, "at": now.isoformat(timespec="seconds")}
		write_state(state, state_path)
		for old in backups_of(nextcloud, folder, part)[:-max(keep, 1)]:
			nextcloud.delete(f"{folder}/{old}")
		messages.append(f"{part}: uploaded {name} ({len(files)} files, {size / 1e6:.1f} MB)")
	state["last_success"] = now.isoformat(timespec="seconds")   # also when nothing had changed
	write_state(state, state_path)
	return messages


def destination_of(name: str) -> Path | None:
	"""Where a file of the archive goes on this PC; None if the name is not allowed."""
	if name.startswith(HOME_PREFIX):
		relative, base = name[len(HOME_PREFIX):], HOME_CONFIG
	else:
		relative, base = name, PROJECT_DIR
	if not relative or relative.startswith("/") or ".." in Path(relative).parts or ":" in relative:
		return None
	return base / relative


def extract(archive_path: Path, force: bool) -> tuple[list[Path], list[Path]]:
	"""Puts the archive's files in place. Returns (written, skipped because they exist already)."""
	written, skipped = [], []
	with tarfile.open(archive_path, "r:gz") as archive:
		for member in archive:
			if not member.isfile():
				continue
			target = destination_of(member.name)
			if target is None:
				raise RuntimeError(f"the backup contains a file with an unsafe name: {member.name!r}")
			if target.exists() and not force:
				skipped.append(target)
				continue
			target.parent.mkdir(parents=True, exist_ok=True)
			target.write_bytes(archive.extractfile(member).read())
			if member.name.startswith(HOME_PREFIX):
				os.chmod(target, 0o600)   # logins: only this user
			written.append(target)
	return written, skipped


def run_restore(nextcloud: Nextcloud, folder: str, passphrase: str, force: bool = False, crypto=None) -> list[str]:
	"""Downloads the newest backup of each part, decrypts it and puts the files back."""
	crypto = crypto or Gpg()
	messages = []
	for part in PARTS:
		names = backups_of(nextcloud, folder, part)
		if not names:
			messages.append(f"{part}: no backup on Nextcloud in {folder}")
			continue
		with tempfile.TemporaryDirectory() as work:
			encrypted, plain = Path(work) / "archive.gpg", Path(work) / "archive.tar.gz"
			nextcloud.download(f"{folder}/{names[-1]}", encrypted)
			crypto.decrypt(encrypted, plain, passphrase)
			written, skipped = extract(plain, force)
		messages.append(f"{part}: restored {len(written)} files from {names[-1]}")
		if skipped:
			messages.append(f"{part}: left {len(skipped)} existing files alone (--force replaces them), e.g. {skipped[0]}")
	return messages


def warnings(now: datetime, state_path: Path = STATE_FILE, passphrase_file: Path = PASSPHRASE_FILE) -> list[str]:
	"""For /status and /health: backups that aren't set up or have stopped."""
	if not passphrase_file.exists():
		return ["no backup is set up on this PC: `python -m francken_tv.backup setup` (docs/01-handover.md)"]
	last = read_state(state_path).get("last_success")
	if not last:
		return ["no backup has run yet: `python -m francken_tv.backup backup` (docs/03-when-something-breaks.md)"]
	late = now - datetime.fromisoformat(last)
	if late > STALE_AFTER:
		return [f"the last backup was {late.days} days ago: see `systemctl --user status francken-tv-backup` (docs/03-when-something-breaks.md)"]
	return []


# ---- the command line -------------------------------------------------------------------------

def settings_from_config() -> tuple[str, dict]:
	from .config import load_config, project_path
	config = load_config()
	photos, backup = config.get("event_photos", {}), config.get("backup", {})
	return photos.get("server", ""), {
		"folder": backup.get("folder", "backups/francken-tv"),
		"keep": backup.get("keep", 1),
		"credentials": project_path(photos.get("credentials", "~/.config/slideshow/nextcloud.credentials.json")),
	}


def main(argv: list[str] | None = None) -> int:
	parser = argparse.ArgumentParser(prog="python -m francken_tv.backup", description=__doc__.split("\n")[0])
	parser.add_argument("command", choices=["setup", "backup", "list", "restore"])
	parser.add_argument("--force", action="store_true", help="restore: replace files that exist already")
	parser.add_argument("--server", help="the Nextcloud address (default: [event_photos] server in config.toml)")
	args = parser.parse_args(argv)
	logging.basicConfig(level=logging.INFO, format="%(message)s")
	server, settings = settings_from_config()
	server = args.server or server

	if args.command == "setup":
		first, second = getpass.getpass("New passphrase for the backups: "), getpass.getpass("Again: ")
		if not first or first != second:
			print("Not the same, or empty. Nothing changed.")
			return 1
		PASSPHRASE_FILE.parent.mkdir(parents=True, exist_ok=True)
		PASSPHRASE_FILE.write_text(first, encoding="utf-8")
		os.chmod(PASSPHRASE_FILE, 0o600)
		print(f"Saved in {PASSPHRASE_FILE}.\nGive the passphrase to the board for their password manager: without it a backup can't be opened.")
		return 0

	if args.command == "backup":
		username, password = load_credentials(settings["credentials"])
		nextcloud = Nextcloud(server, username, password)
		passphrase = PASSPHRASE_FILE.read_text(encoding="utf-8")
		for message in run_backup(nextcloud, settings["folder"], settings["keep"], passphrase, datetime.now()):
			print(message)
		return 0

	# list and restore: on a new PC the Nextcloud login isn't there yet (it is in the backup), so it is asked for.
	if settings["credentials"].exists():
		username, password = load_credentials(settings["credentials"])
	else:
		username, password = input("Nextcloud username (ask the board): "), getpass.getpass("Nextcloud password: ")
	nextcloud = Nextcloud(server, username, password)
	if args.command == "list":
		for part in PARTS:
			print(part, *backups_of(nextcloud, settings["folder"], part) or ["(none)"])
		return 0
	passphrase = getpass.getpass("Backup passphrase (ask the board): ")
	for message in run_restore(nextcloud, settings["folder"], passphrase, args.force):
		print(message)
	return 0


if __name__ == "__main__":
	sys.exit(main())
