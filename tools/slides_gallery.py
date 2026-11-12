"""Every slide of the slideshow on one self-contained web page, to look through without the TV.

	python3 tools/slides_gallery.py                         -> data/slides_gallery.html
	python3 tools/slides_gallery.py --out /tmp/slides.html
	python3 tools/slides_gallery.py --time "2026-11-11 15:30"   the moment the slides are drawn for

Public data is fetched for real (activities, news, weather, buses, timetable, books, puzzles, xkcd,
quote, ...). Everything private or not on this PC is made up: posters, event photos, people in the
room, the confidential contact persons, the extern, Spotify, Instagram, the Francken Vrij. No real
personal data ends up in the page, so it's safe to share (e.g. as an artifact on claude.ai).

It works on a copy of the project in a temporary folder, so data/ and config/ here are left alone.
Every image, font and script is put inside the HTML (no server needed); interactive buttons don't
do anything. Needs the same Python packages as the slideshow (requirements.txt).
"""

from __future__ import annotations

import argparse
import base64
import concurrent.futures
import io
import json
import logging
import mimetypes
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time as monotonic_time
from datetime import date, datetime, time, timedelta
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
LEFT_OUT = {".git", "data", "media", ".venv", "__pycache__", "devices.json", "confidential.json", "extern.json"}
MAP_ZOOMS = range(0, 4)   # world map tiles for TimeGuessr (85 tiles)
NAVY, CRIMSON, GOLD, CREAM = (23, 50, 73), (190, 30, 45), (255, 196, 0), (247, 243, 233)
# The channel buttons in groups, and the slides in this order. A slide belongs to the first group that
# names its key, or its key up to the number ("news" for news-2); anything else lands in "Other".
GROUPS = [
	("What's on", ["poster", "activities", "practice"]),
	("Today", ["news", "weather", "rain", "buses", "timetable"]),
	("The room", ["presence", "leaderboard", "pet", "poll", "streep"]),
	("Puzzles", ["puzzles", "connections", "wordle", "catfishing", "timeguessr"]),
	("Music", ["spotify", "spotify-lyrics", "lyric-video"]),
	("Photos and socials", ["event-photo", "event-photos", "instagram", "socials"]),
	("Committees and contacts", ["confidential", "extern", "compucie", "borrelcie", "fotocie"]),
	("Join and buy", ["membership", "socks", "books", "francken-vrij", "francken-vrij-subscribe"]),
	("Fun", ["quote", "commandments", "xkcd", "graafmachine"]),
	("Full screen", ["bieruur-countdown", "bieruur", "vrijmibo"]),
	("Other", []),
]


def group_of(key: str) -> int:
	for number, (_, keys) in enumerate(GROUPS):
		if key in keys or re.sub(r"-\d+$", "", key) in keys:
			return number
	return len(GROUPS) - 1


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	parser.add_argument("--out", type=Path, default=ROOT / "data" / "slides_gallery.html")
	parser.add_argument("--time", type=datetime.fromisoformat, metavar='"YYYY-MM-DD HH:MM"',
		help="draw the slides for this moment (default: today at 15:30)")
	parser.add_argument("--inside", action="store_true", help=argparse.SUPPRESS)   # running in the copy
	args = parser.parse_args()
	now = args.time or datetime.combine(date.today(), time(15, 30))
	out = args.out.resolve()
	if args.inside:
		build(now, out)
		return
	with tempfile.TemporaryDirectory(prefix="francken-gallery-") as folder:
		copy = Path(folder) / "slideshow"
		shutil.copytree(ROOT, copy, ignore=lambda _, names: [n for n in names if n in LEFT_OUT])
		out.parent.mkdir(parents=True, exist_ok=True)
		subprocess.run([sys.executable, "tools/slides_gallery.py", "--inside", "--out", str(out), "--time", now.isoformat()],
			cwd=copy, check=True)
	print(f"Written: {out}")


