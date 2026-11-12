"""The whole slideshow as a web page that works without the TV PC: the real player (rotation, arrow keys,
number keys, pause), the menu (Esc) with its settings, and the puzzles, playable.

	python3 tools/emulator.py --serve                  build it, then show it at http://127.0.0.1:8090
	python3 tools/emulator.py                          only build it -> data/emulator/
	python3 tools/emulator.py --out /tmp/emulator
	python3 tools/emulator.py --time "2026-11-13 15:30"    the moment it starts at (default: today at 15:30)
	python3 tools/emulator.py --serve --host 0.0.0.0   also reachable from other devices on this network (a TV, a phone)

Needs the Python packages of the slideshow (pip install -r requirements.txt) and internet while it builds;
Pyodide and its packages are downloaded once, to data/cache/pyodide/.

Nothing is rebuilt for it: the page starts Python in the browser (Pyodide) and runs francken_tv itself there,
and player.js asks it what it would ask the server (tools/emulator_runtime.py). What a browser page can't do
is left out: there's no network, so the data is what was fetched when this ran (as in tools/slides_gallery.py,
with the same made-up private things, and made-up quotes), and nothing makes sound, plays on Spotify or shuts
a PC down. Settings and puzzle progress start over when the page is reloaded.

The folder is a plain website: index.html and the files next to it. Any web server can show it, on any
device with a recent browser: --serve here, `python3 -m http.server` in the folder, or the folder uploaded to
a web host (it holds the slideshow's code and config/config.toml, but not devices.json, confidential.json
or extern.json: think before putting it somewhere public). Only opening index.html from disk doesn't work: a
browser doesn't let such a page read the files next to it.

--artifact writes index.html the way claude.ai wants an artifact's page (without the lines every web page
starts with; it adds its own), to publish there with the other files as its files.
"""

from __future__ import annotations

import argparse
import base64
import functools
import http.server
import importlib.util
import json
import mimetypes
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from contextlib import closing
from datetime import date, datetime, time, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYODIDE = "https://cdn.jsdelivr.net/pyodide/v0.26.4/full/"
PYODIDE_FILES = ["pyodide.js", "pyodide.asm.js", "pyodide.asm.wasm", "pyodide-lock.json"]   # published as they are
PACKAGES = ["jinja2", "pillow", "beautifulsoup4", "requests", "sqlite3"]   # requirements.txt, and what Pyodide leaves out of Python
BUNDLED = ["francken_tv", "config", "media", "data", "tools/emulator_runtime.py"]   # of the project, into the page
PACK_BYTES = 9_000_000   # per project-N.json: files of a size every web host takes (an artifact's can be 16 MB each)
QUOTES = """Tijdstempel,name,Quote
1-9-2026 12:00:00,Alice,I only came for the free lunch and now I'm on a committee
8-9-2026 16:05:00,Bob,"It's not a bug, it's a boundary condition"
15-9-2026 10:30:00,Charlie,Is the coffee machine a closed system?
22-9-2026 17:45:00,Dana,I'll hand it in before the deadline. Which deadline is a different question
29-9-2026 13:15:00,Eve,"Assume the cow is spherical. No, more spherical"
6-10-2026 15:59:00,Frank,One minute to bieruur is still lecture time
"""   # the columns of the quotes sheet
EXTRA = {"weather": [("rain", "Rain warning")], "spotify": [("spotify-lyrics", "Spotify lyrics")],
	"puzzles": [("connections", ""), ("wordle", ""), ("catfishing", ""), ("timeguessr", "")]}   # more buttons after a slide type's own


