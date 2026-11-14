"""Made-up data for the slides that have none on a development PC, to see them in ./start.sh and at /preview/<name>.

	python3 tools/fake_slides.py                 add made-up data for every slide below that has none
	python3 tools/fake_slides.py ero extern      only these
	python3 tools/fake_slides.py --remove        take all made-up data out again
	python3 tools/fake_slides.py --list          which slides it can fake, and which are faked now

Slides: ero, confidential, extern, images, event_photos, francken_vrij, vrijmibo, presence (the leaderboard too).
A slide that already has real data is skipped, never overwritten. Everything it creates (files and the
folders that didn't exist yet) is written down in data/fake_slides.json; --remove deletes exactly that and
nothing else. The names are made up, the e-mail addresses are example.org, the pictures are generated.
The presence slides are tools/fake_presence.py (it keeps its own record); --remove takes those out too.
Restart the slideshow, or just reload /preview/<name>: the slides read their files again every round.
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from francken_tv.config import DEFAULT_CONFIG, load_config, project_path   # noqa: E402
from slides_gallery import CREAM, CRIMSON, GOLD, NAVY, font, magazine_pages, photo, poster   # noqa: E402

MANIFEST = ROOT / "data/fake_slides.json"
NAMES = ["ero", "confidential", "extern", "images", "event_photos", "francken_vrij", "vrijmibo", "presence"]
IMAGES = {".png", ".jpg", ".jpeg", ".webp", ".gif"}


class Skip(Exception):
	"""This slide can't be faked (real data is there, or it needs something else)."""


class Dry(Exception):
	"""For --list: the checks passed, so it could be faked (nothing is written)."""


class Made:
	"""What one slide created: written to the manifest as it goes."""

	def __init__(self, dry: bool = False) -> None:
		self.dry = dry
		self.files: list[Path] = []
		self.folders: list[Path] = []

	def checked(self) -> None:
		"""Call once the slide's checks are done and before anything is written."""
		if self.dry:
			raise Dry

	def folder(self, folder: Path) -> None:
		missing = []
		while not folder.exists():
			missing.append(folder)
			folder = folder.parent
		for path in reversed(missing):
			path.mkdir()
			self.folders.append(path)

	def file(self, path: Path) -> Path:
		"""Call before writing: makes the folder and notes the file (the file must be new)."""
		if path.exists():
			raise Skip(f"{rel(path)} already exists")
		self.folder(path.parent)
		self.files.append(path)
		return path


def rel(path: Path) -> str:
	return str(path.relative_to(ROOT))


def settings(name: str) -> dict:
	return load_config(DEFAULT_CONFIG).get(name, {})


def folder_of(name: str, key: str, default: str) -> Path:
	return project_path(settings(name).get(key, default))


def images_in(folder: Path) -> list[Path]:
	return [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in IMAGES] if folder.is_dir() else []


# ---- one function per slide: makes the files, or raises Skip ------------------------------------------

def fake_ero(made: Made) -> None:
	folder = folder_of("ero", "folder", "media/ERO")
	if images_in(folder):
		raise Skip(f"{rel(folder)}/ has pictures")
	made.checked()
	for index, name in enumerate(["Sam", "Noor", "Jesse", "Robin", "Eva"], start=3):
		photo(made.file(folder / f"{name}.png"), (600, 600), index)


def fake_confidential(made: Made) -> None:
	path = project_path(settings("confidential").get("file", "config/confidential.json"))
	if path.exists():
		raise Skip(f"{rel(path)} exists")
	made.checked()
	people = []
	for index, name in enumerate(["Sam de Vries", "Noor Bakker", "Jesse Visser"], start=20):
		picture = Path("media/confidential") / f"fake-{name.split()[0].lower()}.jpg"
		photo(made.file(ROOT / picture), (500, 500), index)
		people.append({"name": name, "email": f"{name.lower().replace(' ', '.')}@example.org", "photo": str(picture)})
	made.file(path).write_text(json.dumps({"email": "confidential@example.org",
		"website": "https://www.professorfrancken.nl/", "people": people}, indent="\t") + "\n", encoding="utf-8")