# ---- made-up pictures ---------------------------------------------------------------------------------

def font(size: int):
	from PIL import ImageFont
	try:
		return ImageFont.truetype(str(ROOT / "francken_tv/static/vendor/familjen-grotesk/familjen-grotesk-700.woff"), size)
	except OSError:
		return ImageFont.load_default(size)


def poster(path: Path, size: tuple[int, int], background, ink, lines: list[tuple[str, float]], accent=None) -> None:
	from PIL import Image, ImageDraw
	image = Image.new("RGB", size, background)
	draw = ImageDraw.Draw(image)
	width, height = size
	if accent:
		draw.ellipse([width * 0.55, -height * 0.2, width * 1.3, height * 0.6], fill=accent)
		draw.rectangle([0, height * 0.82, width, height], fill=accent)
	y = height * 0.18
	for text, share in lines:
		draw.text((width * 0.07, y), text, font=font(int(height * share)), fill=ink)
		y += height * share * 1.3
	path.parent.mkdir(parents=True, exist_ok=True)
	image.save(path)


def photo(path: Path, size: tuple[int, int], seed: int) -> None:
	"""A dusky crowd under party lights: enough to look like an event photo from a distance."""
	from PIL import Image, ImageDraw
	rng = random.Random(seed)
	image = Image.new("RGB", size)
	draw = ImageDraw.Draw(image)
	width, height = size
	top = (rng.randint(20, 80), rng.randint(30, 90), rng.randint(80, 160))
	bottom = (rng.randint(150, 230), rng.randint(90, 160), rng.randint(40, 110))
	for y in range(height):
		draw.line([(0, y), (width, y)], fill=tuple(int(a + (b - a) * y / height) for a, b in zip(top, bottom)))
	for _ in range(40):
		x, y, r = rng.random() * width, height * 0.45 + rng.random() * height * 0.6, rng.randint(int(height * 0.04), int(height * 0.14))
		draw.ellipse([x - r, y - r, x + r, y + r * 2.4], fill=(rng.randint(10, 60),) * 3)
	for _ in range(14):
		x, y, r = rng.random() * width, rng.random() * height * 0.4, rng.randint(4, 18)
		draw.ellipse([x - r, y - r, x + r, y + r], fill=(255, 230, 150))
	path.parent.mkdir(parents=True, exist_ok=True)
	image.save(path, quality=85)


def magazine_pages(folder: Path) -> list[Path]:
	from PIL import Image, ImageDraw
	titles = ["", "Contents", "From the board", "", "Lustrum report", "", "Puzzle page", "", "Interview", "", "Column", "See you at bieruur"]
	pages = []
	for number, title in enumerate(titles, start=1):
		path = folder / f"{number:02}.png"
		if number == 1:
			poster(path, (707, 1000), NAVY, (255, 255, 255), [("Francken", 0.09), ("Vrij", 0.12), ("Volume 30 · Issue 2", 0.035)], accent=CRIMSON)
		else:
			poster(path, (707, 1000), (250, 248, 242), (30, 30, 30), [(title, 0.05)] if title else [])
			with Image.open(path) as image:
				draw = ImageDraw.Draw(image)
				for k in range(22 if title else 26):
					top = (260 if title else 120) + k * 30
					draw.rectangle([60, top, 640 - (k * 37) % 180, top + 12], fill=(175, 175, 175))
				draw.text((340, 950), str(number), font=font(22), fill=(80, 80, 80))
				image.save(path)
		pages.append(path)
	return pages