def main() -> None:
	parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
	parser.add_argument("--out", type=Path, default=ROOT / "data" / "emulator")
	parser.add_argument("--time", type=datetime.fromisoformat, metavar='"YYYY-MM-DD HH:MM"',
		help="the moment the emulator starts at (default: today at 15:30)")
	parser.add_argument("--serve", action="store_true", help="after building, show it in a browser: a small web server until Ctrl+C")
	parser.add_argument("--host", default="127.0.0.1", help="with --serve: who can reach it (default: only this PC; 0.0.0.0: the whole network)")
	parser.add_argument("--port", type=int, default=8090, help="with --serve (default: 8090)")
	parser.add_argument("--artifact", action="store_true", help="index.html as an artifact page for claude.ai instead of a web page")
	parser.add_argument("--fake-ero", action="store_true", help="made-up officers instead of the real pictures of media/ERO/ (always, with --artifact: real faces stay off public hosts)")
	parser.add_argument("--fresh", action="store_true", help="fetch everything again instead of using what the last build fetched (kept %d hours)" % CACHE_HOURS)
	parser.add_argument("--http-cache", type=Path, help=argparse.SUPPRESS)   # in the copy; where the last builds' downloads are kept
	parser.add_argument("--inside", type=Path, help=argparse.SUPPRESS)   # running in the copy; the folder with Pyodide
	args = parser.parse_args()
	now = args.time or datetime.combine(date.today(), time(15, 30))
	out = args.out.resolve()
	if args.inside:
		if args.http_cache and not args.fresh:
			cache_downloads(args.http_cache)
		build(now, out, args.inside, args.artifact)
		return
	missing = [name for name, module in {"jinja2": "jinja2", "requests": "requests", "beautifulsoup4": "bs4", "pillow": "PIL"}.items()
		if importlib.util.find_spec(module) is None]
	if missing:
		raise SystemExit(f"Missing Python packages: {', '.join(missing)}. Install the slideshow's packages first: pip install -r requirements.txt")
	sys.path.insert(0, str(ROOT / "tools"))
	import slides_gallery
	pyodide = download_pyodide(ROOT / "data" / "cache" / "pyodide")
	with tempfile.TemporaryDirectory(prefix="francken-emulator-") as folder:
		copy = Path(folder) / "slideshow"
		shutil.copytree(ROOT, copy, ignore=lambda _, names: [n for n in names if n in slides_gallery.LEFT_OUT])
		if not (args.fake_ero or args.artifact) and (ROOT / "media" / "ERO").is_dir():
			shutil.copytree(ROOT / "media" / "ERO", copy / "media" / "ERO")   # the copy has no media/: slides_gallery makes up the rest
		subprocess.run([sys.executable, "tools/emulator.py", "--inside", str(pyodide), "--out", str(out), "--http-cache", str(ROOT / "data" / "cache" / "emulator_http"), "--time", now.isoformat(),
			*(["--artifact"] if args.artifact else []), *(["--fresh"] if args.fresh else [])], cwd=copy, check=True)
	print(f"Written: {out}/", flush=True)
	if args.serve:
		serve(out, args.host, args.port)


CACHE_HOURS = 6


def cache_downloads(folder: Path) -> None:
	"""Builds fetch the same public data and pictures every time, into a copy of the project that is thrown away
	afterwards. Keep every plain GET (no login) for CACHE_HOURS in `folder`, outside that copy, so the next build is quick."""
	import hashlib
	import pickle
	import time as time_module
	import requests
	folder.mkdir(parents=True, exist_ok=True)
	send = requests.Session.send

	def cached(session, request, **kwargs):
		if request.method != "GET" or kwargs.get("stream") or {"Authorization", "Cookie"} & set(request.headers):
			return send(session, request, **kwargs)
		path = folder / hashlib.sha256(request.url.encode()).hexdigest()
		if path.exists() and time_module.time() - path.stat().st_mtime < CACHE_HOURS * 3600:
			try:
				response = pickle.loads(path.read_bytes())
				response.request = request
				return response
			except Exception:
				pass
		response = send(session, request, **kwargs)
		if response.ok:
			try:
				path.write_bytes(pickle.dumps(response))
			except Exception:
				pass
		return response
	requests.Session.send = cached


