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
from datetime import date, datetime
from pathlib import Path
from xml.etree import ElementTree

from PIL import Image, ImageDraw, ImageFont, ImageOps

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
EVENT_SLIDE_PATTERN = "eventpicture_*.png"
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
		selected_event_names = {Path(remote_path).name for _, remote_path in events[:3]}
		EVENTS_PATH.mkdir(parents=True, exist_ok=True)
		for cached_event in EVENTS_PATH.iterdir():
			if cached_event.is_dir() and cached_event.name not in selected_event_names:
				shutil.rmtree(cached_event)
		local_images = []
		for _, remote_path in events[:3]:
			event_directory = EVENTS_PATH / Path(remote_path).name
			event_directory.mkdir(parents=True, exist_ok=True)
			remote_images = [
				remote_file
				for remote_file, is_directory in client._list(remote_path)
				if not is_directory and remote_file != remote_path
				and Path(remote_file).suffix.lower() in IMAGE_EXTENSIONS
			]
			remote_by_name = {Path(remote_file).name: remote_file for remote_file in remote_images}
			cached = [path for path in event_directory.iterdir() if path.is_file() and path.name in remote_by_name]
			missing_names = [name for name in remote_by_name if name not in {path.name for path in cached}]
			for filename in random.sample(missing_names, min(20 - len(cached), len(missing_names))):
				remote_file = remote_by_name[filename]
				relative_path = Path(remote_file).relative_to(Path(remote_path))
				local_path = event_directory / relative_path
				local_path.parent.mkdir(parents=True, exist_ok=True)
				client.download(remote_file, local_path)
			cached = [path for path in event_directory.rglob("*") if path.is_file() and path.suffix.lower() in IMAGE_EXTENSIONS]
			local_images.extend(cached[:20])
		if not local_images:
			raise RuntimeError("No supported images found in the three newest events")
		return local_images
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


def choose_random_event_image(images: list[Path]) -> Path:
	groups: dict[str, list[Path]] = {}
	for image in images:
		relative = image.relative_to(EVENTS_PATH)
		if relative.parts:
			groups.setdefault(relative.parts[0], []).append(image)
	if not groups:
		raise RuntimeError("No event images are available")
	event_images = random.choice(list(groups.values()))
	selected = random.choice(event_images)
	with Image.open(selected) as image:
		is_portrait = image.height > image.width
	if not is_portrait or len(event_images) < 2:
		return _make_event_slide(selected, None)
	other = random.choice([image for image in event_images if image != selected])
	return _make_event_slide(selected, other)


def _make_event_slide(first_path: Path, second_path: Path | None) -> Path:
	event_name = first_path.relative_to(EVENTS_PATH).parts[0]
	event_title = _event_description(event_name)
	filename_title = re.sub(r"[^A-Za-z0-9]+", "_", event_title).strip("_").lower()
	output = PROJECT_DIR / "slides" / f"eventpicture_{filename_title}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.png"
	temporary = output.with_suffix(".tmp.png")
	with Image.open(first_path) as first:
		first = ImageOps.exif_transpose(first).convert("RGB")
		if second_path is None:
			combined = first.copy()
		else:
			with Image.open(second_path) as second:
				second = ImageOps.exif_transpose(second).convert("RGB")
				height = max(first.height, second.height)
				first.thumbnail((height, height), getattr(Image, "Resampling", Image).LANCZOS)
				second.thumbnail((height, height), getattr(Image, "Resampling", Image).LANCZOS)
				combined = Image.new("RGB", (first.width + second.width, height), "black")
				combined.paste(first, (0, (height - first.height) // 2))
				combined.paste(second, (first.width, (height - second.height) // 2))
		draw = ImageDraw.Draw(combined, "RGBA")
		label = _event_description(event_name)
		font = ImageFont.truetype("/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf", max(24, combined.width // 65))
		left = max(24, combined.width // 35)
		bottom = max(24, combined.height // 28)
		text_box = draw.textbbox((left, 0), label, font=font)
		draw.rectangle((left - 16, combined.height - bottom - (text_box[3] - text_box[1]) - 18, text_box[2] + 16, combined.height - bottom + 12), fill=(0, 0, 0, 165))
		draw.text((left, combined.height - bottom - (text_box[3] - text_box[1])), label, font=font, fill=(255, 255, 255, 235))
		combined.save(temporary, format="PNG")
	for old_slide in output.parent.glob(EVENT_SLIDE_PATTERN):
		if old_slide != temporary:
			old_slide.unlink()
	temporary.rename(output)
	return output


def _event_description(event_name: str) -> str:
	event_date = date.fromisoformat(event_name[:10])
	title = event_name[11:].replace("-", " ").replace("_", " ").strip().title()
	return f"{event_date.strftime('%d %b %Y').upper()}  ·  {title}"