def fake_files(project: Path, now: datetime) -> None:
	from PIL import Image, ImageDraw
	poster(project / "media/slides/01-symposium.png", (1920, 1080), NAVY, (255, 255, 255),
		[("SYMPOSIUM", 0.12), ("Physics of the very small", 0.06), ("Thursday · Aletta Jacobshal", 0.045)], accent=CRIMSON)
	poster(project / "media/slides/02-excursion.png", (1080, 1350), CREAM, NAVY,
		[("Excursion", 0.09), ("to the", 0.05), ("synchrotron", 0.09), ("Sign up on the website", 0.035)], accent=GOLD)
	frames = []
	for i in range(12):
		frame = Image.new("RGB", (960, 540), GOLD if i % 2 else CRIMSON)
		ImageDraw.Draw(frame).text((80 + i * 12, 200), "VRIJMIBO!", font=font(140), fill=NAVY if i % 2 else (255, 255, 255))
		frames.append(frame)
	frames[0].save(project / "media/vrijmibo.gif", save_all=True, append_images=frames[1:], duration=150, loop=0)
	photo(project / "media/extern/photo.jpg", (800, 1000), 9)
	(project / "config/confidential.json").write_text(json.dumps({
		"email": "confidential@example.org", "website": "https://www.professorfrancken.nl/",
		"people": [{"name": name, "email": f"{name.lower().replace(' ', '.')}@example.org"}
			for name in ("Sam de Vries", "Noor Bakker", "Jesse Visser")]}))
	(project / "config/extern.json").write_text(json.dumps({
		"ask": "Ask our extern!", "photo": "media/extern/photo.jpg",
		"contacts": [{"label": "Phone", "value": "+31 6 1234 5678"}, {"label": "Email", "value": "extern@example.org"}]}))
	sys.path.insert(0, str(project / "tools"))
	import fake_presence   # the dummy people of tools/fake_presence.py, in the copy's database
	fake_presence.add(now)


# ---- the slides ---------------------------------------------------------------------------------------

def prepare(now: datetime):
	"""The app in this (copied) project folder, with today's public data fetched and the private things made up:
	the config and the app. Also used by tools/emulator.py."""
	logging.basicConfig(level=logging.ERROR)
	project = Path.cwd()
	sys.path.insert(0, str(project))
	fake_files(project, now)

	from francken_tv.app import build_app
	from francken_tv.clock import Clock
	from francken_tv.config import CACHE_DIR, DEFAULT_CONFIG, load_config
	from francken_tv.providers.activities import Activity
	from francken_tv.providers.francken_vrij import Issue
	from francken_tv.providers.instagram import Post
	from francken_tv.providers.spotify import NowPlaying
	from francken_tv.slides import media_url

	config = load_config(DEFAULT_CONFIG)
	app = build_app(config, Clock(now))
	providers = app.providers
	made_up = {"spotify", "lyric_video", "event_photos", "instagram", "francken_vrij"}

	def refresh(provider) -> None:
		try:
			provider.refresh(now)
		except Exception as error:
			print(f"  {provider.name}: could not refresh ({error})")
	print("Fetching the public data...")
	with concurrent.futures.ThreadPoolExecutor(16) as pool:
		list(pool.map(refresh, [p for name, p in providers.items() if name not in made_up]))

	# Practice sessions, so that slide shows up.
	providers["activities"].activities += [
		Activity(now.date() + timedelta(days=days), f"Practice session {course}", start, "", room)
		for days, course, start, room in [(1, "Linear Algebra", "17:00", "5161.0105"),
			(6, "Electrodynamics", "18:00", "5161.0151"), (8, "Quantum Physics 1", "17:00", "5173.0045")]]
	providers["activities"].activities.sort(key=lambda activity: activity.day)
	providers["membership"].months = set(range(1, 13))
	providers["francken_vrij"].issue = Issue("Volume 30 · Issue 2", magazine_pages(CACHE_DIR / "fake_magazine"), 0.707, {1, 2, 3, 5, 7, 9, 11})

	captions = ["Bieruur!", "Symposium recap", "Meet the new board", "Excursion day", "Pub quiz night",
		"Lustrum gala", "Study session", "BBQ on the roof", "Welcome week"]
	posts = []
	for i, caption in enumerate(captions):
		photo(CACHE_DIR / f"fake_instagram/{i}.jpg", (600, 600), 100 + i)
		posts.append(Post("", "", now - timedelta(days=3 * i + 1), 40 + i * 7, i, caption=caption,
			picture=media_url(CACHE_DIR / f"fake_instagram/{i}.jpg")))
	instagram = providers["instagram"]
	instagram.posts = posts
	instagram.profile = {"username": instagram.username or "francken", "name": "T.F.V. 'Professor Francken'",
		"picture": posts[0].picture, "followers_count": 812, "media_count": 245}

	spotify = providers["spotify"]
	spotify.credentials = lambda: {"refresh_token": "made up"}
	photo(CACHE_DIR / "fake_cover.jpg", (640, 640), 77)
	cover = media_url(CACHE_DIR / "fake_cover.jpg")
	spotify.playing = NowPlaying("made-up", "Mr. Brightside", "The Killers", "Hot Fuss", cover, 222000, 61000, True,
		monotonic_time.monotonic(), 65, spotify.speaker)
	spotify.next = {"title": "Don't Stop Me Now", "artist": "Queen", "uri": "spotify:track:made-up", "cover": cover}
	return config, app