def serve(folder: Path, host: str, port: int) -> None:
	handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(folder))
	with http.server.ThreadingHTTPServer((host, port), handler) as server:
		where = "this PC's address on the network" if host in ("0.0.0.0", "::") else host
		print(f"The emulator is at http://{where}:{port}/ (Ctrl+C stops it)", flush=True)
		try:
			server.serve_forever()
		except KeyboardInterrupt:
			pass


def download_pyodide(folder: Path) -> Path:
	"""Pyodide, and the packages the slideshow needs with everything they need in turn (as listed in its lock file)."""
	import requests
	folder.mkdir(parents=True, exist_ok=True)

	def fetch(name: str) -> Path:
		path = folder / name
		if not path.exists():
			print(f"  downloading {name}")
			response = requests.get(PYODIDE + name, timeout=120)
			response.raise_for_status()
			path.write_bytes(response.content)
		return path

	for name in [*PYODIDE_FILES, "python_stdlib.zip"]:
		fetch(name)
	for name in package_files(folder):
		fetch(name)
	return folder


def package_files(folder: Path) -> list[str]:
	packages = {name.lower(): package for name, package in json.loads((folder / "pyodide-lock.json").read_text())["packages"].items()}
	needed, todo = [], list(PACKAGES)
	while todo:
		name = todo.pop().lower()
		if name not in needed:
			needed.append(name)
			todo += packages[name]["depends"]
	return sorted(packages[name]["file_name"] for name in needed)


# ---- in the copy: fetch, draw once, and pack everything -------------------------------------------------

def build(now: datetime, out: Path, pyodide: Path, artifact: bool = False) -> None:
	import emulator_runtime
	import slides_gallery as gallery
	project = Path.cwd()
	config, app = gallery.prepare(now)
	slides = gallery.draw(config, app, now)   # also to know which pictures from the internet the slides show

	from francken_tv.config import CACHE_DIR, DATA_DIR
	from francken_tv.providers.event_photos import Album, Photo
	albums = [Album("", now.date() - timedelta(days=12), "Halloween borrel"), Album("", now.date() - timedelta(days=26), "Lustrum gala")]
	app.providers["event_photos"].photos = [Photo(CACHE_DIR / f"fake_photos/{i}.jpg", albums[min(i, 1)], portrait=i > 0) for i in range(3)]
	# The gallery shows one real quote; this page would carry the whole sheet, with everyone's name: made-up ones instead.
	from francken_tv.providers.quote import read_quotes
	quote = app.providers["quote"]
	quote.csv_path.write_text(QUOTES, encoding="utf-8")
	quote.quotes, quote.last_quote = read_quotes(QUOTES), None
	if app.tiles:   # the world map for TimeGuessr, up to the zoom level the page asks for
		for z in gallery.MAP_ZOOMS:
			for x in range(2 ** z):
				for y in range(2 ** z):
					app.tiles.get(z, x, y)

	print("Fetching the pictures the slides show...")
	pictures = fetch_pictures(slides, CACHE_DIR / "emulator_pictures", project)
	state, left_out = emulator_runtime.snapshot(app)
	(project / emulator_runtime.STATE).write_bytes(state)
	(project / emulator_runtime.INFO).write_text(json.dumps({"now": now.isoformat()}))
	database = DATA_DIR / "presence.sqlite3"
	if database.exists():   # as one plain file: the browser's files can't do SQLite's write-ahead log
		with closing(sqlite3.connect(database)) as connection:
			connection.execute("PRAGMA journal_mode=DELETE")

	if out.exists():
		shutil.rmtree(out)
	(out / "pyodide").mkdir(parents=True)
	for name in PYODIDE_FILES:
		shutil.copy(pyodide / name, out / "pyodide" / name)
	wheels = ["python_stdlib.zip", *package_files(pyodide)]
	(out / "pyodide" / "packages.json").write_text(json.dumps({name: encoded(pyodide / name) for name in wheels}))
	packs = pack(project, out)

	friday = now.date() + timedelta(days=(4 - now.weekday()) % 7)
	bieruur = time.fromisoformat(config.get("bieruur", {}).get("time", "16:00"))
	info = {
		"root": str(project), "packs": packs, "packages": PACKAGES, "pictures": pictures,
		"zoom": max(gallery.MAP_ZOOMS), "channels": channels(config, app, gallery),
		"moments": [
			{"label": "Right now", "time": "now"},   # the real time: the buses fetched while building are still to come
			{"label": "When it was built", "time": now.isoformat(sep=" ")},
			{"label": "30 s before bieruur", "time": (datetime.combine(friday, bieruur) - timedelta(seconds=30)).isoformat(sep=" ")},
			{"label": "Friday 13:00", "time": datetime.combine(friday, time(13, 0)).isoformat(sep=" ")},
			{"label": "Tonight 21:00", "time": datetime.combine(now.date(), time(21, 0)).isoformat(sep=" ")},
		],
	}
	static = project / "francken_tv" / "static"
	grotesk = encoded(static / "vendor/familjen-grotesk/familjen-grotesk-700.woff2")
	page = PAGE.replace("/*GROTESK*/", grotesk).replace("/*INFO*/", json.dumps(info).replace("</", "<\\/"))
	(out / "index.html").write_text(page if artifact else DOCUMENT.replace("/*PAGE*/", page), encoding="utf-8")
	size = sum(file.stat().st_size for file in out.rglob("*") if file.is_file())
	print(f"{len(info['channels'])} slide types, {len(pictures) // 2} pictures, {packs} project files, {size // 1_000_000} MB in all")
	if left_out:
		print(f"  not carried over (made again in the browser): {', '.join(left_out)}")