def fake_extern(made: Made) -> None:
	path = project_path(settings("extern").get("file", "config/extern.json"))
	if path.exists():
		raise Skip(f"{rel(path)} exists")
	made.checked()
	picture, background = Path("media/extern/fake-photo.jpg"), Path("media/extern/fake-background.png")
	photo(made.file(ROOT / picture), (800, 1000), 9)
	poster(made.file(ROOT / background), (1920, 1080), NAVY, (255, 255, 255), [], accent=CRIMSON)
	made.file(path).write_text(json.dumps({
		"questions": ["Internship?", "Job?", "Thesis?"], "ask": "Ask our extern - Alex Example",
		"contacts": [{"label": "Phone", "value": "+31 6 1234 5678", "note": "(also WhatsApp)"},
			{"label": "Email", "value": "extern@example.org"}],
		"photo": str(picture), "background": str(background)}, indent="\t") + "\n", encoding="utf-8")


def fake_images(made: Made) -> None:
	folder = folder_of("images", "folder", "media/slides")
	if images_in(folder):
		raise Skip(f"{rel(folder)}/ has images")
	made.checked()
	poster(made.file(folder / "fake-symposium.png"), (1920, 1080), NAVY, (255, 255, 255),
		[("SYMPOSIUM", 0.12), ("Physics of the very small", 0.06), ("Thursday · Aletta Jacobshal", 0.045)], accent=CRIMSON)
	poster(made.file(folder / "fake-excursion.png"), (1080, 1350), CREAM, NAVY,
		[("Excursion", 0.09), ("to the", 0.05), ("synchrotron", 0.09), ("Sign up on the website", 0.035)], accent=GOLD)
	poster(made.file(folder / "fake-quiz.png"), (1350, 1080), GOLD, NAVY,
		[("PUB QUIZ", 0.14), ("Friday from 20:00", 0.06)], accent=CRIMSON)


def fake_event_photos(made: Made) -> None:
	# albums_folder is a folder on the Nextcloud server, not on this PC: the provider only knows photos it
	# downloaded itself (refresh() needs the credentials), so there's nothing to write that it would pick up.
	raise Skip("the albums are read from Nextcloud (needs ~/.config/slideshow/nextcloud.credentials.json), not a local folder")


def fake_francken_vrij(made: Made) -> None:
	folder = folder_of("francken_vrij", "folder", "media/francken-vrij")
	if folder.is_dir() and any(p.suffix.lower() == ".pdf" for p in folder.iterdir()):
		raise Skip(f"{rel(folder)}/ has a PDF")
	if shutil.which("pdftoppm") is None or shutil.which("pdftohtml") is None:
		raise Skip("needs poppler to read the PDF: sudo apt install poppler-utils")
	made.checked()
	from PIL import Image
	with tempfile.TemporaryDirectory() as temp:
		pages = [Image.open(p).convert("RGB") for p in magazine_pages(Path(temp))]
		pages[0].save(made.file(folder / "30-2-1.pdf"), save_all=True, append_images=pages[1:], resolution=100)


def fake_vrijmibo(made: Made) -> None:
	from PIL import Image, ImageDraw
	path = project_path(settings("vrijmibo").get("file", "media/vrijmibo.gif"))
	if path.exists():
		raise Skip(f"{rel(path)} exists")
	made.checked()
	frames = []
	for i in range(12):
		frame = Image.new("RGB", (960, 540), GOLD if i % 2 else CRIMSON)
		ImageDraw.Draw(frame).text((80 + i * 12, 200), "VRIJMIBO!", font=font(140), fill=NAVY if i % 2 else (255, 255, 255))
		frames.append(frame)
	frames[0].save(made.file(path), save_all=True, append_images=frames[1:], duration=150, loop=0)


FAKERS = {"ero": fake_ero, "confidential": fake_confidential, "extern": fake_extern, "images": fake_images,
	"event_photos": fake_event_photos, "francken_vrij": fake_francken_vrij, "vrijmibo": fake_vrijmibo}