def draw(config: dict, app, now: datetime) -> list[dict]:
	"""Every slide drawn once, sorted by group: {"key", "label", "group", "seconds", "html"}."""
	from francken_tv.config import CACHE_DIR
	from francken_tv.server import make_templates
	from francken_tv.slides import Slide, media_url

	providers = app.providers
	templates = make_templates()
	slides: list[dict] = []

	def add(key: str, label: str, slide) -> None:
		if slide is None:
			print(f"  {key}: no slide")
			return
		try:
			data = slide.update(now) if slide.update else slide.data
			slides.append({"key": key, "label": label, "seconds": slide.seconds,
				"html": templates.get_template(f"slides/{slide.template}").render(**data)})
		except Exception as error:
			print(f"  {key}: could not draw it ({error!r})")

	print("Drawing the slides...")
	photos = [CACHE_DIR / f"fake_photos/{i}.jpg" for i in range(3)]
	for i, path in enumerate(photos):
		photo(path, (1600, 1067) if i == 0 else (1067, 1600), i)
	for name in config["rotation"]["order"]:
		provider = providers[name]
		title = provider.title or name.replace("_", " ").capitalize()
		if name == "images":
			for i, slide in enumerate(provider.slides(now)):
				add(f"poster-{i + 1}", f"Poster {i + 1}", slide)
		elif name == "event_photos":
			add("event-photo", "Event photo", Slide("photo.html", 10, {"urls": [media_url(photos[0])],
				"title": "Halloween borrel", "day": now.date() - timedelta(days=12)}))
			add("event-photos", "Event photos, two portraits", Slide("photo.html", 10, {"urls": [media_url(p) for p in photos[1:]],
				"title": "Lustrum gala", "day": now.date() - timedelta(days=26)}))
		elif name == "news":
			for i in range(len(provider.feeds) if hasattr(provider, "feeds") else 3):
				add(f"news-{i + 1}", f"News {i + 1}", provider.shortcut_slide(now))   # the next feed each time
		elif name == "weather":
			add("weather", "Weather", provider.shortcut_slide(now))
			add("rain", "Rain warning", provider.rain_preview(now))
		elif name == "puzzles":
			add("puzzles", title, provider.shortcut_slide(now))
			for puzzle in ("connections", "wordle", "catfishing", "timeguessr"):
				add(puzzle, providers[puzzle].title or puzzle.capitalize(), providers[puzzle].shortcut_slide(now))
		elif name == "spotify":
			add("spotify", "Spotify", provider.shortcut_slide(now))
			add("spotify-lyrics", "Spotify lyrics", provider.lyrics_slide())
		else:
			add(name.replace("_", "-"), title, provider.shortcut_slide(now))
	friday = now.date() + timedelta(days=(4 - now.weekday()) % 7)
	bieruur_time = time.fromisoformat(config.get("bieruur", {}).get("time", "16:00"))
	add("bieruur", "Bieruur (full screen)", app.takeovers["bieruur"].slide(
		datetime.combine(friday, bieruur_time) - timedelta(seconds=30)))
	add("vrijmibo", "Vrijmibo", app.takeovers["vrijmibo"].slide(datetime.combine(friday, time(13, 0))))

	slides.sort(key=lambda slide: group_of(slide["key"]))   # stable: within a group, the order of the rotation
	for slide in slides:
		slide["group"] = GROUPS[group_of(slide["key"])][0]
	return slides