def encoded(path: Path) -> str:
	return base64.b64encode(path.read_bytes()).decode()


def fetch_pictures(slides: list[dict], folder: Path, project: Path) -> dict[str, str]:
	"""Every picture from the internet in the drawn slides, saved in the project: {its URL: the /files/ URL of
	the copy}, also for the URL as it's written in HTML (&amp;)."""
	import requests
	import slides_gallery as gallery
	folder.mkdir(parents=True, exist_ok=True)
	pictures: dict[str, str] = {}
	for slide in slides:
		for match in gallery.Assets.PATTERN.finditer(slide["html"]):
			written = match["url"]
			url = written.replace("&amp;", "&")
			if not url.startswith("http") or not gallery.Assets.PICTURE.search(url) or url in pictures:
				continue
			try:
				response = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0 (Francken TV)"})
				response.raise_for_status()
			except requests.RequestException as error:
				print(f"  could not fetch {url[:80]}: {error}")
				continue
			body, kind = gallery.shrink(response.content, response.headers.get("Content-Type", "image/jpeg").split(";")[0])
			path = folder / f"{len(pictures)}{mimetypes.guess_extension(kind) or '.jpg'}"
			path.write_bytes(body)
			pictures[url] = pictures[written] = f"/files/{path.relative_to(project).as_posix()}"
	return pictures


def pack(project: Path, out: Path) -> int:
	"""The project's files as project-0.json, project-1.json, ...: {path: the file in base64}. An artifact
	serves .json but not .py, .toml or a database, and this way it's a few files instead of hundreds."""
	files = []
	for name in BUNDLED:
		path = project / name
		files += [path] if path.is_file() else sorted(file for file in path.rglob("*") if file.is_file()
			and "__pycache__" not in file.parts and file.suffix != ".tmp")
	packs: list[dict[str, str]] = [{}]
	size = 0
	for file in files:
		data = encoded(file)
		if size and size + len(data) > PACK_BYTES:
			packs.append({})
			size = 0
		packs[-1][file.relative_to(project).as_posix()] = data
		size += len(data)
	for number, content in enumerate(packs):
		(out / f"project-{number}.json").write_text(json.dumps(content))
	return len(packs)


