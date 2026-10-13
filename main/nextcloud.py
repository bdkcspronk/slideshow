from __future__ import annotations

import getpass
import json
import re
import base64
import urllib.error
import urllib.parse
import urllib.request
import random
import shutil
from datetime import date
from pathlib import Path
from xml.etree import ElementTree

try:
	import keyring
except ImportError:
	keyring = None

from .config import IMAGE_EXTENSIONS, PROJECT_DIR


NEXTCLOUD_HOST = "https://nextcloud.professorfrancken.nl"
NEXTCLOUD_SERVICE = "slideshow-nextcloud"
CONFIG_PATH = Path.home() / ".config" / "slideshow" / "nextcloud.json"
CREDENTIALS_PATH = Path.home() / ".config" / "slideshow" / "nextcloud.credentials.json"
EVENTS_PATH = PROJECT_DIR / "slides" / "events"
EVENT_NAME = re.compile(r"^(\d{4})-(\d{2})-(\d{2})(?:-|$)")
NETWORK_TIMEOUT_SECONDS = 30


def sync_recent_event_images() -> list[Path]:
	username, password = _load_credentials()
	if username is None:
		username = input("Nextcloud username: ").strip()
		if not username:
			raise RuntimeError("A Nextcloud username is required")
		CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
		CONFIG_PATH.write_text(json.dumps({"username": username}) + "\n", encoding="utf-8")

	if password is None and keyring is not None:
		try:
			password = keyring.get_password(NEXTCLOUD_SERVICE, username)
		except Exception:
			password = None
	if password is None:
		if CREDENTIALS_PATH.is_file():
			raise RuntimeError(f"Could not read credentials from {CREDENTIALS_PATH}")
		password = getpass.getpass("Nextcloud app password: ")
		if not password:
			raise RuntimeError("A Nextcloud app password is required")
		if keyring is not None:
			try:
				keyring.set_password(NEXTCLOUD_SERVICE, username, password)
			except Exception:
				print(f"Could not save to keyring; use {CREDENTIALS_PATH} to avoid future prompts.")

	client = _NextcloudClient(username, password)
	try:
		events = client.recent_events((date.today().year, date.today().year - 1))
		if not events:
			raise RuntimeError(f"No YYYY-MM-DD event folders found for {date.today().year}")
		if EVENTS_PATH.exists():
			shutil.rmtree(EVENTS_PATH)
		EVENTS_PATH.mkdir(parents=True, exist_ok=True)
		downloaded = []
		for _, remote_path in events[:3]:
			remote_images = [
				remote_file
				for remote_file, is_directory in client._list(remote_path)
				if not is_directory and remote_file != remote_path
				and Path(remote_file).suffix.lower() in IMAGE_EXTENSIONS
			]
			for remote_file in random.sample(remote_images, min(10, len(remote_images))):
				relative_path = Path(remote_file).relative_to(Path(remote_path))
				local_path = EVENTS_PATH / Path(remote_path).name / relative_path
				local_path.parent.mkdir(parents=True, exist_ok=True)
				client.download(remote_file, local_path)
				downloaded.append(local_path)
		if not downloaded:
			raise RuntimeError("No supported images found in the three newest events")
		return downloaded
	except (urllib.error.URLError, urllib.error.HTTPError, ElementTree.ParseError) as error:
		raise RuntimeError(f"Could not sync Nextcloud images: {error}") from error


def _load_credentials() -> tuple[str | None, str | None]:
	try:
		credentials = json.loads(CREDENTIALS_PATH.read_text(encoding="utf-8"))
		username = credentials.get("username")
		password = credentials.get("password")
		if isinstance(username, str) and isinstance(password, str) and username and password:
			return username, password
		raise RuntimeError("credentials file must contain non-empty username and password")
	except FileNotFoundError:
		pass
	except (json.JSONDecodeError, OSError, RuntimeError) as error:
		raise RuntimeError(f"Could not read credentials from {CREDENTIALS_PATH}: {error}") from error
	try:
		username = json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("username")
		return username if isinstance(username, str) and username else None, None
	except (FileNotFoundError, json.JSONDecodeError, OSError):
		return None, None


class _NextcloudClient:
	def __init__(self, username: str, password: str) -> None:
		self.base_url = f"{NEXTCLOUD_HOST}/remote.php/dav/files/{urllib.parse.quote(username, safe='')}"
		credentials = base64.b64encode(f"{username}:{password}".encode()).decode("ascii")
		self.auth_header = f"Basic {credentials}"

	def recent_events(self, years: tuple[int, ...]) -> list[tuple[date, str]]:
		events = []
		for year in years:
			root = f"/images/albums/{year}"
			for path, is_directory in self._list(root):
				if not is_directory:
					continue
				match = EVENT_NAME.match(Path(path).name)
				if match:
					events.append((date.fromisoformat("-".join(match.groups())), path))
		return sorted(events, reverse=True)

	def files(self, path: str) -> list[str]:
		result = []
		for child, is_directory in self._list(path):
			result.extend(self.files(child) if is_directory else [child])
		return result

	def download(self, remote_path: str, local_path: Path) -> None:
		request = urllib.request.Request(self._url(remote_path), headers={"Authorization": self.auth_header})
		with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
			local_path.write_bytes(response.read())

	def _list(self, path: str) -> list[tuple[str, bool]]:
		request = urllib.request.Request(
			self._url(path),
			method="PROPFIND",
			headers={"Authorization": self.auth_header, "Depth": "1"},
		)
		with urllib.request.urlopen(request, timeout=NETWORK_TIMEOUT_SECONDS) as response:
			root = ElementTree.fromstring(response.read())
		namespace = "{DAV:}"
		result = []
		for response in root.findall(f"{namespace}response"):
			href = response.findtext(f"{namespace}href")
			if not href:
				continue
			resource = response.find(f".//{namespace}resourcetype/{namespace}collection")
			path = urllib.parse.unquote(urllib.parse.urlparse(href).path)
			if path.startswith(self._dav_prefix):
				path = path[len(self._dav_prefix):]
			result.append((path, resource is not None))
		return result

	@property
	def _dav_prefix(self) -> str:
		return urllib.parse.urlparse(self.base_url).path

	def _url(self, path: str) -> str:
		return self.base_url + "/" + "/".join(urllib.parse.quote(part) for part in path.strip("/").split("/"))