def build(now: datetime, out: Path) -> None:
	project = Path.cwd()
	config, app = prepare(now)
	slides = draw(config, app, now)

	print("Putting every picture inside the page...")
	assets = Assets(project)
	for slide in slides:
		slide["html"] = assets.inline(slide["html"])
	tiles = {}
	if app.tiles:
		for z in MAP_ZOOMS:
			for x in range(2 ** z):
				for y in range(2 ** z):
					path = app.tiles.get(z, x, y)
					if path:
						tiles[f"{z}/{x}/{y}"] = assets.add(path.read_bytes(), "image/png")
	out.write_text(page(project, slides, assets.uris, tiles, now), encoding="utf-8")
	print(f"{len(slides)} slides, {out.stat().st_size // 1024} KB")


class Assets:
	"""Images as data: URIs, each stored once (the Francken Vrij uses each page 24 times); the slides
	refer to them as @@asset-N@@, which the page swaps back in when it shows a slide."""

	PATTERN = re.compile(r"""(?:(?:src|href|poster)=["']|url\(\s*['"]?|url\(&#39;)(?P<url>(?:/files/|/static/|https?://)[^"'\s)&]+(?:&amp;[^"'\s)&]+)*)""")
	PICTURE = re.compile(r"\.(png|jpe?g|gif|webp|svg|mp4|wav)(\?|$)|upload\.wikimedia|covers\.openlibrary|imgs\.xkcd|/images?/|/media/", re.I)

	def __init__(self, project: Path) -> None:
		self.project = project
		self.uris: list[str] = []
		self.found: dict[str, str] = {}

	def add(self, body: bytes, mime: str) -> str:
		self.uris.append(f"data:{mime};base64,{base64.b64encode(body).decode()}")
		return f"@@asset-{len(self.uris) - 1}@@"

	def get(self, url: str) -> str:
		if url in self.found:
			return self.found[url]
		import requests
		path = unquote(url.split("?")[0])
		try:
			if path.startswith("/files/"):
				file = self.project / path.removeprefix("/files/")
				body, mime = file.read_bytes(), mimetypes.guess_type(file.name)[0]
			elif path.startswith("/static/"):
				file = self.project / "francken_tv" / path.removeprefix("/")
				body, mime = file.read_bytes(), mimetypes.guess_type(file.name)[0]
			else:
				response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Francken TV)"})
				response.raise_for_status()
				body, mime = response.content, response.headers.get("Content-Type", "image/jpeg").split(";")[0]
		except Exception as error:
			print(f"  could not fetch {url[:80]}: {error}")
			self.found[url] = url
			return url
		body, mime = shrink(body, mime or "application/octet-stream")
		self.found[url] = self.add(body, mime)
		return self.found[url]

	def inline(self, html: str) -> str:
		def replace(match: re.Match) -> str:
			url = match["url"]
			if url.startswith("http") and not self.PICTURE.search(url):
				return match[0]   # a link, not a picture
			return match[0].replace(url, self.get(url.replace("&amp;", "&")))
		return self.PATTERN.sub(replace, html)