def channels(config: dict, app, gallery) -> list[dict]:
	"""The page's buttons: every slide type of the rotation, in the gallery's groups."""
	found = []
	for name in config["rotation"]["order"]:
		for key, label in [(name, ""), *EXTRA.get(name, [])]:
			provider = app.providers.get(key)
			label = label or (provider.title if provider else "") or key.replace("_", " ").capitalize()
			group = gallery.group_of({"images": "poster", "event_photos": "event-photo"}.get(key, key.replace("_", "-")))
			found.append({"name": key, "label": label, "group": gallery.GROUPS[group][0], "order": group})
	found.sort(key=lambda channel: channel.pop("order"))
	return found


# ---- the page -------------------------------------------------------------------------------------------
# The TV is an iframe of 1920 x 1080 holding the real player.html, with its styles and scripts written into it.
# Whatever it fetches (and every /files/, /static/ and /tiles/ URL in what comes back) is answered by Python.

# What every web page starts with; claude.ai adds this itself around an artifact's page (--artifact).
DOCUMENT = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<style>body { margin: 0; }</style>
</head>
<body>
/*PAGE*/</body>
</html>
"""

PAGE = """<title>Francken TV emulator</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
/* Layout: the TV in a dark room. One 16:9 screen with the real slideshow in it; under it the keys it listens to,
   a clock that can be set, and every slide type as a channel button. */
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
	--mono: ui-monospace, "SF Mono", Menlo, Consolas, monospace;
	color-scheme: dark;
}
[hidden] { display: none !important; }
html, body { background: var(--room); color: var(--ink); }
body { font-family: var(--text); font-size: 15px; line-height: 1.45; }
.wrap { max-width: 1240px; margin: 0 auto; padding-block: 20px 40px;
	padding-left: max(16px, env(safe-area-inset-left, 0px)); padding-right: max(16px, env(safe-area-inset-right, 0px));
	display: grid; gap: 18px; }