HINTS = {
	"membership": "only in the months in [membership] months: out of season /preview/membership shows nothing until you add the month there",
	"practice": "comes from the activities on the website: it shows when one of them has \"practice session\" in its title",
	"vrijmibo": "shown on Fridays only: /preview/vrijmibo works on a Friday (or set weekday in [vrijmibo])",
}


# ---- the manifest -------------------------------------------------------------------------------------

def read_manifest() -> dict:
	if not MANIFEST.exists():
		return {}
	return json.loads(MANIFEST.read_text(encoding="utf-8"))


def write_manifest(manifest: dict) -> None:
	if not manifest:
		MANIFEST.unlink(missing_ok=True)
		return
	MANIFEST.parent.mkdir(exist_ok=True)
	MANIFEST.write_text(json.dumps(manifest, indent="\t") + "\n", encoding="utf-8")


def inside(path: Path) -> bool:
	return ROOT in path.resolve().parents


def presence_faked() -> bool:
	import fake_presence
	if not fake_presence.DEVICES.exists():
		return False
	entries = json.loads(fake_presence.DEVICES.read_text(encoding="utf-8"))
	return any(fake_presence.is_fake(e) for e in ([entries] if isinstance(entries, dict) else entries))


def add(names: list[str]) -> None:
	manifest = read_manifest()
	for name in names:
		if name in manifest:
			print(f"{name}: already faked")
			continue
		if name == "presence":
			import fake_presence
			fake_presence.add(datetime.now().replace(microsecond=0))
			continue
		made = Made()
		try:
			FAKERS[name](made)
		except Skip as reason:
			for path in made.files:   # nothing half-made is left behind
				path.unlink(missing_ok=True)
			for folder in reversed(made.folders):
				folder.rmdir()
			print(f"{name}: skipped, {reason}")
			continue
		manifest[name] = {"files": [rel(p) for p in made.files], "folders": [rel(p) for p in made.folders]}
		write_manifest(manifest)   # after each slide, so a crash loses nothing
		print(f"{name}: made {', '.join(manifest[name]['files'])}")
		if name in HINTS:
			print(f"  note: {HINTS[name]}")
	if names == NAMES:
		for name in ("membership", "practice"):
			print(f"{name}: no files to make; {HINTS[name]}")


def remove() -> None:
	manifest = read_manifest()
	for name, made in manifest.items():
		for path in (ROOT / p for p in made["files"]):
			if inside(path) and path.is_file():
				path.unlink()
		for path in (ROOT / p for p in reversed(made["folders"])):
			if inside(path) and path.is_dir() and not any(path.iterdir()):
				path.rmdir()
		print(f"{name}: removed")
	write_manifest({})
	import fake_presence
	if presence_faked():
		fake_presence.remove()
	elif fake_presence.DATABASE.exists():   # only stray fake sightings: leave the real config/devices.json untouched
		from francken_tv.presence_store import PresenceStore
		fake_presence.remove_sightings(PresenceStore(fake_presence.DATABASE))


def list_slides() -> None:
	manifest = read_manifest()
	for name in NAMES:
		if name == "presence":
			state = "faked now" if presence_faked() else "can be faked"
		elif name in manifest:
			state = "faked now"
		else:
			try:
				FAKERS[name](Made(dry=True))
			except Dry:
				state = "can be faked"
			except Skip as reason:
				state = f"skipped: {reason}"
		print(f"{name:15} {state}")
	for name in ("membership", "practice"):
		print(f"{name:15} no files to make; {HINTS[name]}")


if __name__ == "__main__":
	args = sys.argv[1:]
	if "--list" in args:
		list_slides()
	elif "--remove" in args:
		remove()
	else:
		unknown = [a for a in args if a not in NAMES]
		if unknown:
			sys.exit(f"Unknown: {', '.join(unknown)}. Choose from: {', '.join(NAMES)}")
		add(args or NAMES)