def shrink(body: bytes, mime: str) -> tuple[bytes, str]:
	"""Large photos as smaller JPEGs, to keep the page well under the size limit of an artifact."""
	if len(body) < 300_000 or mime not in ("image/png", "image/jpeg", "image/webp"):
		return body, mime
	from PIL import Image
	with Image.open(io.BytesIO(body)) as image:
		image = image.convert("RGB")
		image.thumbnail((1600, 1600))
		smaller = io.BytesIO()
		image.save(smaller, "JPEG", quality=80)
	return smaller.getvalue(), "image/jpeg"


# ---- the page -----------------------------------------------------------------------------------------

def inline_css(css: str, folder: Path) -> str:
	"""url("vendor/...") in a stylesheet as data: URIs."""
	def replace(match: re.Match) -> str:
		file = folder / match[1]
		if match[1].startswith("data:") or not file.is_file():
			return match[0]
		mime = mimetypes.guess_type(file.name)[0] or ("font/woff2" if file.suffix == ".woff2" else "application/octet-stream")
		return f'url("data:{mime};base64,{base64.b64encode(file.read_bytes()).decode()}")'
	return re.sub(r"""url\(["']?([^"')]+)["']?\)""", replace, css)


def page(project: Path, slides: list[dict], assets: list[str], tiles: dict, now: datetime) -> str:
	static = project / "francken_tv" / "static"
	style = inline_css((static / "style.css").read_text(encoding="utf-8"), static)
	leaflet_css = inline_css((static / "vendor/leaflet/leaflet.css").read_text(encoding="utf-8"), static / "vendor/leaflet")
	scripts = "\n".join((static / name).read_text(encoding="utf-8") for name in
		["vendor/leaflet/leaflet.js", "vendor/qrcode/qrcode.js", "widgets.js"])
	frame = FRAME.replace("/*STYLE*/", leaflet_css + "\n" + style).replace("/*SCRIPTS*/", scripts.replace("</script", "<\\/script"))
	grotesk = base64.b64encode((static / "vendor/familjen-grotesk/familjen-grotesk-700.woff2").read_bytes()).decode()
	data = {"slides": slides, "assets": assets, "tiles": tiles, "frame": frame,
		"drawn": now.strftime("%A %-d %B %Y, %H:%M")}
	return (GALLERY.replace("/*GROTESK*/", grotesk)
		.replace("/*DATA*/", json.dumps(data).replace("</", "<\\/")))


# The document inside the iframe: 1920 x 1080 like the TV, so the slides' vw and vh come out right.
FRAME = """<!doctype html><html lang="en"><head><meta charset="utf-8"><style>/*STYLE*/
body { cursor: default; } .layer.visible { opacity: 1; }</style></head><body>
<script>/*SCRIPTS*/</script>
<script>
window.showSlide = function (html, tiles) {
	if (window.L && !L.TileLayer.prototype.__gallery) {   // map tiles from the page, not from the server
		L.TileLayer.prototype.__gallery = true;
		L.TileLayer.prototype.getTileUrl = function (c) {
			const z = Math.max(0, Math.min(3, c.z)), n = 2 ** z, k = 2 ** (c.z - z);
			return window.galleryTiles[`${z}/${((Math.floor(c.x / k) % n) + n) % n}/${Math.floor(c.y / k)}`] || "";
		};
		L.TileLayer.prototype.options.maxNativeZoom = 3;
	}
	window.galleryTiles = tiles;
	document.querySelectorAll(".layer").forEach((old) => old.remove());
	const layer = document.createElement("div");
	layer.className = "layer visible";
	layer.innerHTML = html;
	document.body.prepend(layer);
	try { setupWidgets(layer); } catch (error) { console.warn(error); }
};
document.addEventListener("keydown", (event) => parent.postMessage({ key: event.key }, "*"));
document.addEventListener("click", (event) => { if (event.target.closest("a")) event.preventDefault(); });
</script></body></html>"""