header { display: flex; flex-wrap: wrap; align-items: baseline; justify-content: space-between; gap: 6px 20px; }
h1 { font-family: var(--display); font-weight: 700; font-size: clamp(24px, 3.4vw, 34px); margin: 0; letter-spacing: -0.01em; }
h1 span { color: var(--crimson); }
.clock { color: var(--muted); margin: 0; font-size: 13px; font-variant-numeric: tabular-nums; }
.tv { background: var(--bezel); border-radius: 14px; padding: clamp(6px, 1.2vw, 14px); box-shadow: 0 30px 60px -30px #000; }
.screen { position: relative; aspect-ratio: 16 / 9; max-width: 100%; overflow: hidden; border-radius: 4px; background: #000; }
.screen iframe { position: absolute; top: 0; left: 0; width: 1920px; height: 1080px; border: 0; transform-origin: 0 0; }
.starting { position: absolute; inset: 0; display: grid; place-content: center; gap: 10px; text-align: center; padding: 16px; }
.starting strong { font-family: var(--display); font-size: clamp(18px, 3vw, 28px); }
.starting span { color: var(--muted); }
.starting pre { color: var(--gold); font: 12px/1.5 var(--mono); white-space: pre-wrap; overflow-wrap: anywhere; text-align: left;
	max-height: 40vh; overflow: auto; margin: 0; }
.keys { display: flex; flex-wrap: wrap; gap: 6px 18px; margin: 0; padding: 0; list-style: none; color: var(--muted); font-size: 13px; }
kbd { font: 12px/1 var(--mono); color: var(--ink); border: 1px solid var(--line); border-radius: 4px; padding: 2px 5px; }
button { font: inherit; color: var(--ink); background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
	padding: 5px 10px; font-size: 13px; cursor: pointer; }
button:hover { border-color: var(--muted); }
button:focus-visible { outline: 2px solid var(--gold); outline-offset: 2px; }
button:disabled { opacity: 0.5; cursor: default; }
.groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(min(100%, 280px), 1fr)); gap: 14px 24px; }
.groups section { display: grid; gap: 6px; align-content: start; min-width: 0; }
h2 { font: 600 11px/1.2 var(--text); letter-spacing: 0.08em; text-transform: uppercase; color: var(--muted); margin: 0; }
.row { display: flex; flex-wrap: wrap; gap: 6px; }
.said { color: var(--gold); font-size: 13px; margin: 0; min-height: 1.45em; }
.note { color: var(--muted); font-size: 13px; margin: 0; max-width: 75ch; }
</style>
<div class="wrap">
	<header>
		<h1>Francken <span>TV</span></h1>
		<p class="clock" id="clock"></p>
	</header>
	<div class="tv"><div class="screen" id="screen">
		<iframe id="frame" title="The slideshow" hidden></iframe>
		<div class="starting" id="starting"><strong>Starting the slideshow</strong><span id="step">Loading Python...</span></div>
	</div></div>
	<ul class="keys">
		<li><kbd>Esc</kbd> menu and settings</li>
		<li><kbd>&larr;</kbd> <kbd>&rarr;</kbd> previous, next</li>
		<li><kbd>space</kbd> pause</li>
		<li><kbd>1</kbd>&ndash;<kbd>7</kbd> shortcuts</li>
		<li><kbd>m</kbd> mute</li>
		<li>click a puzzle to play it</li>
	</ul>
	<p class="said" id="said" role="status"></p>
	<section class="groups" aria-label="Pretend it is">
		<section><h2>Set the clock to</h2><div class="row" id="moments"></div></section>
	</section>
	<nav class="groups" id="channels" aria-label="Jump to a slide type"></nav>
	<p class="note">This is the slideshow's own code, running in your browser. It has no network: the data is from when the page was built, and Spotify, sound and the power buttons have nothing to control. Private things (posters, photos, people, Spotify, Instagram) are made up. Settings and puzzle progress start over when you reload.</p>
</div>
<script src="pyodide/pyodide.js"></script>
<script>
const INFO = /*INFO*/;
const frame = document.getElementById("frame"), screen = document.getElementById("screen");
let runtime = null;

function bytes(text) {
	const raw = atob(text), out = new Uint8Array(raw.length);
	for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
	return out;
}
const decode = (data) => new TextDecoder().decode(data);
function say(text) { document.getElementById("said").textContent = text || ""; }

// ---- asking Python, and turning its URLs into things a page without a server can show ----------------

function ask(method, path, body = "") {
	const answer = runtime.request(method, path, body);
	const [status, type, data] = answer.toJs();
	answer.destroy();
	return { status, type, data };
}

const blobs = new Map();
function blobUrl(url) {   // "/files/media/slides/poster.png?v=3" -> "blob:..."; the URL itself if there's no such file
	const path = url.replace(/&amp;/g, "&");
	if (!blobs.has(path)) {
		const answer = ask("GET", path);
		blobs.set(path, answer.status === 200 ? URL.createObjectURL(new Blob([answer.data], { type: answer.type })) : null);
	}
	return blobs.get(path) || url;
}

function dataUrl(path) {   // for fonts in a stylesheet
	const answer = ask("GET", path);
	if (answer.status !== 200) return path;
	let text = "";
	for (let i = 0; i < answer.data.length; i += 0x8000) text += String.fromCharCode.apply(null, answer.data.subarray(i, i + 0x8000));
	return `data:${answer.type};base64,${btoa(text)}`;
}

const LOCAL = /(?<=["'(;\\s])\\/(?:files|static|tiles)\\/(?:(?!&#39;|&quot;|&#34;)[^"'\\s)\\\\<>])+/g;
function rewrite(text) {
	for (const [url, local] of Object.entries(INFO.pictures)) if (text.includes(url)) text = text.split(url).join(local);
	return text.replace(LOCAL, (url) => blobUrl(url));
}

const sheets = new Map();
function stylesheet(href) {
	if (!sheets.has(href)) {
		const folder = href.slice(0, href.lastIndexOf("/") + 1);
		sheets.set(href, decode(ask("GET", href).data).replace(/url\\(\\s*["']?([^"')]+)["']?\\s*\\)/g, (all, url) =>
			/^(data:|https?:|#)/.test(url) ? all : `url("${dataUrl(url.startsWith("/") ? url : folder + url)}")`));
	}
	return sheets.get(href);
}

// Inside every document shown in a frame, before anything else runs.
const SHIM = `(() => {
	let host = window.parent;
	while (!host.emulator && host !== host.parent) host = host.parent;
	window.emulator = host.emulator;
	window.fetch = (url, options) => window.emulator.fetch(String(url), options || {});
	new MutationObserver(() => {   // the menu's previews: frames of /preview/<slide type>
		for (const preview of document.querySelectorAll('iframe[src^="/preview/"]')) {
			const path = preview.getAttribute("src");
			preview.removeAttribute("src");
			preview.srcdoc = window.emulator.page(path);
		}
	}).observe(document, { childList: true, subtree: true });
})();`;
// After Leaflet: map tiles from Python's cache (the world up to INFO.zoom, stretched when zoomed in further).
const TILES = `L.TileLayer.prototype.getTileUrl = function (c) {
	const z = Math.max(0, Math.min(${INFO.zoom}, c.z)), n = 2 ** z, k = 2 ** (c.z - z);
	return window.emulator.tile(z, ((Math.floor(c.x / k) % n) + n) % n, Math.floor(c.y / k));
};
L.TileLayer.prototype.options.maxNativeZoom = ${INFO.zoom};`;

window.emulator = {
	fetch(url, options) {
		// Firefox brings the TV's old page back when the page is reloaded, and it asks before Python runs: not yet.
		if (!runtime) return Promise.reject(new Error("the slideshow is still starting"));
		try {
			const answer = ask(options.method || "GET", url, options.body || "");
			const text = /json|html/.test(answer.type) ? rewrite(decode(answer.data)) : null;
			if (text !== null && url.startsWith("/api/shortcut/go-")) say(JSON.parse(text).message);
			return Promise.resolve(new Response(text ?? answer.data, { status: answer.status, headers: { "Content-Type": answer.type } }));
		} catch (error) {
			console.error(error);
			say(String(error).split("\\n").filter(Boolean).pop());
			return Promise.reject(error);
		}
	},
	// A page of the server as one document: its stylesheets and scripts written into it.
	page(path) {
		const kept = [];
		const keep = (text) => `\\u0000${kept.push(text) - 1}\\u0000`;
		let html = decode(ask("GET", path).data);
		html = html.replace(/<link rel="stylesheet" href="([^"]+)">/g, (_, href) => keep(`<style>${stylesheet(href)}</style>`));
		html = html.replace(/<script src="([^"]+)"><\\/script>/g, (_, src) => keep(
			`<script>${decode(ask("GET", src).data).replace(/<\\/script/g, "<\\\\/script")}<\\/script>`
			+ (src.includes("leaflet") ? `<script>${TILES}<\\/script>` : "")));
		html = rewrite(html).replace(/\\u0000(\\d+)\\u0000/g, (_, n) => kept[n]);
		return html.replace("<head>", () => `<head><script>${SHIM}<\\/script>`);
	},
	tile(z, x, y) {
		const url = blobUrl(`/tiles/${z}/${x}/${y}.png`);
		return url.startsWith("blob:") ? url : "";
	},
};

// ---- the page around the TV --------------------------------------------------------------------------

function fit() { frame.style.transform = `scale(${screen.clientWidth / 1920})`; }
new ResizeObserver(fit).observe(screen);

function group(parent, title) {
	const section = document.createElement("section"), heading = document.createElement("h2"), row = document.createElement("div");
	heading.textContent = title;
	row.className = "row";
	section.append(heading, row);
	parent.append(section);
	return row;
}
function button(row, label, press) {
	const made = document.createElement("button");
	made.textContent = label;
	made.disabled = true;   // until the slideshow runs
	made.addEventListener("click", () => { say(""); press(); frame.contentWindow.focus(); });
	row.append(made);
}
let row = null;
INFO.channels.forEach((channel, i) => {
	if (!row || channel.group !== INFO.channels[i - 1].group) row = group(document.getElementById("channels"), channel.group);
	button(row, channel.label, () => frame.contentWindow.jumpTo(`go-${channel.name}`));
});
for (const moment of INFO.moments) {
	button(document.getElementById("moments"), moment.label, () => {
		runtime.set_time(moment.time);
		showClock();
		frame.contentWindow.next();
	});
}
function showClock() { document.getElementById("clock").textContent = `On the TV it is ${runtime.now()}`; }

// Keys pressed outside the TV go to it, and so does the focus: the next ones arrive there by themselves.
document.addEventListener("keydown", (event) => {
	if (!runtime || frame.hidden || event.ctrlKey || event.metaKey || event.altKey || event.key === "Tab") return;
	if (event.target.closest("button") && (event.key === " " || event.key === "Enter")) return;
	event.preventDefault();
	frame.contentWindow.focus();
	frame.contentDocument.dispatchEvent(new frame.contentWindow.KeyboardEvent("keydown",
		{ key: event.key, code: event.code, shiftKey: event.shiftKey, bubbles: true, cancelable: true }));
});

async function start() {
	const step = (text) => { document.getElementById("step").textContent = text; };
	const packages = await (await fetch("pyodide/packages.json")).json();
	const realFetch = window.fetch.bind(window);
	window.fetch = (url, options) => {   // Python's own library and the packages travel in packages.json
		const name = String(url).split("/").pop().split("?")[0];
		return packages[name] ? Promise.resolve(new Response(bytes(packages[name]))) : realFetch(url, options);
	};
	const pyodide = await loadPyodide({ indexURL: "pyodide/" });
	step("Loading the packages the slideshow uses...");
	await pyodide.loadPackage(INFO.packages);
	step("Unpacking the slideshow...");
	for (let number = 0; number < INFO.packs; number++) {
		const pack = await (await realFetch(`project-${number}.json`)).json();
		for (const [path, data] of Object.entries(pack)) {
			const full = `${INFO.root}/${path}`;
			pyodide.FS.mkdirTree(full.slice(0, full.lastIndexOf("/")));
			pyodide.FS.writeFile(full, bytes(data));
		}
	}
	step("Starting the slideshow...");
	await new Promise((resolve) => setTimeout(resolve, 30));   // so that line is on screen first
	pyodide.runPython(`
import os, sys
os.chdir(${JSON.stringify(INFO.root)})
sys.path[:0] = [${JSON.stringify(INFO.root)}, ${JSON.stringify(INFO.root + "/tools")}]
import emulator_runtime
emulator_runtime.boot()
`);
	runtime = pyodide.pyimport("emulator_runtime");
	frame.srcdoc = window.emulator.page("/");
	frame.addEventListener("load", () => {
		document.getElementById("starting").hidden = true;
		frame.hidden = false;
		fit();
		frame.contentWindow.focus();
		document.querySelectorAll("button").forEach((made) => { made.disabled = false; });
	}, { once: true });
	say("");
	showClock();
	setInterval(showClock, 1000);
}
start().catch((error) => {
	console.error(error);
	document.getElementById("step").textContent = "It didn't start. Copy this to Claude:";
	const detail = document.createElement("pre");
	detail.textContent = String(error && error.message || error).slice(-3000);
	document.getElementById("starting").append(detail);
});
</script>
"""


if __name__ == "__main__":
	main()