GALLERY = """<title>Francken TV slides</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* Layout: the TV in a dark room. One 16:9 screen, the controls under it like a remote, every slide as a channel button. */
@font-face { font-family: "Familjen Grotesk"; font-weight: 700; src: url("data:font/woff2;base64,/*GROTESK*/") format("woff2"); }
:root {
	--room: #0e1319;
	--bezel: #05080b;
	--panel: #172029;
	--line: #26323e;
	--ink: #eef1f4;
	--muted: #8d9aa8;
	--crimson: #c8283a;
	--gold: #ffc400;
	--display: "Familjen Grotesk", "Helvetica Neue", Arial, sans-serif;
	--text: system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
	color-scheme: dark;
}
html, body { background: var(--room); color: var(--ink); }
body { font-family: var(--text); font-size: 15px; line-height: 1.45; }
.wrap { max-width: 1240px; margin: 0 auto; padding-block: 20px 40px;
	padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
	display: grid; gap: 18px; }
header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 20px; }
h1 { font-family: var(--display); font-weight: 700; font-size: clamp(24px, 3.4vw, 34px); margin: 0; letter-spacing: -0.01em; }
h1 span { color: var(--crimson); }
.note { color: var(--muted); margin: 0; font-size: 13px; }
.tv { background: var(--bezel); border-radius: 14px; padding: clamp(6px, 1.2vw, 14px); box-shadow: 0 30px 60px -30px #000; }
.screen { position: relative; aspect-ratio: 16 / 9; max-width: 100%; overflow: hidden; border-radius: 4px; background: #000; }
.screen iframe { position: absolute; top: 0; left: 0; width: 1920px; height: 1080px; border: 0; transform-origin: 0 0; }
.remote { display: flex; flex-wrap: wrap; align-items: center; gap: 10px 14px; }
.remote .now { flex: 1 1 220px; min-width: 0; display: flex; align-items: baseline; gap: 12px; }
.now strong { font-family: var(--display); font-size: 22px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.now .count { color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }
.buttons { display: flex; gap: 8px; }
button { font: inherit; color: var(--ink); background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
	padding: 8px 14px; cursor: pointer; }
button:hover { border-color: var(--muted); }
button:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
#play[aria-pressed="true"] { background: var(--crimson); border-color: var(--crimson); }
.progress { height: 3px; background: var(--line); border-radius: 2px; overflow: hidden; }
.progress i { display: block; height: 100%; width: 0; background: var(--gold); }
.channels { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: 14px 24px; }
.channels section { display: grid; gap: 6px; align-content: start; min-width: 0; }
.channels h2 { font: 600 11px/1.2 var(--text); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin: 0; }
.channels div { display: flex; flex-wrap: wrap; gap: 6px; }
.channels button { padding: 5px 10px; font-size: 13px; color: var(--muted); }
.channels button.on { color: var(--room); background: var(--gold); border-color: var(--gold); }
.hint { color: var(--muted); font-size: 13px; margin: 0; }
kbd { font: 12px/1 ui-monospace, monospace; border: 1px solid var(--line); border-radius: 4px; padding: 2px 5px; }
@media (prefers-reduced-motion: reduce) { .progress i { transition: none !important; } }
</style>
<div class="wrap">
	<header>
		<h1>Francken <span>TV</span></h1>
		<p class="note" id="drawn"></p>
	</header>
	<div class="tv"><div class="screen" id="screen"><iframe id="frame" title="Slide" tabindex="-1"></iframe></div></div>
	<div class="progress" aria-hidden="true"><i id="bar"></i></div>
	<div class="remote">
		<div class="now"><strong id="name"></strong><span class="count" id="count"></span></div>
		<div class="buttons">
			<button id="prev" aria-label="Previous slide">&larr;</button>
			<button id="play" aria-pressed="false">Play</button>
			<button id="again" aria-label="Replay this slide's animation">Replay</button>
			<button id="next" aria-label="Next slide">&rarr;</button>
		</div>
	</div>
	<nav class="channels" id="channels" aria-label="All slides"></nav>
	<p class="hint"><kbd>&larr;</kbd> <kbd>&rarr;</kbd> previous and next, <kbd>space</kbd> play through them all, each for as long as on the TV. Private things (posters, photos, people, Spotify, Instagram) are made up; the rest is today's real data. Buttons on the slides don't do anything here.</p>
</div>
<script>
const DATA = /*DATA*/;
const slides = DATA.slides, frame = document.getElementById("frame"), screen = document.getElementById("screen");
const fill = (html) => html.replace(/@@asset-(\\d+)@@/g, (_, n) => DATA.assets[n]);
const tiles = Object.fromEntries(Object.entries(DATA.tiles).map(([k, v]) => [k, fill(v)]));
let index = 0, playing = false, timer = null, ready = false;
document.getElementById("drawn").textContent = `Drawn for ${DATA.drawn}`;

const channels = document.getElementById("channels"), channelButtons = [];
let row = null;
slides.forEach((slide, i) => {
	if (!row || slide.group !== slides[i - 1].group) {   // the slides come sorted by group
		const section = document.createElement("section"), heading = document.createElement("h2");
		heading.textContent = slide.group;
		row = document.createElement("div");
		section.append(heading, row);
		channels.append(section);
	}
	const button = document.createElement("button");
	button.textContent = slide.label;
	button.addEventListener("click", () => show(i));
	row.append(button);
	channelButtons.push(button);
});

function fit() { frame.style.transform = `scale(${screen.clientWidth / 1920})`; }
new ResizeObserver(fit).observe(screen);

function show(i) {
	index = (i + slides.length) % slides.length;
	const slide = slides[index];
	if (ready) frame.contentWindow.showSlide(fill(slide.html), tiles);
	document.getElementById("name").textContent = slide.label;
	document.getElementById("count").textContent = `${index + 1} / ${slides.length}`;
	channelButtons.forEach((b, n) => b.classList.toggle("on", n === index));
	try { history.replaceState(null, "", `#${slide.key}`); } catch (e) {}
	schedule();
}

function schedule() {
	clearTimeout(timer);
	const bar = document.getElementById("bar");
	bar.style.transition = "none"; bar.style.width = "0";
	if (!playing) return;
	const seconds = Math.min(Math.max(slides[index].seconds || 8, 4), 40);
	requestAnimationFrame(() => requestAnimationFrame(() => {
		bar.style.transition = `width ${seconds}s linear`; bar.style.width = "100%";
	}));
	timer = setTimeout(() => show(index + 1), seconds * 1000);
}

function togglePlay() {
	playing = !playing;
	const play = document.getElementById("play");
	play.textContent = playing ? "Pause" : "Play";
	play.setAttribute("aria-pressed", String(playing));
	schedule();
}

function key(k) {
	if (k === "ArrowRight" || k === "ArrowDown") show(index + 1);
	else if (k === "ArrowLeft" || k === "ArrowUp") show(index - 1);
	else if (k === " ") togglePlay();
}
document.addEventListener("keydown", (e) => {
	if (e.target.closest("button") && e.key === " ") return;
	if (["ArrowRight", "ArrowLeft", "ArrowUp", "ArrowDown", " "].includes(e.key)) { e.preventDefault(); key(e.key); }
});
window.addEventListener("message", (e) => { if (e.source === frame.contentWindow && e.data?.key) key(e.data.key); });
document.getElementById("prev").onclick = () => show(index - 1);
document.getElementById("next").onclick = () => show(index + 1);
document.getElementById("again").onclick = () => show(index);
document.getElementById("play").onclick = togglePlay;
window.addEventListener("hashchange", () => {
	const i = slides.findIndex((s) => `#${s.key}` === location.hash);
	if (i >= 0 && i !== index) show(i);
});

frame.addEventListener("load", () => { ready = true; fit(); show(index); });
const start = slides.findIndex((s) => `#${s.key}` === location.hash);
index = start >= 0 ? start : 0;
frame.srcdoc = DATA.frame;
</script>
"""


if __name__ == "__main__":
	main()
